"""Self-check, no network:  python test_core.py"""
import sys, threading, xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import engine
from maltego_xml import TransformError, build_request, local_args, parse_response
from store import Conflict, Store

EXAMPLE = str(Path(__file__).parent.parent / "examples" / "dns_to_ip_local.py")
RESPONSE = """log noise before
<MaltegoMessage><MaltegoTransformResponseMessage><Entities>
 <Entity Type="maltego.Person"><Value>Ann Lee</Value><Weight>100</Weight>
  <DisplayInformation><Label Name="Bio" Type="text/html">hi</Label></DisplayInformation>
  <AdditionalFields>
   <Field Name="link#maltego.link.label" DisplayName="Label">Registrant</Field>
   <Field Name="link#maltego.link.direction" DisplayName="d">output-to-input</Field>
   <Field Name="notes#" DisplayName="Notes">check me</Field>
   <Field Name="person.firstnames" DisplayName="First Names">Ann</Field>
  </AdditionalFields><IconURL>http://x/i.png</IconURL></Entity>
 <Entity Type="acme.Widget"><Value>w1</Value></Entity>
</Entities><UIMessages><UIMessage MessageType="Inform">done</UIMessage></UIMessages>
</MaltegoTransformResponseMessage></MaltegoMessage>"""


def test_protocol():
    ent = {"type": "Domain", "value": "a.com",
           "properties": {"k#": {"name": "k#", "value": "x=y\\z", "displayName": "K"}}}
    assert local_args(ent) == ["a.com", r"k\#=x\=y\\z"]
    assert local_args({"value": "v", "properties": {}}) == ["v"]  # no empty props arg (trx would crash)

    req = ET.fromstring(build_request(ent, {"api.key": "s3"}, 50))
    e = req.find("MaltegoTransformRequestMessage/Entities/Entity")
    assert e.get("Type") == "maltego.Domain" and e.findtext("Value") == "a.com"
    assert req.find(".//TransformFields/Field").text == "s3"
    assert req.find(".//Limits").get("SoftLimit") == "50"

    res, msgs = parse_response(RESPONSE)
    p, w = res
    assert (p["type"], p["value"], p["notes"], p["icon"]) == ("Person", "Ann Lee", "check me", "http://x/i.png")
    assert p["link"] == {"label": "Registrant", "reverse": True}
    assert p["properties"]["person.firstnames"]["value"] == "Ann" and "display.Bio" in p["properties"]
    assert w["type"] == "Phrase" and w["properties"]["maltego.type"]["value"] == "acme.Widget"
    assert msgs == [{"type": "Inform", "text": "done"}]
    try:
        parse_response("<MaltegoMessage><MaltegoTransformExceptionMessage><Exceptions>"
                       "<Exception>bad key</Exception></Exceptions></MaltegoTransformExceptionMessage></MaltegoMessage>")
        assert False
    except TransformError as x:
        assert "bad key" in str(x)


def test_store():
    s = Store(":memory:")
    g = s.create_graph("case1")
    a, created = s.upsert_entity(g, "Domain", "a.com", {"x": {"name": "x", "value": 1, "displayName": "x"}})
    a2, created2 = s.upsert_entity(g, "Domain", "a.com", {"y": {"name": "y", "value": 2, "displayName": "y"}})
    assert created and not created2 and a["id"] == a2["id"] and set(a2["properties"]) == {"x", "y"}
    b, _ = s.upsert_entity(g, "IPAddress", "1.2.3.4", notes="edge router")
    assert s.upsert_link(g, a["id"], b["id"], "Resolves To") == s.upsert_link(g, a["id"], b["id"], "Resolves To")
    assert s.search(g, "edge") == [b["id"]] and s.search(g, 'a.com" OR') == []  # quoted, no FTS injection
    # a second graph is isolated: same (type, value) is a distinct entity
    g2 = s.create_graph("case2")
    a_other, created_other = s.upsert_entity(g2, "Domain", "a.com")
    assert created_other and a_other["id"] != a["id"] and len(s.graph(g)["entities"]) == 2
    c, _ = s.upsert_entity(g, "IPAddress", "5.5.5.5")
    try:  # renaming onto an existing (type, value) is a conflict
        s.update_entity(c["id"], {"value": "1.2.3.4"})
        assert False
    except Conflict:
        pass
    s.delete_entities(g, [b["id"]])
    assert s.graph(g)["links"] == []  # cascade
    try:  # a failed bulk transaction leaves nothing behind
        with s.tx(g):
            s.upsert_entity(g, "Domain", "rolled.back")
            raise RuntimeError
    except RuntimeError:
        pass
    assert not s.search(g, "rolled")


def test_undo_and_evidence():
    s = Store(":memory:")
    g = s.create_graph("case")
    assert s.history(g) == {"canUndo": False, "canRedo": False}
    e, _ = s.upsert_entity(g, "Domain", "x.com")
    f, _ = s.upsert_entity(g, "IPAddress", "9.9.9.9")
    s.upsert_link(g, e["id"], f["id"], "Resolves To")
    assert len(s.graph(g)["entities"]) == 2 and s.history(g)["canUndo"]
    assert s.undo(g) and len(s.graph(g)["entities"]) == 2 and s.graph(g)["links"] == []  # undo the link only
    assert s.undo(g) and len(s.graph(g)["entities"]) == 1  # undo the IP (its own batch)
    assert s.undo(g, redo=True) and len(s.graph(g)["entities"]) == 2  # redo the IP
    # a fresh edit clears the redo stack
    s.upsert_entity(g, "Company", "Acme")
    assert not s.history(g)["canRedo"]
    # evidence: store, attach, read back, download body
    ev = s.add_evidence(g, "To IP [DNS]", {"url": "https://dns/x", "status": 200, "body": b"RAW-BYTES",
                                           "fetched_at": 1})
    assert ev == s.add_evidence(g, "To IP [DNS]", {"url": "https://dns/x", "status": 200, "body": b"RAW-BYTES",
                                                   "fetched_at": 2})  # deduped by (sha, url)
    s.attach_evidence(e["id"], [ev])
    got = s.evidence_for(e["id"])
    assert len(got) == 1 and got[0]["sha256"] and got[0]["url"] == "https://dns/x"
    body, url = s.evidence_body(ev)
    assert body == b"RAW-BYTES" and url == "https://dns/x"


def test_monitors():
    s = Store(":memory:")
    g = s.create_graph("case")
    e, _ = s.upsert_entity(g, "Domain", "x.com")
    mid = s.add_monitor(g, "domain-footprint", [e["id"]], 60)
    m = s.monitors(g)[0]
    assert m["id"] == mid and m["entity_ids"] == [e["id"]] and m["enabled"]
    al = s.add_alert(g, mid, "2 new entities", [e["id"]])
    assert s.alerts(g)[0]["text"] == "2 new entities" and al["seen"] == 0
    s.mark_alerts_seen(g)
    assert s.alerts(g)[0]["seen"] == 1


def test_local_and_remote():
    local = {"id": "l", "kind": "local", "name": "L", "inputType": "Domain", "command": sys.executable,
             "args": [EXAMPLE], "settings": []}
    res, _, ev = engine.run(local, {"type": "Domain", "value": "localhost", "properties": {}}, {})
    assert res and res[0]["type"] == "IPAddress" and res[0]["link"]["label"] == "Resolves To (local)"
    assert ev and b"<MaltegoMessage" in ev[0]["body"]  # raw stdout captured as evidence

    bad = local | {"command": "definitely-not-a-command-xyz"}
    try:
        engine.run(bad, {"type": "Domain", "value": "x", "properties": {}}, {})
        assert False
    except TransformError:
        pass

    class H(BaseHTTPRequestHandler):  # stands in for a maltego-trx server: echoes value + a setting
        def do_POST(self):
            req = ET.fromstring(self.rfile.read(int(self.headers["Content-Length"])))
            v, key = req.findtext(".//Entity/Value"), req.findtext(".//TransformFields/Field")
            body = (f"<MaltegoMessage><MaltegoTransformResponseMessage><Entities><Entity Type='maltego.Phrase'>"
                    f"<Value>{v}:{key}</Value></Entity></Entities></MaltegoTransformResponseMessage></MaltegoMessage>")
            self.send_response(200); self.end_headers(); self.wfile.write(body.encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    remote = {"id": "r", "kind": "remote", "name": "R", "inputType": "Domain", "settings": ["k"],
              "url": f"http://127.0.0.1:{srv.server_port}/run/echo/"}
    res, _, ev = engine.run(remote, {"type": "Domain", "value": "a.com", "properties": {}}, {"k": "KEY", "other": "no"})
    assert res[0]["value"] == "a.com:KEY" and res[0]["link"]["label"] == "R"
    try:  # secrets never go over plain http to a non-loopback host
        engine.run(remote | {"url": "http://example.com/run/x"}, {"type": "Domain", "value": "a", "properties": {}},
                   {"k": "KEY"})
        assert False
    except TransformError:
        pass
    srv.shutdown()


def test_legacy_migration():
    import sqlite3
    db = sqlite3.connect(":memory:")  # build a pre-multigraph DB, then hand its file-like path to Store
    # Store needs a real path to reopen; use a temp file
    import os, tempfile
    p = os.path.join(tempfile.gettempdir(), "osint_legacy_check.db")
    if os.path.exists(p):
        os.remove(p)
    old = sqlite3.connect(p)
    old.executescript("""
    create table entities (id text primary key, type text, value text, label text, icon text,
      properties text default '{}', created_at integer, discovered_by text, notes text, x real, y real, unique(type,value));
    create table links (id text primary key, source_id text, target_id text, label text, direction text, weight real);
    create virtual table entities_fts using fts5(value, label, notes, properties, content='entities', content_rowid='rowid');
    create trigger ent_ai after insert on entities begin insert into entities_fts(rowid,value,label,notes,properties)
      values (new.rowid,new.value,new.label,new.notes,new.properties); end;
    create table settings (name text primary key, value text not null, secret integer not null);""")
    old.execute("insert into entities values ('e1','Domain','a.com',null,null,'{}',1,null,'n',1,2)")
    old.execute("insert into links values ('l1','e1','e1','self','source-to-target',null)")
    old.execute("insert into settings values ('k','v',0)")
    old.commit(); old.close()
    s = Store(p)
    g = s.graphs()
    assert len(g) == 1 and g[0]["entities"] == 1
    assert s.graph(g[0]["id"])["entities"][0]["value"] == "a.com"
    assert s.settings() == {"k": "v"} and s.search(g[0]["id"], "a.com")
    s2 = Store(p)  # reopen is idempotent (no crash)
    assert len(s2.graphs()) == 1
    s.db.close(); s2.db.close()
    try:
        os.remove(p)
    except OSError:
        pass


if __name__ == "__main__":
    test_protocol(); test_store(); test_undo_and_evidence(); test_monitors()
    test_legacy_migration(); test_local_and_remote()
    print("ok")

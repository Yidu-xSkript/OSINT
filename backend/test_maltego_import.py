"""Self-check for Maltego import:  python test_maltego_import.py"""
import io, os, tempfile, zipfile
from pathlib import Path

from maltego_import import _entity_defs, _our_type, parse_mtgx, parse_mtz

HERE = Path(__file__).parent
MALTEGO = Path(r"C:\Program Files (x86)\Paterva\Maltego\v4.13.0")
DOMAIN_DEF = """<MaltegoEntity id="maltego.Domain" displayName="Domain"><Properties value="fqdn" displayValue="fqdn">
 <Fields><Field name="fqdn" type="string" displayName="Domain Name"/><Field name="whois-info" type="string"/></Fields>
</Properties></MaltegoEntity>"""
SERVER_DEF = """<MaltegoEntity id="acme.Server" displayName="Server">
 <BaseEntities><BaseEntity>maltego.Domain</BaseEntity></BaseEntities></MaltegoEntity>"""


def prop(name, value, display="", ro="false"):
    return (f'<mtg:Property name="{name}" displayName="{display or name}" type="string" hidden="false" '
            f'readonly="{ro}"><mtg:Value>{value}</mtg:Value></mtg:Property>')


def node(nid, mtype, props, xy=None, notes=""):
    pos = f'<data key="d2"><mtg:EntityRenderer><mtg:Position x="{xy[0]}" y="{xy[1]}"/></mtg:EntityRenderer></data>' if xy else ""
    return (f'<node id="{nid}"><data key="d1"><mtg:MaltegoEntity type="{mtype}"><mtg:Properties>{"".join(props)}'
            f'</mtg:Properties>{notes}</mtg:MaltegoEntity></data>{pos}</node>')


def edge(s, t, props, ltype="maltego.link.manual-link"):
    return (f'<edge id="{s}{t}" source="{s}" target="{t}"><data key="d3"><mtg:MaltegoLink type="{ltype}">'
            f'<mtg:Properties>{"".join(props)}</mtg:Properties></mtg:MaltegoLink></data></edge>')


def graphml(body):
    return ('<?xml version="1.0" encoding="UTF-8"?><graphml xmlns="http://graphml.graphdrawing.org/xmlns" '
            'xmlns:y="http://www.yworks.com/xml/graphml" xmlns:mtg="http://maltego.paterva.com/xml/mtgx">'
            '<key attr.name="MaltegoEntity" for="node" id="d1"/><key for="node" id="d2" yfiles.type="nodegraphics"/>'
            f'<key attr.name="MaltegoLink" for="edge" id="d3"/><graph edgedefault="directed" id="G">{body}</graph></graphml>')


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def jar_files(jar, suffixes):
    with zipfile.ZipFile(jar) as j:
        return {n: j.read(n) for n in j.namelist() if n.endswith(suffixes)}


def test_mtgx():
    g1 = graphml(
        node("n0", "maltego.Domain", [prop("whois-info", "x"), prop("fqdn", "paterva.com", "Domain Name")], (-125.5, 40),
             "<mtg:Notes>check it</mtg:Notes>")
        + node("n1", "maltego.Person", [prop("person.fullname", "Ann Lee"), prop("person.lastname", "Lee", ro="true")])
        + node("n2", "acme.Hash", [prop("hash", "abc123")])
        + node("n3", "acme.Server", [prop("fqdn", "srv.paterva.com")])
        + node("n4", "maltego.Phrase", [prop("text", "")])  # empty value -> skipped
        + '<node id="n5"><data key="d2"><y:ShapeNode><y:Geometry x="7" y="8" width="1" height="1"/></y:ShapeNode></data>'
          '<data key="d1"><mtg:MaltegoEntity type="maltego.IPv4Address"><mtg:Properties>'
        + prop("ipv4-address", "1.2.3.4") + '</mtg:Properties></mtg:MaltegoEntity></data></node>'
        + edge("n0", "n1", [prop("maltego.link.manual.type", "Registrant", "Label")])
        + edge("n0", "n5", [prop("maltego.link.transform.name", "paterva.v2.DomainToIP"),
                            prop("maltego.link.transform.display-name", "To IP Address")], "maltego.link.transform-link")
        + edge("n2", "n0", [prop("maltego.link.is_reversed", "true")])
        + edge("n0", "n4", [prop("maltego.link.manual.type", "dropped")]))
    g2 = graphml(node("a", "maltego.Phrase", [prop("text", "second graph")]))
    data = zipped({"Graphs/Graph1.graphml": g1, "Graphs/Graph10.graphml": "<bad", "Graphs/Graph2.graphml": g2,
                   "Entities/maltego.Domain.entity": DOMAIN_DEF, "Entities/acme.Server.entity": SERVER_DEF,
                   "Graphs/Graph1.properties": "author="})
    r = parse_mtgx(data)
    ents = {e["id"]: e for e in r["entities"]}
    assert set(ents) == {"n0", "n1", "n2", "n3", "n5"}, ents
    d = ents["n0"]
    assert (d["type"], d["value"], d["position"], d["metadata"]["notes"]) == ("Domain", "paterva.com",
                                                                               {"x": -125.5, "y": 40.0}, "check it")
    assert "fqdn" not in d["properties"] and d["properties"]["whois-info"]["value"] == "x"
    p = ents["n1"]  # no Person definition in archive -> first property is the value
    assert (p["type"], p["value"], "position" in p) == ("Person", "Ann Lee", False)
    assert p["properties"]["person.lastname"]["isReadOnly"] is True
    h = ents["n2"]
    assert (h["type"], h["value"], h["properties"]["maltego.type"]["value"]) == ("Phrase", "abc123", "acme.Hash")
    s = ents["n3"]  # custom type resolved through BaseEntities, original type kept
    assert (s["type"], s["value"], s["properties"]["maltego.type"]["value"]) == ("Domain", "srv.paterva.com", "acme.Server")
    assert ents["n5"]["position"] == {"x": 7.0, "y": 8.0} and ents["n5"]["type"] == "IPAddress"
    links = {(l["sourceId"], l["targetId"]): l for l in r["links"]}
    assert links.keys() == {("n0", "n1"), ("n0", "n5"), ("n0", "n2")}, links
    assert links["n0", "n1"]["label"] == "Registrant" and links["n0", "n5"]["label"] == "To IP Address"
    assert all(l["direction"] == "source-to-target" for l in r["links"])
    assert parse_mtgx(data, graph=1)["entities"][0]["value"] == "second graph"  # Graph2 sorts before Graph10
    try:
        parse_mtgx(data, graph=2)
        assert False, "Graph10 is broken XML"
    except ValueError:
        pass


def test_our_graphml_roundtrip():
    g = {"entities": [
        {"id": "e1", "type": "Domain", "value": "a.com", "label": "Main", "metadata": {"notes": "n"},
         "properties": {"k": {"name": "k", "value": "v", "displayName": "K", "isReadOnly": False}}},
        {"id": "e2", "type": "IPAddress", "value": "1.1.1.1", "label": None, "properties": {}, "metadata": {"notes": None}}],
        "links": [{"id": "l1", "sourceId": "e1", "targetId": "e2", "label": "resolves", "direction": "bidirectional"}]}
    os.environ.setdefault("OSINT_DB", os.path.join(tempfile.mkdtemp(), "t.db"))
    try:
        import app
    except Exception as ex:  # fastapi missing or app.py mid-edit
        print(f"skip graphml round trip: cannot import app ({ex!r})")
        return
    r = parse_mtgx(app.graphml(g).encode())
    want = [{k: e[k] for k in ("id", "type", "value", "label", "properties", "metadata")} for e in g["entities"]]
    assert r["entities"] == want, r["entities"]
    assert r["links"] == [{k: v for k, v in g["links"][0].items() if k != "id"}]
    for e in r["entities"]:  # accepted by /api/import's models
        app.NewEntity(type=e["type"], value=e["value"], properties=e["properties"], label=e["label"])
    mt = parse_mtz((HERE / "fixtures" / "trx-local.mtz").read_bytes())
    for t in mt["transforms"]:
        app.TransformCfg(**(t | {"workingDir": None}))


def test_mtgl_rejected():
    fake = zipped({"Graphs/Graph1/DataEntities/_y.cfs": b"\0", "Graphs/Graph1.properties": "x=1"})
    real = MALTEGO / "maltego-ui" / "modules" / "com-paterva-maltego-mtgx.jar"
    samples = [fake] + ([jar_files(real, ("example.mtgl",))["com/paterva/maltego/mtgx/example.mtgl"]]
                        if real.exists() else [])
    for data in samples:
        try:
            parse_mtgx(data)
            assert False
        except ValueError as ex:
            assert "mtgl" in str(ex) and "GraphML" in str(ex)
    try:
        parse_mtgx(b"not xml")
        assert False
    except ValueError:
        pass


def test_trx_mtz():
    r = parse_mtz((HERE / "fixtures" / "trx-local.mtz").read_bytes())  # genuine maltego-trx 1.7.0 write_local_mtz
    dns, greet = r["transforms"]
    assert dns == {"kind": "local", "name": "DNS to IP", "inputType": "Domain", "description": "Resolve DNS name to IP.",
                   "command": "python", "args": ["project.py", "local", "dnstoip"], "workingDir": r"C:\work\trx",
                   "settings": [], "linkLabel": None, "timeout": 60}, dns
    assert greet["inputType"] == "Person" and greet["args"][-1] == "greetperson"
    assert r["skipped"] == ["Hash Lookup: input type maltego.Hash has no equivalent here"]


def test_remote_and_quoting():
    t = ('<MaltegoTransform name="{n}" displayName="{n}"><TransformAdapter>com.paterva.maltego.transform.protocol.'
         'v2api.RemoteTransformAdapterV2</TransformAdapter><Properties><Fields><Property name="api.key" type="string"/>'
         '</Fields></Properties><InputConstraints><Entity type="maltego.EmailAddress"/></InputConstraints></MaltegoTransform>')
    local = ('<MaltegoTransform name="q"><TransformAdapter>LocalTransformAdapterV2</TransformAdapter>'
             '<InputConstraints><Entity type="maltego.Phrase"/></InputConstraints></MaltegoTransform>')
    qs = ('<TransformSettings><Properties><Property name="transform.local.command">C:\\Py\\python.exe</Property>'
          '<Property name="transform.local.parameters">"C:\\my dir\\p.py" local q</Property></Properties></TransformSettings>')
    data = zipped({"TransformRepositories/R/email-lookup.transform": t.format(n="email-lookup"),
                   "TransformRepositories/R/acme.Lookup.transform": t.format(n="acme.Lookup"),
                   "TransformRepositories/L/q.transform": local, "TransformRepositories/L/q.transformsettings": qs,
                   "Servers/trx.tas": '<MaltegoServer name="trx" url="https://trx.example.com:8443/"><Transforms>'
                                      '<Transform name="email-lookup"/></Transforms></MaltegoServer>',
                   "Servers/tds.tas": '<MaltegoServer name="tds" url="https://tds.example.com/TDS/stubs"><Transforms>'
                                      '<Transform name="acme.Lookup"/></Transforms></MaltegoServer>'})
    r = parse_mtz(data)
    by = {t["name"]: t for t in r["transforms"]}
    assert by["q"]["args"] == ["C:\\my dir\\p.py", "local", "q"] and by["q"]["command"] == "C:\\Py\\python.exe"
    rem = by["email-lookup"]
    assert (rem["kind"], rem["url"], rem["settings"], rem["inputType"]) == (
        "remote", "https://trx.example.com:8443/run/email-lookup/", ["api.key"], "EmailAddress")
    assert "inferred" in rem["description"]
    assert len(r["skipped"]) == 1 and r["skipped"][0].startswith("acme.Lookup: remote TDS transform"), r["skipped"]


def test_real_maltego_resources():
    auto = MALTEGO / "maltego-ui" / "modules" / "com-paterva-maltego-automation.jar"
    common = MALTEGO / "maltego-core-platform" / "modules" / "com-paterva-maltego-entities-common.jar"
    if not (auto.exists() and common.exists()):
        print("skip real Maltego resources: install not found")
        return
    files = jar_files(auto, (".transform", ".transformsettings", ".entity")) | jar_files(common, (".entity",))
    with zipfile.ZipFile(io.BytesIO(zipped(files))) as z:
        defs = _entity_defs(z)
    assert len(defs) >= 107 and defs["maltego.Person"]["value"] == "person.fullname"
    assert _our_type("maltego.Person", defs) == "Person" and _our_type("maltego.DesktopComputer", defs) is None
    r = parse_mtz(zipped(files))
    assert r["transforms"] == [] and len(r["skipped"]) == 6, r  # Java/test adapters: nothing runnable here
    assert any("JavaTransformAdapter" in s for s in r["skipped"]), r["skipped"]
    assert r["entityTypes"]["maltego.Person"] == "Person"
    # a .mtgx using the real entity definitions bundled in Maltego's own example graph
    ex = jar_files(MALTEGO / "maltego-ui" / "modules" / "com-paterva-maltego-mtgx.jar", (".mtgl",))
    with zipfile.ZipFile(io.BytesIO(ex["com/paterva/maltego/mtgx/example.mtgl"])) as z:
        ents = {n: z.read(n) for n in z.namelist() if n.endswith(".entity")}
    body = node("a", "maltego.Location", [prop("country", "ZA"), prop("location.name", "Pretoria, ZA")])
    e = parse_mtgx(zipped(ents | {"Graphs/Graph1.graphml": graphml(body)}))["entities"][0]
    assert (e["type"], e["value"]) == ("Location", "Pretoria, ZA"), e


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")

"""SQLite store: graphs (cases), entities + links adjacency list, FTS5, undo journal, evidence, monitors, settings."""
import hashlib, json, sqlite3, threading, time, uuid, zlib
from contextlib import contextmanager

import secretstore

SCHEMA = """
pragma foreign_keys = on;
create table if not exists graphs (id text primary key, name text not null, created_at integer not null,
  notes text);
create table if not exists entities (
  id text primary key, graph_id text not null references graphs(id) on delete cascade,
  type text not null, value text not null, label text, icon text,
  properties text not null default '{}', created_at integer not null, discovered_by text, notes text,
  x real, y real, unique (graph_id, type, value));
create table if not exists links (
  id text primary key, graph_id text not null references graphs(id) on delete cascade,
  source_id text not null references entities(id) on delete cascade,
  target_id text not null references entities(id) on delete cascade,
  label text not null default '', direction text not null default 'source-to-target', weight real,
  transform text, provider text, classification text, evidence_id text, created_at integer,
  unique (source_id, target_id, label));
create index if not exists links_target on links(target_id);
create index if not exists links_graph on links(graph_id);
create virtual table if not exists entities_fts using fts5(
  value, label, notes, properties, content='entities', content_rowid='rowid');
create trigger if not exists ent_ai after insert on entities begin
  insert into entities_fts(rowid, value, label, notes, properties)
  values (new.rowid, new.value, new.label, new.notes, new.properties); end;
create trigger if not exists ent_ad after delete on entities begin
  insert into entities_fts(entities_fts, rowid, value, label, notes, properties)
  values ('delete', old.rowid, old.value, old.label, old.notes, old.properties); end;
create trigger if not exists ent_au after update of value, label, notes, properties on entities begin
  insert into entities_fts(entities_fts, rowid, value, label, notes, properties)
  values ('delete', old.rowid, old.value, old.label, old.notes, old.properties);
  insert into entities_fts(rowid, value, label, notes, properties)
  values (new.rowid, new.value, new.label, new.notes, new.properties); end;
create table if not exists journal (seq integer primary key autoincrement, graph_id text not null,
  batch integer not null, op text not null, tbl text not null, row text not null, undone integer not null default 0);
create index if not exists journal_graph on journal(graph_id, batch);
create table if not exists evidence (id text primary key, graph_id text not null references graphs(id) on delete cascade,
  transform text, url text, fetched_at integer not null, status integer, sha256 text not null, size integer not null,
  body blob);
create table if not exists entity_evidence (entity_id text not null references entities(id) on delete cascade,
  evidence_id text not null references evidence(id) on delete cascade, primary key (entity_id, evidence_id));
create table if not exists monitors (id text primary key, graph_id text not null references graphs(id) on delete cascade,
  machine_id text not null, entity_ids text not null, interval_min integer not null, enabled integer not null default 1,
  last_run integer, next_run integer not null);
create table if not exists alerts (id text primary key, graph_id text not null references graphs(id) on delete cascade,
  monitor_id text, created_at integer not null, text text not null, entity_ids text not null, seen integer not null default 0);
create table if not exists images (id text primary key, graph_id text not null references graphs(id) on delete cascade,
  name text not null, media_type text not null, width integer, height integer, size integer not null,
  created_at integer not null, data blob not null);
create table if not exists transform_configs (id text primary key, config text not null);
create table if not exists settings (name text primary key, value text not null, secret integer not null);
"""
MAX_IMAGE_BYTES = 30_000_000
MAX_EVIDENCE_BODY = 5_000_000
JOURNAL_KEEP = 300  # undo depth per graph


class Conflict(Exception):
    pass


def now_ms():
    return int(time.time() * 1000)


def entity_row(r):
    return {"id": r["id"], "type": r["type"], "value": r["value"], "label": r["label"], "icon": r["icon"],
            "properties": json.loads(r["properties"]),
            "metadata": {"createdAt": r["created_at"], "discoveredByTransform": r["discovered_by"],
                         "notes": r["notes"]},
            "position": {"x": r["x"], "y": r["y"]} if r["x"] is not None else None}


import re as _re
_SECRET_QS = _re.compile(r"(?i)([?&](?:[^=&]*(?:token|apikey|api_key|key|secret|password|sid|auth|access_token)[^=&]*)=)[^&#]*")


def _redact_url(url):
    """Mask credential-looking query values so a key passed in a URL never lands in the evidence trail."""
    if not url or "?" not in url:
        return url
    return _SECRET_QS.sub(r"\1REDACTED", url)


def link_row(r):
    k = r.keys()  # provenance columns may be absent on rows from a mid-migration read
    return {"id": r["id"], "sourceId": r["source_id"], "targetId": r["target_id"], "label": r["label"],
            "direction": r["direction"], "weight": r["weight"],
            "transform": r["transform"] if "transform" in k else None,
            "provider": r["provider"] if "provider" in k else None,
            "classification": r["classification"] if "classification" in k else None,
            "evidenceId": r["evidence_id"] if "evidence_id" in k else None,
            "createdAt": r["created_at"] if "created_at" in k else None}


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._migrate_legacy()  # upgrade a pre-multigraph DB before applying the current schema
        self.db.executescript(SCHEMA)
        # Add link provenance columns to DBs created before the evidence-model change.
        self._ensure_cols("links", {"transform": "text", "provider": "text", "classification": "text",
                                    "evidence_id": "text", "created_at": "integer"})
        self.lock = threading.RLock()  # ponytail: one writer lock, fine for a single-analyst workspace
        self.depth = 0
        self.batch = None  # (graph_id, batch no) of the outermost journaled transaction

    def _cols(self, table):
        return [r[1] for r in self.db.execute(f"pragma table_info({table})").fetchall()]

    def _ensure_cols(self, table, coldefs):
        """Add any missing columns (sqlite ALTER TABLE ADD COLUMN is cheap and non-destructive)."""
        have = set(self._cols(table))
        for name, decl in coldefs.items():
            if name not in have:
                self.db.execute(f"alter table {table} add column {name} {decl}")

    def _migrate_legacy(self):
        """Old DBs (before cases) had entities/links with no graph_id and no `graphs` table.
        Move their rows into a default graph instead of crashing on the new indexes/triggers."""
        tables = {r[0] for r in self.db.execute("select name from sqlite_master where type='table'")}
        if "entities" not in tables or ("graphs" in tables and "graph_id" in self._cols("entities")):
            return  # fresh DB, or already current
        ent_cols = [c for c in self._cols("entities") if c != "graph_id"]
        link_cols = [c for c in self._cols("links")] if "links" in tables else []
        with self.db:
            # drop old FTS + triggers (they bind to the old entities table) and move the data aside
            for t in ("ent_ai", "ent_ad", "ent_au"):
                self.db.execute(f"drop trigger if exists {t}")
            self.db.execute("drop table if exists entities_fts")
            self.db.execute("alter table entities rename to _old_entities")
            if link_cols:
                self.db.execute("alter table links rename to _old_links")
            self.db.executescript(SCHEMA)
            gid = uuid.uuid4().hex
            self.db.execute("insert into graphs values (?,?,?,null)", (gid, "Investigation 1", now_ms()))
            keep = [c for c in ent_cols if c in self._cols("entities")]
            self.db.execute(f"insert into entities (graph_id, {', '.join(keep)}) "
                            f"select ?, {', '.join(keep)} from _old_entities", (gid,))
            self.db.execute("drop table _old_entities")
            if link_cols:
                lkeep = [c for c in link_cols if c in self._cols("links")]
                self.db.execute(f"insert into links (graph_id, {', '.join(lkeep)}) "
                                f"select ?, {', '.join(lkeep)} from _old_links", (gid,))
                self.db.execute("drop table _old_links")

    @contextmanager
    def tx(self, graph_id=None):
        """Locked transaction; nested tx() joins the outer one. With graph_id, its changes form one undo step."""
        with self.lock:
            self.depth += 1
            if self.depth == 1 and graph_id:
                n = self.db.execute("select coalesce(max(batch), 0) + 1 from journal where graph_id = ?",
                                    (graph_id,)).fetchone()[0]
                self.batch = (graph_id, n)
            try:
                yield
                if self.depth == 1:
                    if self.batch:
                        self._trim_journal(self.batch[0])
                    self.db.commit()
            except BaseException:
                if self.depth == 1:
                    self.db.rollback()
                raise
            finally:
                self.depth -= 1
                if self.depth == 0:
                    self.batch = None

    def q(self, sql, *args):
        with self.tx():
            return self.db.execute(sql, args).fetchall()

    # ---- journal (undo/redo) ----
    def _log(self, op, tbl, row):
        if self.batch:
            g, n = self.batch
            if op != "noop":
                self.db.execute("delete from journal where graph_id = ? and undone = 1", (g,))  # new edit kills redo
            self.db.execute("insert into journal (graph_id, batch, op, tbl, row) values (?,?,?,?,?)",
                            (g, n, op, tbl, json.dumps(row)))

    def _trim_journal(self, g):
        self.db.execute("delete from journal where graph_id = ? and batch <= "
                        "(select max(batch) from journal where graph_id = ?) - ?", (g, g, JOURNAL_KEEP))

    def _raw(self, tbl, rid):
        r = self.db.execute(f"select * from {tbl} where id = ?", (rid,)).fetchone()
        return dict(r) if r else None

    def _insert(self, tbl, row):
        cols = ", ".join(row)
        self.db.execute(f"insert or replace into {tbl} ({cols}) values ({', '.join('?' * len(row))})",
                        tuple(row.values()))

    def _apply(self, op, tbl, row, forward):
        if op == "ins":
            self._insert(tbl, row) if forward else self.db.execute(f"delete from {tbl} where id = ?", (row["id"],))
        elif op == "del":
            self.db.execute(f"delete from {tbl} where id = ?", (row["id"],)) if forward else self._insert(tbl, row)
        elif op == "upd":
            self._insert(tbl, row["new"] if forward else row["old"])

    def undo(self, graph_id, redo=False):
        """Undo the last step (or redo the last undone one). Returns False when there is nothing to do."""
        with self.tx():
            # undo the most-recent applied batch; redo the oldest undone one (undone batches form a suffix)
            pick = ("select min(batch) from journal where graph_id = ? and undone = 1" if redo else
                    "select max(batch) from journal where graph_id = ? and undone = 0")
            n = self.db.execute(pick, (graph_id,)).fetchone()[0]
            if n is None:
                return False
            rows = self.db.execute("select * from journal where graph_id = ? and batch = ? order by seq "
                                   + ("asc" if redo else "desc"), (graph_id, n)).fetchall()
            for r in rows:
                self._apply(r["op"], r["tbl"], json.loads(r["row"]), forward=redo)
            self.db.execute("update journal set undone = ? where graph_id = ? and batch = ?",
                            (0 if redo else 1, graph_id, n))
            return True

    def history(self, graph_id):
        r = self.db.execute("select sum(undone = 0) u, sum(undone = 1) r from (select batch, max(undone) undone "
                            "from journal where graph_id = ? group by batch)", (graph_id,)).fetchone()
        return {"canUndo": bool(r["u"]), "canRedo": bool(r["r"])}

    # ---- graphs ----
    def graphs(self):
        return [dict(r) | {"entities": r["n"]} for r in self.q(
            "select g.*, (select count(*) from entities e where e.graph_id = g.id) n from graphs g order by created_at")]

    def create_graph(self, name):
        gid = uuid.uuid4().hex
        self.q("insert into graphs values (?,?,?,null)", gid, name, now_ms())
        return gid

    def rename_graph(self, gid, name):
        self.q("update graphs set name = ? where id = ?", name, gid)

    def delete_graph(self, gid):
        self.q("delete from journal where graph_id = ?", gid)
        self.q("delete from graphs where id = ?", gid)

    def graph_exists(self, gid):
        return bool(self.q("select 1 from graphs where id = ?", gid))

    def graph(self, gid):
        return {"entities": [entity_row(r) for r in self.q("select * from entities where graph_id = ?", gid)],
                "links": [link_row(r) for r in self.q("select * from links where graph_id = ?", gid)]}

    # ---- entities & links ----
    def get(self, eid):
        rows = self.q("select * from entities where id = ?", eid)
        return entity_row(rows[0]) if rows else None

    def upsert_entity(self, gid, type, value, properties=None, label=None, icon=None, notes=None,
                      discovered_by=None, position=None):
        """Maltego-style merge: same (type, value) in a graph is one entity; new properties merge in.
        Returns (entity, created)."""
        with self.tx(gid):
            row = self.db.execute("select * from entities where graph_id = ? and type = ? and value = ?",
                                  (gid, type, value)).fetchone()
            if row:
                old = dict(row)
                props = json.loads(row["properties"]) | (properties or {})
                new = old | {"properties": json.dumps(props), "icon": old["icon"] or icon,
                             "notes": old["notes"] or notes}
                if new != old:
                    self._insert("entities", new)
                    self._log("upd", "entities", {"old": old, "new": new})
                eid, created = row["id"], False
            else:
                pos = position or {}
                new = {"id": uuid.uuid4().hex, "graph_id": gid, "type": type, "value": value, "label": label,
                       "icon": icon, "properties": json.dumps(properties or {}), "created_at": now_ms(),
                       "discovered_by": discovered_by, "notes": notes, "x": pos.get("x"), "y": pos.get("y")}
                self._insert("entities", new)
                self._log("ins", "entities", new)
                eid, created = new["id"], True
            return entity_row(self.db.execute("select * from entities where id = ?", (eid,)).fetchone()), created

    def update_entity(self, eid, patch):
        old = self._raw("entities", eid)
        new = dict(old)
        for k in ("value", "label", "icon", "notes"):
            if k in patch:
                new[k] = patch[k]
        if "properties" in patch:
            new["properties"] = json.dumps(patch["properties"])
        if new != old:
            try:
                with self.tx(old["graph_id"]):
                    sets = ", ".join(f"{k} = ?" for k in new if k != "id")
                    self.db.execute(f"update entities set {sets} where id = ?",
                                    (*[v for k, v in new.items() if k != "id"], eid))
                    self._log("upd", "entities", {"old": old, "new": new})
            except sqlite3.IntegrityError:
                raise Conflict("an entity with that type and value already exists")
        return self.get(eid)

    def set_positions(self, positions):  # layout moves are not undo steps
        with self.tx():
            self.db.executemany("update entities set x = ?, y = ? where id = ?",
                                [(p["x"], p["y"], eid) for eid, p in positions.items()])

    def delete_entities(self, gid, ids):
        with self.tx(gid):
            for eid in ids:
                for l in self.db.execute("select * from links where source_id = ? or target_id = ?", (eid, eid)):
                    self._log("del", "links", dict(l))
                    self.db.execute("delete from links where id = ?", (l["id"],))
                row = self._raw("entities", eid)
                if row and row["graph_id"] == gid:
                    # evidence attachments cascade away and are not restored by undo
                    self._log("del", "entities", row)
                    self.db.execute("delete from entities where id = ?", (eid,))

    def upsert_link(self, gid, source_id, target_id, label="", direction="source-to-target", weight=None,
                    transform=None, provider=None, classification=None, evidence_id=None, created_at=None):
        with self.tx(gid):
            r = self.db.execute("select * from links where source_id = ? and target_id = ? and label = ?",
                                (source_id, target_id, label or "")).fetchone()
            if not r:
                # ponytail: one row per (source,target,label) keeps the FIRST assertion's provenance. Recording
                # multiple independent sources / disagreements for the same edge is a follow-up (link_evidence join).
                new = {"id": uuid.uuid4().hex, "graph_id": gid, "source_id": source_id, "target_id": target_id,
                       "label": label or "", "direction": direction, "weight": weight, "transform": transform,
                       "provider": provider, "classification": classification, "evidence_id": evidence_id,
                       "created_at": created_at}
                self._insert("links", new)
                self._log("ins", "links", new)
                r = new
            return link_row(r)

    def delete_link(self, lid):
        row = self._raw("links", lid)
        if row:
            with self.tx(row["graph_id"]):
                self._log("del", "links", row)
                self.db.execute("delete from links where id = ?", (lid,))

    def search(self, gid, text, limit=500):
        # quote each term so user input can't inject FTS5 query syntax
        terms = " ".join('"' + t.replace('"', '""') + '"*' for t in text.split())
        if not terms:
            return []
        return [r["id"] for r in self.q("select e.id from entities_fts f join entities e on e.rowid = f.rowid "
                                        "where entities_fts match ? and e.graph_id = ? limit ?", terms, gid, limit)]

    def clear(self, gid):
        self.delete_entities(gid, [r["id"] for r in self.q("select id from entities where graph_id = ?", gid)])

    # ---- evidence ----
    def add_evidence(self, gid, transform, rec):
        """rec: {url, status, body(bytes), fetched_at}. Deduped per graph by content hash + url."""
        body = rec["body"] or b""
        sha = hashlib.sha256(body).hexdigest()
        url = _redact_url(rec["url"])  # keep API keys out of the stored evidence trail
        with self.tx():
            r = self.db.execute("select id from evidence where graph_id = ? and sha256 = ? and url = ?",
                                (gid, sha, url)).fetchone()
            if r:
                return r["id"]
            eid = uuid.uuid4().hex
            stored = zlib.compress(body[:MAX_EVIDENCE_BODY])
            self.db.execute("insert into evidence values (?,?,?,?,?,?,?,?,?)",
                            (eid, gid, transform, url, rec["fetched_at"], rec.get("status"), sha,
                             len(body), stored))
            return eid

    def attach_evidence(self, entity_id, evidence_ids):
        with self.tx():
            self.db.executemany("insert or ignore into entity_evidence values (?, ?)",
                                [(entity_id, e) for e in evidence_ids])

    def evidence_for(self, entity_id):
        return [dict(r) for r in self.q(
            "select v.id, v.transform, v.url, v.fetched_at fetchedAt, v.status, v.sha256, v.size from evidence v "
            "join entity_evidence ee on ee.evidence_id = v.id where ee.entity_id = ? order by v.fetched_at",
            entity_id)]

    def evidence_index(self, gid):
        """{entity_id: [evidence meta]} for a whole graph (reports)."""
        out = {}
        for r in self.q("select ee.entity_id, v.id, v.transform, v.url, v.fetched_at fetchedAt, v.status, v.sha256, "
                        "v.size from evidence v join entity_evidence ee on ee.evidence_id = v.id "
                        "where v.graph_id = ?", gid):
            d = dict(r)
            out.setdefault(d.pop("entity_id"), []).append(d)
        return out

    def evidence_body(self, evid):
        r = self.q("select body, url from evidence where id = ?", evid)
        return (zlib.decompress(r[0]["body"]), r[0]["url"]) if r else (None, None)

    # ---- monitors & alerts ----
    def monitors(self, gid=None):
        sql, args = ("select * from monitors where graph_id = ?", (gid,)) if gid else ("select * from monitors", ())
        return [dict(r) | {"entity_ids": json.loads(r["entity_ids"])} for r in self.q(sql, *args)]

    def add_monitor(self, gid, machine_id, entity_ids, interval_min):
        mid = uuid.uuid4().hex
        self.q("insert into monitors values (?,?,?,?,?,1,null,?)", mid, gid, machine_id, json.dumps(entity_ids),
               interval_min, now_ms())
        return mid

    def update_monitor(self, mid, **fields):
        for k, v in fields.items():
            self.q(f"update monitors set {k} = ? where id = ?", v, mid)

    def delete_monitor(self, mid):
        self.q("delete from monitors where id = ?", mid)

    def add_alert(self, gid, monitor_id, text, entity_ids):
        aid = uuid.uuid4().hex
        self.q("insert into alerts values (?,?,?,?,?,?,0)", aid, gid, monitor_id, now_ms(), text,
               json.dumps(entity_ids))
        return {"id": aid, "graph_id": gid, "monitor_id": monitor_id, "created_at": now_ms(), "text": text,
                "entity_ids": entity_ids, "seen": 0}

    def alerts(self, gid):
        return [dict(r) | {"entity_ids": json.loads(r["entity_ids"])}
                for r in self.q("select * from alerts where graph_id = ? order by created_at desc limit 200", gid)]

    def mark_alerts_seen(self, gid):
        self.q("update alerts set seen = 1 where graph_id = ?", gid)

    # ---- images (forensic light table) ----
    def add_image(self, gid, name, media_type, data, width=None, height=None):
        iid = uuid.uuid4().hex
        self.q("insert into images values (?,?,?,?,?,?,?,?,?)",
               iid, gid, name, media_type, width, height, len(data), now_ms(), data)
        return iid

    def image(self, iid):
        r = self.q("select * from images where id = ?", iid)
        return dict(r[0]) if r else None

    # ---- transform configs & settings ----
    def configs(self):
        return [json.loads(r["config"]) for r in self.q("select config from transform_configs")]

    def save_config(self, cfg):
        self.q("insert or replace into transform_configs values (?, ?)", cfg["id"], json.dumps(cfg))

    def delete_config(self, cid):
        self.q("delete from transform_configs where id = ?", cid)

    def settings(self):  # secrets unsealed here, at the one point transforms/AI read them
        return {r["name"]: (secretstore.unseal(r["value"]) if r["secret"] else r["value"])
                for r in self.q("select * from settings")}

    def settings_public(self):  # secrets never leave the server (value masked to None)
        return [{"name": r["name"], "secret": bool(r["secret"]), "value": None if r["secret"] else r["value"]}
                for r in self.q("select * from settings order by name")]

    def set_setting(self, name, value, secret):
        stored = secretstore.seal(value) if secret else value  # at-rest protection for API keys/tokens
        self.q("insert or replace into settings values (?, ?, ?)", name, stored, int(secret))

    def delete_setting(self, name):
        self.q("delete from settings where name = ?", name)

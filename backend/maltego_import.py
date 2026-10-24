"""Import Maltego files: .mtgx graphs (plus our own GraphML export) and .mtz configuration archives.

Verified against real files: .entity/.transform/.transformsettings/.tas from Maltego 4.13 jars, maltego-trx 1.7.0
write_local_mtz output, real .mtgl archives (Lucene) and Maltego's empty .mtgx template (Graphs/Graph1.graphml).
Inferred from public docs only: MaltegoEntity/MaltegoLink node/edge encoding and position data inside .mtgx graphml.
"""
import io
import json
import re
import shlex
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import urlsplit

from maltego_xml import to_our_type

MAX_UNZIPPED = 512 << 20
LINK_LABELS = ("maltego.link.manual.type", "maltego.link.label", "label",
               "maltego.link.transform.display-name", "maltego.link.transform.name")


def _ln(el):
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def _all(el, name):
    return [c for c in el.iter() if _ln(c) == name] if el is not None else []


def _find(el, name):
    return next(iter(_all(el, name)), None)


def _text(el):
    return (el.text or "").strip() if el is not None else ""


MAX_ZIP_ENTRIES = 10_000


def _xml(b):
    # expat resolves no external entities; also reject a DOCTYPE outright so an internal-entity
    # expansion bomb ("billion laughs") in an untrusted import can't blow up memory while parsing.
    if b"<!DOCTYPE" in b:
        raise ValueError("DOCTYPE/DTD not allowed in imported XML")
    try:
        return ET.fromstring(b)
    except ET.ParseError:
        return None


def _zip(data):
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return None
    z = zipfile.ZipFile(io.BytesIO(data))
    infos = z.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ValueError("archive has too many entries")
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise ValueError("archive too large")
    return z


def _entity_defs(z):
    """{maltego type id: {displayName, value (main property name), bases}} from Entities/*.entity."""
    defs = {}
    for n in z.namelist():
        r = _xml(z.read(n)) if n.endswith(".entity") else None
        if r is not None and r.get("id"):
            p = _find(r, "Properties")
            defs[r.get("id")] = {"displayName": r.get("displayName") or r.get("id"),
                                 "value": p.get("value") if p is not None else None,
                                 "bases": [_text(b) for b in _all(r, "BaseEntity") if _text(b)]}
    return defs


def _resolve(mtype, defs, get):
    """First non-empty get(type) walking the BaseEntities inheritance chain breadth-first."""
    seen, todo = set(), [mtype]
    while todo:
        t = todo.pop(0)
        if t in seen:
            continue
        seen.add(t)
        if v := get(t):
            return v
        todo += defs.get(t, {}).get("bases", [])
    return None


def _our_type(mtype, defs):
    return _resolve(mtype, defs, to_our_type)


def _pval(p):
    v = _find(p, "Value")
    return (v.text if v is not None else p.text) or ""


def _position(node):
    for e in node.iter():
        try:
            if e.get("x") is not None and e.get("y") is not None:
                return {"x": float(e.get("x")), "y": float(e.get("y"))}
        except ValueError:
            pass
    return None


def _maltego_entity(nid, me, node, defs):
    mtype = me.get("type") or "maltego.Phrase"
    props, notes = {}, _text(_find(me, "Notes")) or None
    for p in _all(me, "Property"):
        name = p.get("name")
        if name == "notes#":
            notes = _pval(p) or notes
        elif name:
            props[name] = {"name": name, "value": _pval(p), "displayName": p.get("displayName") or name}
            if p.get("readonly") == "true":
                props[name]["isReadOnly"] = True
    key = _resolve(mtype, defs, lambda t: defs.get(t, {}).get("value"))
    key = key if key in props else next(iter(props), None)
    value = props.pop(key)["value"].strip() if key else ""
    if not value:
        return None
    if not to_our_type(mtype):
        props["maltego.type"] = {"name": "maltego.type", "value": mtype, "displayName": "Maltego Type",
                                 "isReadOnly": True}
    e = {"id": nid, "type": _our_type(mtype, defs) or "Phrase", "value": value, "label": None,
         "properties": props, "metadata": {"notes": notes}}
    if pos := _position(node):
        e["position"] = pos
    return e


def _graphml(root, defs):
    g = _find(root, "graph")
    if g is None:
        raise ValueError("no <graph> in GraphML")
    ents = []
    for node in (c for c in g if _ln(c) == "node"):
        me, d = _find(node, "MaltegoEntity"), {x.get("key"): x.text or "" for x in node if _ln(x) == "data"}
        if me is not None:
            e = _maltego_entity(node.get("id"), me, node, defs)
        elif d.get("n_type") and d.get("n_value"):  # our own export (app.graphml)
            try:
                props = json.loads(d.get("n_properties") or "{}")
            except ValueError:
                props = {}
            e = {"id": node.get("id"), "type": d["n_type"], "value": d["n_value"], "label": d.get("n_label") or None,
                 "properties": props, "metadata": {"notes": d.get("n_notes") or None}}
        else:
            e = None
        if e and e["id"]:
            ents.append(e)
    ids, links = {e["id"] for e in ents}, []
    for ed in (c for c in g if _ln(c) == "edge"):
        s, t = ed.get("source"), ed.get("target")
        if s not in ids or t not in ids:
            continue
        ml, rev = _find(ed, "MaltegoLink"), False
        if ml is not None:
            lp = {p.get("name"): _pval(p).strip() for p in _all(ml, "Property")}
            label = next((lp[k] for k in LINK_LABELS if lp.get(k)), "")
            rev = lp.get("maltego.link.is_reversed") == "true" or lp.get("maltego.link.direction") == "output-to-input"
            direction = "bidirectional" if lp.get("maltego.link.direction") == "bidirectional" else "source-to-target"
        else:
            d = {x.get("key"): x.text or "" for x in ed if _ln(x) == "data"}
            label = d.get("e_label", "")
            direction = d.get("e_direction") if d.get("e_direction") == "bidirectional" else "source-to-target"
        links.append({"sourceId": t if rev else s, "targetId": s if rev else t, "label": label, "direction": direction})
    return {"entities": ents, "links": links}


def parse_mtgx(data: bytes, graph: int = 0) -> dict:
    """.mtgx (zip of Graphs/GraphN.graphml) or a bare .graphml -> /api/import payload."""
    z = _zip(data)
    if z is None:
        root = _xml(data)
        if root is None:
            raise ValueError("not a .mtgx archive or GraphML file")
        return _graphml(root, {})
    names = z.namelist()
    graphs = sorted((n for n in names if n.lower().endswith(".graphml")),
                    key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)])
    if not graphs:
        if any("/DataEntities/" in n or n.endswith(".cfs") for n in names):
            raise ValueError("Maltego .mtgl (Lucene) graphs are not supported; in Maltego use "
                             "File → Export → Export Graph… as .mtgx or GraphML, then import that")
        raise ValueError("no Graphs/*.graphml in archive")
    if not 0 <= graph < len(graphs):
        raise ValueError(f"graph index {graph} out of range ({len(graphs)} graphs)")
    root = _xml(z.read(graphs[graph]))
    if root is None:
        raise ValueError(f"{graphs[graph]} is not valid XML")
    return _graphml(root, _entity_defs(z))


def _args(s):
    # ponytail: Windows-friendly split (keeps backslashes, strips quotes); Maltego's exact rules unknown
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] and a[0] in "\"'" else a for a in shlex.split(s, posix=False)]


def _trx_url(server_url, name):
    """Guess a maltego-trx endpoint. Real TDS endpoints are assigned server-side and are not in the .mtz."""
    u = urlsplit(server_url or "")
    if u.scheme not in ("http", "https") or not u.hostname or re.search(r"paterva\.com|maltego\.com", u.hostname) \
            or re.search(r"tds|stub|seed", u.path, re.I) or not re.fullmatch(r"[a-z0-9-]+", name):
        return None
    return f"{server_url.rstrip('/')}/run/{name}/"


def parse_mtz(data: bytes) -> dict:
    """.mtz config archive -> {transforms: [TransformCfg dicts], entityTypes: {id: displayName}, skipped: [reasons]}."""
    z = _zip(data)
    if z is None:
        raise ValueError("not a .mtz (zip) archive")
    names, defs = set(z.namelist()), _entity_defs(z)
    servers = {}
    for n in names:
        r = _xml(z.read(n)) if n.endswith(".tas") else None
        for t in _all(r, "Transform"):
            servers[t.get("name")] = r.get("url") or ""
    out, skipped = [], []
    for n in sorted(x for x in names if x.endswith(".transform")):
        r = _xml(z.read(n))
        if r is None or _ln(r) != "MaltegoTransform":
            skipped.append(f"{n}: not a MaltegoTransform")
            continue
        name = r.get("name") or n.rsplit("/", 1)[-1][:-len(".transform")]
        label = r.get("displayName") or name
        fl = _find(r, "Fields")
        fields = [f for f in (fl if fl is not None else []) if f.get("name")]
        vals = {f.get("name"): _text(_find(f, "DefaultValue")) for f in fields}
        st = _xml(z.read(n + "settings")) if n + "settings" in names else None
        vals |= {p.get("name"): _text(p) for p in _all(st, "Property") if p.get("name")}
        ent = _find(_find(r, "InputConstraints"), "Entity")
        mtype = ent.get("type") if ent is not None else None
        ours = _our_type(mtype, defs) if mtype else None
        adapter = _text(_find(r, "TransformAdapter"))
        if not ours:
            skipped.append(f"{label}: input type {mtype or '(none)'} has no equivalent here")
        elif "Local" in adapter or vals.get("transform.local.command"):
            if not vals.get("transform.local.command"):
                skipped.append(f"{label}: local transform without transform.local.command")
                continue
            out.append({"kind": "local", "name": label, "inputType": ours, "description": r.get("description") or "",
                        "command": vals["transform.local.command"],
                        "args": _args(vals.get("transform.local.parameters") or ""),
                        "workingDir": vals.get("transform.local.working-directory") or None,
                        "settings": [], "linkLabel": None, "timeout": 60})
        elif "Remote" in adapter:
            url = _trx_url(servers.get(name), name)
            if not url:
                skipped.append(f"{label}: remote TDS transform on {servers.get(name) or 'unknown server'}; "
                               "its endpoint is assigned by the TDS and not stored in the .mtz")
                continue
            desc = (r.get("description") or "") + f" [URL inferred from maltego-trx convention: {url}]"
            out.append({"kind": "remote", "name": label, "inputType": ours, "description": desc.strip(), "url": url,
                        "settings": [k for k in vals if not k.startswith(("transform.", "maltego.transform."))],
                        "linkLabel": None, "timeout": 60})
        else:
            skipped.append(f"{label}: unsupported transform adapter {adapter or '(none)'}")
    return {"transforms": out, "entityTypes": {k: v["displayName"] for k, v in defs.items()}, "skipped": skipped}

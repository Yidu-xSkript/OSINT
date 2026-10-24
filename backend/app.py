"""OSINT Graph API.  python app.py [--port 8000] [--data-dir DIR]   ->  http://127.0.0.1:<port>"""
import argparse, json, os, re, sys, threading, time, uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

import ai
import engine
import gev_proxy
import maltego_import
import report
import sightline
import tools
import nmap_scan
from machines import MACHINES
from maltego_xml import TO_MALTEGO
from store import Conflict, Store


def _bundle_base():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))


def ui_dir():
    # bundled by PyInstaller under _MEIPASS/frontend/dist, else the repo's frontend/dist
    return _bundle_base() / "frontend" / "dist"


def gev_dir():
    # bundled God's Eye View static build (served at /gev so no separate GEV server is needed)
    return _bundle_base() / "gev"


store: Store = None  # set in main()
app = FastAPI(title="OSINT Graph")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.include_router(gev_proxy.router)  # /api/adsblol, /api/celestrak, /api/overpass for the bundled globe's live layers

EntityType = Literal[tuple(TO_MALTEGO)]


class Prop(BaseModel):
    name: str
    value: str | int | float | bool
    displayName: str
    isReadOnly: bool = False


class NewEntity(BaseModel):
    type: EntityType
    value: str = Field(min_length=1, max_length=4000)
    properties: dict[str, Prop] = {}
    label: str | None = None
    notes: str | None = None
    position: dict[str, float] | None = None


class EntityPatch(BaseModel):
    value: str | None = Field(None, min_length=1, max_length=4000)
    label: str | None = None
    notes: str | None = None
    icon: str | None = None
    properties: dict[str, Prop] | None = None


class NewLink(BaseModel):
    sourceId: str
    targetId: str
    label: str = ""
    direction: Literal["source-to-target", "bidirectional"] = "source-to-target"
    weight: float | None = None


class Ids(BaseModel):
    ids: list[str]


class RunReq(BaseModel):
    entityIds: list[str]
    limit: int = Field(256, ge=1, le=10_000)


class TransformCfg(BaseModel):
    kind: Literal["local", "remote"]
    name: str = Field(min_length=1, max_length=100)
    inputType: EntityType
    description: str = ""
    linkLabel: str | None = None
    settings: list[str] = []
    timeout: int = Field(60, ge=1, le=600)
    command: str | None = None
    args: list[str] = []
    workingDir: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def check(self):
        if self.kind == "local" and not self.command:
            raise ValueError("local transforms need a command")
        if self.kind == "remote" and not (self.url or "").startswith(("http://", "https://")):
            raise ValueError("remote transforms need an http(s) url")
        if self.workingDir and not Path(self.workingDir).is_dir():
            raise ValueError(f"working directory does not exist: {self.workingDir}")
        return self


class SettingIn(BaseModel):
    value: str
    secret: bool = True


class LatLonH(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    height: float | None = None


class SightlineReq(BaseModel):
    far: LatLonH   # distant landmark (e.g. a spire)
    near: LatLonH  # nearer landmark it lines up behind (e.g. a bridge arch)
    camera: LatLonH  # candidate camera building


class GraphName(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MonitorIn(BaseModel):
    machineId: str
    entityIds: list[str]
    intervalMin: int = Field(60, ge=5, le=100_000)


class MonitorPatch(BaseModel):
    enabled: bool | None = None
    intervalMin: int | None = Field(None, ge=5, le=100_000)


class AIText(BaseModel):
    text: str = Field(max_length=200_000)


def must(x, what="not found"):
    if not x:
        raise HTTPException(404, what)
    return x


def need_graph(gid):
    if not store.graph_exists(gid):
        raise HTTPException(404, "unknown graph")


@app.get("/api/health")
def health():
    return {"ok": True}


# ---- graphs (cases) ----
@app.get("/api/graphs")
def graphs():
    return store.graphs()


@app.post("/api/graphs")
def create_graph(g: GraphName):
    return {"id": store.create_graph(g.name)}


@app.post("/api/graphs/sample")
def sample_graph():
    """A keyless demo case for first-run: a short pivot chain whose links show every evidence class."""
    gid = store.create_graph("Sample investigation")
    now = int(time.time() * 1000)

    def ent(typ, value, x, y, props=None):
        e, _ = store.upsert_entity(gid, typ, value, props or {}, position={"x": x, "y": y})
        return e["id"]

    def coord(v):
        return {"location.coordinates": {"name": "location.coordinates", "value": v, "displayName": "location.coordinates"}}

    with store.tx(gid):
        person = ent("Person", "Jane Doe", -40, 0)
        email = ent("EmailAddress", "jane@acme.example", 220, -140)
        domain = ent("Domain", "acme.example", 480, -140)
        ip = ent("IPAddress", "93.184.216.34", 740, -140)
        site = ent("Website", "www.acme.example", 480, 40)
        loc = ent("Location", "Berlin, DE", 220, 150, coord("52.52,13.405"))
        edges = [  # (src, dst, label, classification, provider)
            (person, email, "Account", "source-asserted", "Hunter"),
            (email, domain, "Email Domain", "derived", None),
            (domain, ip, "Resolves To", "source-asserted", "DNS"),
            (domain, site, "Website", "source-asserted", "DNS"),
            (person, loc, "Based In", "hypothesis", None),
        ]
        for a, b, label, cls, prov in edges:
            store.upsert_link(gid, a, b, label, transform="sample", provider=prov,
                              classification=cls, created_at=now)
    return {"id": gid}


@app.patch("/api/graphs/{gid}")
def rename_graph(gid: str, g: GraphName):
    need_graph(gid)
    store.rename_graph(gid, g.name)
    return {"ok": True}


@app.delete("/api/graphs/{gid}")
def delete_graph(gid: str):
    store.delete_graph(gid)
    return {"ok": True}


@app.get("/api/graphs/{gid}/graph")
def graph(gid: str):
    need_graph(gid)
    return store.graph(gid)


@app.post("/api/graphs/{gid}/clear")
def clear(gid: str):
    need_graph(gid)
    store.clear(gid)
    return {"ok": True}


@app.post("/api/graphs/{gid}/undo")
def undo(gid: str):
    need_graph(gid)
    return {"applied": store.undo(gid), **store.history(gid)}


@app.post("/api/graphs/{gid}/redo")
def redo(gid: str):
    need_graph(gid)
    return {"applied": store.undo(gid, redo=True), **store.history(gid)}


@app.get("/api/graphs/{gid}/history")
def history(gid: str):
    need_graph(gid)
    return store.history(gid)


# ---- entities & links ----
@app.post("/api/graphs/{gid}/entities")
def create_entity(gid: str, e: NewEntity):
    need_graph(gid)
    props = {k: p.model_dump() for k, p in e.properties.items()}
    ent, created = store.upsert_entity(gid, e.type, e.value.strip(), props, e.label, notes=e.notes,
                                       position=e.position)
    return {"entity": ent, "created": created}


@app.patch("/api/entities/{eid}")
def patch_entity(eid: str, patch: EntityPatch):
    must(store.get(eid))
    try:
        return store.update_entity(eid, patch.model_dump(exclude_unset=True))
    except Conflict as c:
        raise HTTPException(409, str(c))


@app.post("/api/graphs/{gid}/entities/delete")
def delete_entities(gid: str, body: Ids):
    need_graph(gid)
    store.delete_entities(gid, body.ids)
    return {"ok": True}


@app.put("/api/positions")
def positions(body: dict[str, dict[str, float]]):
    store.set_positions(body)
    return {"ok": True}


@app.post("/api/graphs/{gid}/links")
def create_link(gid: str, l: NewLink):
    need_graph(gid)
    must(store.get(l.sourceId) and store.get(l.targetId), "unknown entity")
    return store.upsert_link(gid, l.sourceId, l.targetId, l.label, l.direction, l.weight)


@app.delete("/api/links/{lid}")
def delete_link(lid: str):
    store.delete_link(lid)
    return {"ok": True}


@app.get("/api/graphs/{gid}/search")
def search(gid: str, q: str):
    need_graph(gid)
    return store.search(gid, q)


# ---- tools ----
@app.get("/api/tools")
def list_tools():
    return tools.registry(store.settings())


@app.get("/api/scan/profiles")
def scan_profiles():
    return [{"id": k, "label": v["label"], "args": v["args"]} for k, v in nmap_scan.PROFILES.items()]


class ScanReq(BaseModel):
    targets: list[str]
    profile: str
    authorized: bool = False


@app.post("/api/graphs/{gid}/scan")
def scan(gid: str, req: ScanReq):
    """Authorized Nmap scan. Only runs with explicit authorization; discovered IPs never auto-scan."""
    need_graph(gid)
    if not req.authorized:
        raise HTTPException(400, "Authorization required — confirm you are permitted to scan these targets.")
    try:
        hosts, xml, messages = nmap_scan.scan(req.targets, req.profile, store.settings())
    except nmap_scan.ScanError as e:
        raise HTTPException(400, str(e))
    now = int(time.time() * 1000)
    entities, links = {}, []
    with store.tx(gid):
        ev_id = store.add_evidence(gid, f"nmap:{req.profile}", {
            "url": f"nmap:{req.profile}:{','.join(req.targets)}", "status": 200, "body": xml, "fetched_at": now})
        prov = dict(transform=f"nmap:{req.profile}", provider="Nmap", classification="observed",
                    evidence_id=ev_id, created_at=now)

        def node(typ, val, props=None):
            e, _ = store.upsert_entity(gid, typ, val, props or {}, discovered_by="Nmap")
            store.attach_evidence(e["id"], [ev_id])
            entities[e["id"]] = e
            return e

        for h in hosts:
            props = {"nmap.ports": engine._prop("nmap.ports", h["ports_summary"] or "(no open ports)")}
            if h["hostnames"]:
                props["nmap.hostnames"] = engine._prop("nmap.hostnames", ", ".join(h["hostnames"]))
            ip = node("IPAddress", h["ip"], props)
            for hn in h["hostnames"]:
                d = node("Domain", hn)
                links.append(store.upsert_link(gid, ip["id"], d["id"], "Hostname [nmap]", **prov))
            for s in h["services"]:
                if s["url"]:
                    u = node("URL", s["url"], {"service.name": engine._prop("service.name", s["name"] or "")})
                    label = f"{s['port']}/{s['proto']} {s['name'] or ''}".strip() + " [nmap]"
                    links.append(store.upsert_link(gid, ip["id"], u["id"], label, **prov))
    return {"entities": list(entities.values()), "links": links, "messages": [{"entity": "", **m} for m in messages]}


# ---- transforms ----
def _is_credential(name):
    """A setting that gates a transform (an API key/token) vs. plain config (radius, datetime, url)."""
    return name.rsplit(".", 1)[-1] in ("apikey", "key", "token", "sid", "secret", "password")


@app.get("/api/transforms")
def transforms():
    configured = {k for k, v in store.settings().items() if str(v).strip()}
    out = []
    for t in engine.all_transforms(store):
        pub = engine.public(t)
        optional = set(t.get("optionalSettings", []))
        creds = [s for s in t.get("settings", []) if _is_credential(s) and s not in optional]
        pub["credentialSettings"] = creds
        pub["missingSettings"] = [s for s in creds if s not in configured]  # -> "needs setup"
        out.append(pub)
    return out


@app.post("/api/transforms")
def add_transform(cfg: TransformCfg):
    t = {"id": f"{cfg.kind}-{uuid.uuid4().hex[:8]}", **cfg.model_dump()}
    store.save_config(t)
    return t


@app.delete("/api/transforms/{tid}")
def delete_transform(tid: str):
    must(any(c["id"] == tid for c in store.configs()), "only custom transforms can be deleted")
    store.delete_config(tid)
    return {"ok": True}


def _provider(name):
    """The data source behind a transform, from its "To … [Source]" name (e.g. "HIBP", "Nominatim")."""
    m = re.search(r"\[([^\]]+)\]\s*$", name or "")
    return m.group(1) if m else None


def _run_transform(gid, t, entity_ids, limit):
    """Shared by the HTTP endpoint and the monitor scheduler. Returns (entities, links, messages)."""
    inputs = [e for e in map(store.get, entity_ids) if e and e["type"] == t["inputType"]]
    settings = store.settings()

    def one(e):
        try:
            return (e, *engine.run(t, e, settings, limit), None)
        except Exception as ex:
            return e, [], [], [], f"{type(ex).__name__}: {ex}"

    with ThreadPoolExecutor(8) as pool:
        outs = list(pool.map(one, inputs))

    provider = _provider(t["name"])
    classification = t.get("classification", "source-asserted")
    entities, links, messages = {}, [], []
    with store.tx(gid):
        for src, results, msgs, evidence, err in outs:
            ev_ids = [store.add_evidence(gid, t["name"], rec) for rec in evidence]
            if ev_ids:
                store.attach_evidence(src["id"], ev_ids)
            messages += [{"entity": src["value"], **m} for m in msgs]
            if err:
                messages.append({"entity": src["value"], "type": "PartialError", "text": err})
            elif not results:  # a clean run that found nothing is not the same as a failure
                messages.append({"entity": src["value"], "type": "Inform", "text": f"{t['name']}: no results"})
            prov = dict(transform=t["name"], provider=provider, classification=classification,
                        evidence_id=ev_ids[0] if ev_ids else None, created_at=int(time.time() * 1000))
            for r in results:
                ent, _ = store.upsert_entity(gid, r["type"], r["value"], r["properties"], icon=r["icon"],
                                             notes=r["notes"], discovered_by=t["name"])
                if ev_ids:
                    store.attach_evidence(ent["id"], ev_ids)
                if ent["id"] == src["id"]:
                    continue
                a, b = (ent["id"], src["id"]) if r["link"]["reverse"] else (src["id"], ent["id"])
                links.append(store.upsert_link(gid, a, b, r["link"]["label"], **prov))
                entities[ent["id"]] = ent
    return list(entities.values()), links, messages


@app.post("/api/graphs/{gid}/transforms/{tid}/run")
def run_transform(gid: str, tid: str, req: RunReq):
    need_graph(gid)
    t = must(next((t for t in engine.all_transforms(store) if t["id"] == tid), None), "unknown transform")
    entities, links, messages = _run_transform(gid, t, req.entityIds, req.limit)
    return {"entities": entities, "links": links, "messages": messages}


# ---- evidence ----
@app.get("/api/entities/{eid}/evidence")
def entity_evidence(eid: str):
    must(store.get(eid))
    return store.evidence_for(eid)


@app.get("/api/evidence/{evid}")
def evidence_body(evid: str):
    body, url = store.evidence_body(evid)
    if body is None:
        raise HTTPException(404, "no such evidence")
    return Response(body, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="evidence-{evid[:8]}.bin"',
                             "X-Source-URL": url or ""})


# ---- monitors & alerts ----
@app.get("/api/graphs/{gid}/monitors")
def monitors(gid: str):
    need_graph(gid)
    return store.monitors(gid)


@app.post("/api/graphs/{gid}/monitors")
def add_monitor(gid: str, m: MonitorIn):
    need_graph(gid)
    must(m.machineId in MACHINES, "unknown machine")
    return {"id": store.add_monitor(gid, m.machineId, m.entityIds, m.intervalMin)}


@app.patch("/api/monitors/{mid}")
def patch_monitor(mid: str, p: MonitorPatch):
    f = {}
    if p.enabled is not None:
        f["enabled"] = int(p.enabled)
    if p.intervalMin is not None:
        f["interval_min"] = p.intervalMin
    if f:
        store.update_monitor(mid, **f)
    return {"ok": True}


@app.delete("/api/monitors/{mid}")
def delete_monitor(mid: str):
    store.delete_monitor(mid)
    return {"ok": True}


@app.get("/api/graphs/{gid}/alerts")
def alerts(gid: str):
    need_graph(gid)
    return store.alerts(gid)


@app.post("/api/graphs/{gid}/alerts/seen")
def alerts_seen(gid: str):
    store.mark_alerts_seen(gid)
    return {"ok": True}


# ---- AI assist ----
@app.get("/api/ai/settings")
def ai_settings():
    """The AI-related setting names the UI should offer (name, placeholder, secret)."""
    return [{"name": n, "placeholder": p, "secret": s} for n, p, s in ai.AI_SETTINGS]


@app.post("/api/ai/extract")
def ai_extract(body: AIText):
    try:
        return {"entities": ai.extract_entities(store.settings(), body.text)}
    except ai.AIError as e:
        raise HTTPException(400, str(e))


@app.post("/api/graphs/{gid}/ai/suggest")
def ai_suggest(gid: str, body: Ids):
    need_graph(gid)
    ents = [e for e in map(store.get, body.ids) if e]
    try:
        return {"suggestions": ai.suggest_pivots(store.settings(), ents,
                                                 [engine.public(t) for t in engine.all_transforms(store)],
                                                 list(MACHINES.values()))}
    except ai.AIError as e:
        raise HTTPException(400, str(e))


@app.post("/api/graphs/{gid}/ai/summary")
def ai_summary(gid: str):
    need_graph(gid)
    try:
        return {"summary": ai.summarize_graph(store.settings(), store.graph(gid))}
    except ai.AIError as e:
        raise HTTPException(400, str(e))


# ---- images (forensic light table) ----
@app.post("/api/graphs/{gid}/images")
async def upload_image(gid: str, file: UploadFile, position_x: float = None, position_y: float = None):
    from store import MAX_IMAGE_BYTES
    need_graph(gid)
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"image too large (max {MAX_IMAGE_BYTES // 1_000_000} MB)")
    media = file.content_type or "image/png"
    if not media.startswith("image/"):
        raise HTTPException(400, "not an image")
    iid = store.add_image(gid, file.filename or "image", media, data)
    pos = {"x": position_x, "y": position_y} if position_x is not None else None
    props = {"image.id": {"name": "image.id", "value": iid, "displayName": "Image", "isReadOnly": True},
             "image.size": {"name": "image.size", "value": len(data), "displayName": "Bytes", "isReadOnly": True},
             "image.type": {"name": "image.type", "value": media, "displayName": "Type", "isReadOnly": True}}
    ent, _ = store.upsert_entity(gid, "Image", file.filename or iid, props, position=pos)
    return {"entity": ent, "imageId": iid}


@app.get("/api/images/{iid}")
def get_image(iid: str):
    img = store.image(iid)
    if not img:
        raise HTTPException(404, "no such image")
    return Response(img["data"], media_type=img["media_type"],
                    headers={"Cache-Control": "private, max-age=31536000"})


# ---- sightline resection (chronolocation triangulation) ----
@app.post("/api/sightline")
def sightline_resection(req: SightlineReq):
    return sightline.resection(req.far.model_dump(), req.near.model_dump(), req.camera.model_dump())


# ---- settings (API keys) ----
@app.get("/api/settings")
def settings():
    return store.settings_public()


@app.put("/api/settings/{name}")
def put_setting(name: str, s: SettingIn):
    store.set_setting(name, s.value, s.secret)
    return {"ok": True}


@app.delete("/api/settings/{name}")
def delete_setting(name: str):
    store.delete_setting(name)
    return {"ok": True}


# ---- import / export ----
def _import_graph(gid, g):
    ids = {}
    with store.tx(gid):
        for e in g.get("entities", []):
            ent = NewEntity(type=e["type"], value=e["value"], properties=e.get("properties", {}),
                            label=e.get("label"), notes=(e.get("metadata") or {}).get("notes"),
                            position=e.get("position"))
            props = {k: p.model_dump() for k, p in ent.properties.items()}
            row, _ = store.upsert_entity(gid, ent.type, ent.value.strip(), props, ent.label, notes=ent.notes,
                                         position=ent.position)
            ids[e["id"]] = row["id"]
        for l in g.get("links", []):
            if l["sourceId"] in ids and l["targetId"] in ids:
                store.upsert_link(gid, ids[l["sourceId"]], ids[l["targetId"]], l.get("label", ""),
                                  l.get("direction", "source-to-target"), l.get("weight"))
    return len(ids)


@app.post("/api/graphs/{gid}/import")
def import_graph(gid: str, g: dict):
    need_graph(gid)
    return {"imported": _import_graph(gid, g)}


MAX_IMPORT_BYTES = 64 << 20  # cap the raw upload before it (and its unzipped contents) hit memory


async def _read_capped(file: UploadFile, limit=MAX_IMPORT_BYTES):
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"file too large (max {limit >> 20} MB)")
    return data


@app.post("/api/graphs/{gid}/import/maltego")
async def import_maltego(gid: str, file: UploadFile):
    need_graph(gid)
    data = await _read_capped(file)
    try:
        g = maltego_import.parse_mtgx(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"imported": _import_graph(gid, g)}


@app.post("/api/import/mtz")
async def import_mtz(file: UploadFile):
    data = await _read_capped(file)
    try:
        parsed = maltego_import.parse_mtz(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    added = []
    for cfg in parsed["transforms"]:
        try:
            if cfg.get("workingDir") and not Path(cfg["workingDir"]).is_dir():
                cfg = {**cfg, "workingDir": None}  # a dir from another machine won't validate here
            t = {"id": f"{cfg['kind']}-{uuid.uuid4().hex[:8]}", **TransformCfg(**cfg).model_dump()}
            store.save_config(t)
            added.append(t["name"])
        except Exception as e:
            parsed["skipped"].append(f"{cfg.get('name', '?')}: {e}")
    return {"added": added, "skipped": parsed["skipped"], "entityTypes": parsed["entityTypes"]}


def graphml(g):
    root = ET.Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
    nkeys, ekeys = ("type", "value", "label", "properties", "notes"), ("label", "direction")
    for k in nkeys:
        ET.SubElement(root, "key", {"id": f"n_{k}", "for": "node", "attr.name": k, "attr.type": "string"})
    for k in ekeys:
        ET.SubElement(root, "key", {"id": f"e_{k}", "for": "edge", "attr.name": k, "attr.type": "string"})
    gx = ET.SubElement(root, "graph", edgedefault="directed")
    for e in g["entities"]:
        n = ET.SubElement(gx, "node", id=e["id"])
        vals = (e["type"], e["value"], e["label"], json.dumps(e["properties"]), e["metadata"]["notes"])
        for k, v in zip(nkeys, vals):
            if v:
                ET.SubElement(n, "data", key=f"n_{k}").text = v
    for l in g["links"]:
        x = ET.SubElement(gx, "edge", id=l["id"], source=l["sourceId"], target=l["targetId"])
        for k in ekeys:
            ET.SubElement(x, "data", key=f"e_{k}").text = l[k]
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


@app.get("/api/graphs/{gid}/report")
def case_report(gid: str, format: Literal["html", "md"] = "html"):
    need_graph(gid)
    name = next((g["name"] for g in store.graphs() if g["id"] == gid), "Case")
    g = store.graph(gid)
    evidence = store.evidence_index(gid)
    if format == "md":
        return Response(report.build_markdown(name, g, evidence), media_type="text/markdown",
                        headers={"Content-Disposition": 'attachment; filename="case-report.md"'})
    # html renders inline so the browser can Print → Save as PDF (and images load from /api/images)
    return Response(report.build_html(name, g, evidence), media_type="text/html; charset=utf-8")


@app.get("/api/graphs/{gid}/export")
def export(gid: str, format: Literal["json", "graphml"] = "json"):
    need_graph(gid)
    g = store.graph(gid)
    if format == "graphml":
        body, ctype = graphml(g), "application/graphml+xml"
    else:
        body, ctype = json.dumps(g, indent=1), "application/json"
    return Response(body, media_type=ctype,
                    headers={"Content-Disposition": f'attachment; filename="graph.{format}"'})


# ---- monitor scheduler ----
def run_machine_for_monitor(gid, machine, entity_ids):
    """Run a machine's phases and return the set of entity ids touched (new or found)."""
    found = set(entity_ids)
    for phase in machine["phases"]:
        ids = list(found)
        for step in phase["steps"]:
            t = next((t for t in engine.all_transforms(store) if t["id"] == step["transform"]), None)
            if not t:
                continue
            ents, _, _ = _run_transform(gid, t, ids, step.get("limit", 256))
            found.update(e["id"] for e in ents)
    return found


def scheduler_tick():
    now = int(time.time() * 1000)
    for m in store.monitors():
        if not m["enabled"] or m["next_run"] > now:
            continue
        store.update_monitor(m["id"], next_run=now + m["interval_min"] * 60_000, last_run=now)
        try:
            before = {e["id"] for e in store.graph(m["graph_id"])["entities"]}
            found = run_machine_for_monitor(m["graph_id"], MACHINES[m["machine_id"]], m["entity_ids"])
            new = [i for i in found if i not in before]
            if new:
                vals = [store.get(i)["value"] for i in new[:10] if store.get(i)]
                store.add_alert(m["graph_id"], m["id"],
                                f"{MACHINES[m['machine_id']]['name']}: {len(new)} new entities "
                                f"({', '.join(vals)}{'…' if len(new) > 10 else ''})", new)
        except Exception as e:
            store.add_alert(m["graph_id"], m["id"], f"monitor error: {type(e).__name__}: {e}", [])


def scheduler_loop():
    while True:
        try:
            scheduler_tick()
        except Exception:
            pass
        time.sleep(30)


# ---- static UI (mounted last so /api wins) ----
def mount_ui():
    g = gev_dir()
    if g.is_dir():  # mount /gev before "/" so it isn't shadowed by the catch-all UI
        app.mount("/gev", StaticFiles(directory=str(g), html=True), name="gev")
    d = ui_dir()
    if d.is_dir():
        app.mount("/", StaticFiles(directory=str(d), html=True), name="ui")


def main():
    global store
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("OSINT_PORT", 8000)))
    ap.add_argument("--data-dir", default=os.environ.get("OSINT_DATA_DIR"))
    args = ap.parse_args()

    db = os.environ.get("OSINT_DB")
    if not db:
        d = Path(args.data_dir) if args.data_dir else Path(__file__).parent
        d.mkdir(parents=True, exist_ok=True)
        db = str(d / "osint.db")
    store = Store(db)
    if not store.graphs():
        store.create_graph("Investigation 1")

    threading.Thread(target=scheduler_loop, daemon=True).start()
    mount_ui()

    import uvicorn
    print(f"OSINT Graph on http://127.0.0.1:{args.port}  (db: {db})")
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
else:
    # imported (tests, ASGI servers): use an in-env DB and ensure a default graph exists
    store = Store(os.environ.get("OSINT_DB", str(Path(__file__).parent / "osint.db")))
    if not store.graphs():
        store.create_graph("Investigation 1")
    mount_ui()

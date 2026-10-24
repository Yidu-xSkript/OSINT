"""Case report generator — a timestamped investigative dossier from a graph.

Markdown (portable) and printable HTML (Save-as-PDF). Both document: summary, key entities, the full
evidence trail (source URL, SHA-256, timestamp), entities with properties/notes, images, coordinates, links.
No dependencies.
"""
import html as _html
import time

# Mirror frontend/src/types.ts entity colors so the dossier's dots match the app.
TYPE_COLOR = {
    "Domain": "#4f8cff", "IPAddress": "#f2a33a", "Website": "#38bdf8", "URL": "#38c172",
    "EmailAddress": "#e3577a", "PhoneNumber": "#f472b6", "Person": "#f5d547", "Company": "#2ec4c6",
    "Affiliation": "#a970ff", "Location": "#ff7b54", "Phrase": "#c9b18a", "Snapshot": "#9aa3b0",
    "Image": "#22d3ee",
}


CLASS_LABEL = {"observed": "Observed", "source-asserted": "Source-asserted",
               "derived": "Derived", "hypothesis": "Hypothesis"}


def _prov(l):
    """Provenance suffix for a relationship: how to read it, where it came from, when — or '' if analyst-drawn."""
    bits = [CLASS_LABEL.get(l.get("classification"), "Analyst-added" if not l.get("classification") else l["classification"])]
    if l.get("provider"):
        bits.append(l["provider"])
    if l.get("createdAt"):
        bits.append(time.strftime("%Y-%m-%d", time.gmtime(l["createdAt"] / 1000)))
    return " · ".join(bits)


def _ts():
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _degree(graph):
    deg = {}
    for l in graph["links"]:
        deg[l["sourceId"]] = deg.get(l["sourceId"], 0) + 1
        deg[l["targetId"]] = deg.get(l["targetId"], 0) + 1
    return deg


def _by_type(entities):
    out = {}
    for e in entities:
        out.setdefault(e["type"], []).append(e)
    return dict(sorted(out.items()))


def _coords(e):
    for k in ("location.coordinates", "coordinates", "gps.coordinate"):
        p = e["properties"].get(k)
        if p and p.get("value"):
            return str(p["value"])
    return None


def build_markdown(name, graph, evidence_index):
    ents, links = graph["entities"], graph["links"]
    by_id = {e["id"]: e for e in ents}
    deg = _degree(graph)
    L = [f"# Case Report: {name}", "",
         f"_Generated {_ts()} · {len(ents)} entities · {len(links)} links_", ""]

    L += ["## Summary", ""]
    for t, es in _by_type(ents).items():
        L.append(f"- **{t}**: {len(es)}")
    L.append("")

    hubs = sorted(ents, key=lambda e: deg.get(e["id"], 0), reverse=True)[:10]
    if hubs and deg:
        L += ["## Key Entities (most connected)", ""]
        for e in hubs:
            if deg.get(e["id"]):
                L.append(f"- **{e['value']}** ({e['type']}) — {deg[e['id']]} links")
        L.append("")

    ev_rows = [(e, evidence_index.get(e["id"], [])) for e in ents if evidence_index.get(e["id"])]
    if ev_rows:
        L += ["## Evidence Trail", "",
              "Every item below was captured from a live source; the SHA-256 fixes the exact bytes seen.", ""]
        for e, evs in ev_rows:
            L.append(f"### {e['value']} ({e['type']})")
            if e["metadata"].get("discoveredByTransform"):
                L.append(f"Discovered by: {e['metadata']['discoveredByTransform']}")
            for v in evs:
                when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(v["fetchedAt"] / 1000))
                L.append(f"- `{v['transform'] or 'fetch'}` · {v['url'] or ''} · {v['size']:,} B · {when}")
                L.append(f"  - SHA-256: `{v['sha256']}`")
            L.append("")

    coords = [(e, _coords(e)) for e in ents if _coords(e)]
    if coords:
        L += ["## Verified Coordinates", ""]
        for e, c in coords:
            L.append(f"- **{e['value']}** — `{c}`")
        L.append("")

    L += ["## Entities", ""]
    for t, es in _by_type(ents).items():
        L.append(f"### {t} ({len(es)})")
        for e in es:
            L.append(f"- **{e['value']}**" + (f" — {e['label']}" if e.get("label") else ""))
            for p in e["properties"].values():
                if not p["name"].startswith(("display.", "image.")):
                    L.append(f"  - {p.get('displayName', p['name'])}: {p['value']}")
            if e["metadata"].get("notes"):
                L.append(f"  - Notes: {e['metadata']['notes']}")
        L.append("")

    if links:
        L += ["## Relationships", ""]
        for l in links:
            s, t = by_id.get(l["sourceId"]), by_id.get(l["targetId"])
            if s and t:
                arrow = "↔" if l["direction"] == "bidirectional" else "→"
                L.append(f"- {s['value']} {arrow} {t['value']}" + (f" ({l['label']})" if l["label"] else "")
                         + f" — _{_prov(l)}_")
        L.append("")

    L += ["---", f"_OSINT Graph case report · {name} · {_ts()}_"]
    return "\n".join(L)


CSS = """
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --amber:#d97706; --bg:#f8fafc; --card:#fff; }
* { box-sizing:border-box; }
body { font:14px/1.65 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:var(--ink); background:var(--bg); margin:0; }
.wrap { max-width:900px; margin:0 auto; background:var(--card); box-shadow:0 1px 3px rgba(0,0,0,.08); }
.cover { background:#0f172a; color:#fff; padding:34px 40px 28px; }
.eyebrow { font-size:11px; letter-spacing:.22em; text-transform:uppercase; color:var(--amber); font-weight:700; }
.cover h1 { font-size:30px; font-weight:800; margin:8px 0 14px; letter-spacing:-.01em; line-height:1.15; }
.facts { display:flex; flex-wrap:wrap; gap:0 28px; font-size:13px; color:#cbd5e1; }
.facts b { color:#fff; font-variant-numeric:tabular-nums; }
.rule { height:3px; background:var(--amber); width:64px; margin-top:16px; border-radius:2px; }
.body { padding:28px 40px 40px; }
.badges { display:flex; flex-wrap:wrap; gap:8px; margin:4px 0 8px; }
.badge { display:inline-flex; align-items:center; gap:7px; border:1px solid var(--line); border-radius:999px; padding:4px 11px 4px 9px; font-size:12px; font-weight:600; background:#fff; }
.dot { width:9px; height:9px; border-radius:50%; flex:none; }
.badge .n { color:var(--muted); font-weight:700; font-variant-numeric:tabular-nums; }
section { margin-top:30px; page-break-inside:auto; }
.sec-head { display:flex; align-items:baseline; gap:10px; border-bottom:2px solid var(--ink); padding-bottom:6px; margin-bottom:12px; }
.sec-num { font-size:12px; font-weight:800; color:var(--amber); font-variant-numeric:tabular-nums; }
.sec-head h2 { font-size:16px; font-weight:800; margin:0; text-transform:uppercase; letter-spacing:.04em; }
h3 { font-size:14px; margin:14px 0 4px; }
code { font-family:'SF Mono',Consolas,'Courier New',monospace; font-size:12px; background:#f1f5f9; padding:1.5px 5px; border-radius:3px; word-break:break-all; }
a { color:#2563eb; text-decoration:none; } a:hover { text-decoration:underline; }
ul { margin:4px 0 10px; padding-left:20px; } li { margin:2px 0; }
.lede { color:var(--muted); margin:-4px 0 12px; }
.gallery { display:flex; flex-wrap:wrap; gap:16px; }
.gallery figure { margin:0; width:270px; page-break-inside:avoid; }
.gallery img { width:270px; height:auto; border-radius:6px; border:1px solid var(--line); display:block; }
.gallery figcaption { font-size:12px; color:var(--muted); margin-top:5px; }
.ev { border:1px solid var(--line); border-left:4px solid var(--amber); border-radius:6px; padding:12px 14px; margin:10px 0; page-break-inside:avoid; background:#fffdf9; }
.ev h3 { margin:0 0 6px; } .ev .disc { font-weight:500; color:var(--muted); font-size:12px; }
.ev .row { padding:6px 0; border-top:1px dashed var(--line); font-size:13px; }
.ev .row:first-of-type { border-top:none; }
.ev .hash { color:var(--muted); font-size:11px; margin-top:3px; }
.rank { list-style:none; padding:0; margin:0; }
.rank li { display:flex; align-items:center; gap:10px; padding:5px 0; border-bottom:1px solid var(--line); }
.rank .idx { color:var(--amber); font-weight:800; font-size:12px; width:22px; font-variant-numeric:tabular-nums; }
.rank .links { margin-left:auto; color:var(--muted); font-size:12px; white-space:nowrap; }
.rank .ty { color:var(--muted); font-size:12px; }
.coords { list-style:none; padding:0; margin:0; }
.coords li { padding:4px 0; }
.coords li::before { content:'◎'; color:var(--amber); margin-right:8px; }
.etype { display:flex; align-items:center; gap:8px; margin:16px 0 4px; font-weight:700; font-size:13px; }
.etype .n { color:var(--muted); font-weight:600; }
.props { color:var(--muted); font-size:12.5px; }
.rel li::marker { color:var(--amber); }
.rel .prov { color:var(--muted); font-size:11px; }
footer { color:var(--muted); font-size:12px; border-top:1px solid var(--line); margin-top:36px; padding-top:14px; }
.toolbar { position:sticky; top:0; z-index:5; background:#0f172a; padding:10px 40px; display:flex; gap:10px; align-items:center; }
.toolbar button { font:inherit; font-weight:700; font-size:13px; background:var(--amber); color:#1a1200; border:none; border-radius:6px; padding:7px 16px; cursor:pointer; }
.toolbar span { color:#94a3b8; font-size:12px; }
@media print { .toolbar { display:none; } body { background:#fff; } .wrap { box-shadow:none; max-width:none; } .cover { -webkit-print-color-adjust:exact; print-color-adjust:exact; } section { page-break-inside:auto; } }
"""


def build_html(name, graph, evidence_index):
    ents, links = graph["entities"], graph["links"]
    by_id = {e["id"]: e for e in ents}
    deg = _degree(graph)
    e = _html.escape
    n = [0]

    def dot(t):
        return f'<span class="dot" style="background:{TYPE_COLOR.get(t, "#888")}"></span>'

    def section(title, inner):
        n[0] += 1
        return (f'<section><div class="sec-head"><span class="sec-num">{n[0]:02d}</span>'
                f'<h2>{e(title)}</h2></div>{inner}</section>')

    badges = "".join(f'<span class="badge">{dot(t)}{e(t)} <span class="n">{len(es)}</span></span>'
                     for t, es in _by_type(ents).items())
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Case Report: {e(name)}</title><style>{CSS}</style></head><body>
<div class="toolbar"><button onclick="window.print()">⎙ Print / Save as PDF</button><span>OSINT Graph · Case Dossier</span></div>
<div class="wrap">
<header class="cover"><div class="eyebrow">OSINT Graph · Case Dossier</div>
<h1>{e(name)}</h1>
<div class="facts"><span>Generated&nbsp;<b>{e(_ts())}</b></span><span><b>{len(ents)}</b> entities</span><span><b>{len(links)}</b> links</span><span><b>{len(evidence_index)}</b> with evidence</span></div>
<div class="rule"></div></header>
<div class="body">
<div class="badges">{badges}</div>"""]

    imgs = [x for x in ents if x["type"] == "Image" and x["properties"].get("image.id")]
    if imgs:
        figs = "".join(
            f'<figure><img src="/api/images/{e(x["properties"]["image.id"]["value"])}" alt="{e(x["value"])}">'
            f'<figcaption><b>{e(x["value"])}</b>{"<br>" + e(x["metadata"]["notes"]) if x["metadata"].get("notes") else ""}</figcaption></figure>'
            for x in imgs)
        parts.append(section("Evidence Images", f'<div class="gallery">{figs}</div>'))

    hubs = [x for x in sorted(ents, key=lambda z: deg.get(z["id"], 0), reverse=True)[:10] if deg.get(x["id"])]
    if hubs:
        rows = "".join(f'<li><span class="idx">{i:02d}</span>{dot(x["type"])}<b>{e(x["value"])}</b>'
                       f'<span class="ty">{e(x["type"])}</span><span class="links">{deg[x["id"]]} links</span></li>'
                       for i, x in enumerate(hubs, 1))
        parts.append(section("Key Entities", f'<ul class="rank">{rows}</ul>'))

    ev_rows = [(x, evidence_index.get(x["id"], [])) for x in ents if evidence_index.get(x["id"])]
    if ev_rows:
        blocks = []
        for x, evs in ev_rows:
            rows = "".join(
                f'<div class="row"><code>{e(v["transform"] or "fetch")}</code> &middot; '
                f'{("<a href=" + chr(34) + e(v["url"]) + chr(34) + ">" + e(v["url"]) + "</a>") if v["url"] else ""} '
                f'&middot; {v["size"]:,} B &middot; {e(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(v["fetchedAt"] / 1000)))}'
                f'<div class="hash">SHA-256: <code>{e(v["sha256"])}</code></div></div>' for v in evs)
            disc = f' <span class="disc">· discovered by {e(x["metadata"]["discoveredByTransform"])}</span>' if x["metadata"].get("discoveredByTransform") else ""
            blocks.append(f'<div class="ev"><h3>{dot(x["type"])} {e(x["value"])}{disc}</h3>{rows}</div>')
        parts.append(section("Evidence Trail",
                             '<p class="lede">Every item was captured from a live source; the SHA-256 fixes the exact bytes seen.</p>'
                             + "".join(blocks)))

    coords = [(x, _coords(x)) for x in ents if _coords(x)]
    if coords:
        rows = "".join(f'<li><b>{e(x["value"])}</b> &nbsp;<code>{e(c)}</code></li>' for x, c in coords)
        parts.append(section("Verified Coordinates", f'<ul class="coords">{rows}</ul>'))

    ent_html = []
    for t, es in _by_type(ents).items():
        ent_html.append(f'<div class="etype">{dot(t)}{e(t)} <span class="n">({len(es)})</span></div><ul>')
        for x in es:
            props = "".join(f'<li>{e(p.get("displayName", p["name"]))}: {e(str(p["value"]))}</li>'
                            for p in x["properties"].values() if not p["name"].startswith(("display.", "image.")))
            note = f'<li>Notes: {e(x["metadata"]["notes"])}</li>' if x["metadata"].get("notes") else ""
            ent_html.append(f'<li><b>{e(x["value"])}</b>{" — " + e(x["label"]) if x.get("label") else ""}'
                            + (f'<ul class="props">{props}{note}</ul>' if props or note else "") + "</li>")
        ent_html.append("</ul>")
    parts.append(section("Entities", "".join(ent_html)))

    if links:
        rows = []
        for l in links:
            s, t = by_id.get(l["sourceId"]), by_id.get(l["targetId"])
            if s and t:
                arrow = "↔" if l["direction"] == "bidirectional" else "→"
                rows.append(f'<li>{e(s["value"])} {arrow} {e(t["value"])}{" (" + e(l["label"]) + ")" if l["label"] else ""}'
                            f' <span class="prov">{e(_prov(l))}</span></li>')
        parts.append(section("Relationships", f'<ul class="rel">{"".join(rows)}</ul>'))

    parts.append(f'<footer>OSINT Graph case report · {e(name)} · {e(_ts())}</footer></div></div></body></html>')
    return "".join(parts)

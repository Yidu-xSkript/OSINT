# OSINT Graph

An open-source link-analysis and OSINT pivoting tool modelled on Maltego's core ideas: an entity–relationship graph, transforms that turn one entity into others, and iterative pivoting. Transforms speak the **real Maltego protocol**, so existing `maltego-trx` transforms run unmodified, either locally or remotely.

Reverse-engineering notes are in [docs/REA-FINDINGS.md](docs/REA-FINDINGS.md).

## Features

- **Graph canvas** (Cytoscape WebGL) with Force / Tree / Radial / Grid layouts that run in a Web Worker, so the UI never freezes even at 10k+ nodes. Minimap, drag-and-drop palette, property inspector.
- **Transforms**: built-in (DNS, certificate logs, RDAP/WHOIS, IP geo, page scrape, snapshots, GitHub), **17 bring-your-own-key data connectors** (Shodan, VirusTotal, Have I Been Pwned, urlscan, Wayback, Hunter, AbuseIPDB, GreyNoise, SecurityTrails, RIPEstat), plus **local** and **remote** Maltego-protocol transforms you add yourself.
- **Machines**: multi-phase transform pipelines (Domain Footprint, Username to Person, Web Page Recon).
- **Monitoring**: re-run a machine on a schedule and get alerts when new entities appear (🔔).
- **Evidence trail**: every HTTP response a transform makes is stored (source URL, timestamp, SHA-256) and downloadable from the inspector.
- **AI assist** (✨): extract entities from pasted text, suggest next pivots, summarize the graph. Uses Claude (default `claude-opus-5-5`) or any OpenAI-compatible endpoint — including open-weight / self-hosted models (Ollama, vLLM, llama.cpp, LM Studio).
- **Cases**: multiple independent graphs; undo/redo (Ctrl+Z / Ctrl+Y); paste identifiers to auto-create typed entities.
- **Import/export**: JSON round-trip, GraphML export, and **Maltego `.mtgx` graph / `.mtz` config import**.
- **ChronoSight image-geolocation mode**: a **Forensic Light Table** (upload an image → non-destructive forensic canvas: Shadow Recovery / Invert & High-Pass / RGB channel split / Reflective De-glare, brightness/contrast/shadow-lift/gamma/sharpness, pan + zoom to pixel level with a pixel grid, engine `frontend/src/forensics/ImageForensicsEngine.ts`), a **split/overlay compare** (curtain + opacity blend + candidate alignment), a **candidate funnel** (status tracking + verification checklist over venue entities), a **case-report generator** (polished printable HTML / Markdown dossier with the evidence trail), and a **temporal helper** (`chrono.py`): sun position (sunrise/sunset + azimuth/elevation for shadow analysis, offline) and historical weather (Open-Meteo, no key), driven by the `chrono.datetime` setting.
- **Geospatial / God's Eye View bridge** (`geo.py`): geocode a place (Nominatim), find **live aircraft overhead** (ADS-B), **nearby venues** (OSM Overpass), and **"Show on God's Eye View"** — opens the [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view) 3D globe centered on the coordinates. Phone OSINT (`phone.py`): libphonenumber (offline), numverify, Twilio Lookup, IPQS HLR, and free reverse-search.
- **Native Windows app**: packaged with Tauri (`desktop/`), Python backend as a sidecar.

## Run

```sh
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
python backend/app.py                 # → http://127.0.0.1:8000  (serves API + built UI)
```

Options: `python backend/app.py --port 8000 --data-dir DIR` (the SQLite DB lives at `DIR/osint.db`).

To develop with hot reload, run `python backend/app.py` and `npm run dev` in `frontend/` together, then open http://localhost:5173. Vite proxies `/api` to the backend.

To build the **Windows desktop app**: `powershell -ExecutionPolicy Bypass -File desktop/build.ps1` (needs Rust + VS C++ build tools + WebView2). It produces an NSIS installer and an MSI under `desktop/src-tauri/target/release/bundle/`.

To run the backend self-checks (no network): `python backend/test_core.py`, `test_connectors.py`, `test_maltego_import.py`.

## AI setup

Open **Transforms… → API Keys & Settings**. For Claude, set `anthropic.apikey`. For an open-weight / self-hosted model, set `ai.provider=openai`, `openai.baseurl` (e.g. `http://localhost:11434/v1` for Ollama), and `openai.model` (`llama3.1`, `qwen2.5`, …); `openai.apikey` can be any non-empty string for a local server. Keys are stored server-side and never returned to the browser.

## Architecture

```
frontend/ (Vite + React + TS + Tailwind)       backend/ (FastAPI, Python 3.12)
 GraphCanvas  cytoscape WebGL, worker layouts    app.py           REST API, cases, undo, evidence, monitors, AI
 Minimap      bird's-eye canvas                  store.py         SQLite: graphs, entities+links, FTS5, undo journal,
 Palette      drag-and-drop entity creation                       evidence, monitors, alerts, settings
 Inspector    props / links / evidence           engine.py        transform runner: builtin | local | remote (+ evidence capture)
 TransformWizard  transforms, API keys, .mtz     builtin.py       DNS, CT logs, RDAP, ipinfo, scrape, snapshot, GitHub
 AIPanel      extract / suggest / summarize      connectors.py    17 BYO-key data sources (Shodan, VT, HIBP, …)
 machines.ts  multi-phase pipelines              ai.py            Claude or OpenAI-compatible (open-weight) provider
 ContextMenu  transforms + machines + monitor    maltego_xml.py   Maltego wire protocol <-> Entity model
                                                 maltego_import.py  .mtgx graph + .mtz config parsers
                                                 machines.py      machine defs for the monitor scheduler
desktop/ (Tauri v2 + Rust)  native Windows app; Python backend frozen as a sidecar
```

A transform run (`POST /api/transforms/{id}/run`) works like this:
1. Selected entities fan out to 8 worker threads.
2. Each transform returns results plus link labels and directions.
3. Results are merged into the graph Maltego-style: the same (type, value) becomes one entity and new properties merge in.
4. The UI places new entities in a ring around their source.

The whole merge is one SQLite transaction.

**Data model:** `frontend/src/types.ts` holds the canonical `Entity`, `EntityProperty` and `Link`. The spec's `EntityType` union is extended with `Domain` and `IPAddress`, because DNS and IP pivots need them. Maltego type ids map both ways in `maltego_xml.py`. Unknown incoming types become a `Phrase` carrying a read-only `maltego.type` property.

**Export/import:** JSON round-trips. GraphML is export-only and opens in Gephi, yEd and Cytoscape desktop.

## Pasting and machines

- **Paste onto the graph** (Ctrl+V, focus not in a text field): each line becomes an entity, and its type is detected the way Maltego's entity Converters do it. Check: `node frontend/detect.check.ts`.
- **Machines** (`frontend/src/machines.ts`): multi-phase transform pipelines, modelled on Maltego's `.machine` scripts. Right-click an entity → Machines. Each phase runs its transforms in parallel on everything found so far. The toolbar `⚙ … ■` button stops a machine after the current phase. Built-in machines: Domain Footprint, Username to Person, Web Page Recon.

## Transforms

| Kind | How it runs |
|---|---|
| builtin | Python functions in `builtin.py` |
| local | `command args… <value> [k=v#…]` → Maltego XML on stdout. For a `maltego-trx` project: command `python`, args `project.py local <name>`, working dir = the project. Example: `examples/dns_to_ip_local.py` |
| remote | POSTs a `MaltegoTransformRequestMessage` to any TRX server URL, e.g. `http://localhost:8080/run/dnstoip/` from `python project.py runserver` |

API keys go in **Transforms… → API Keys & Settings** and are stored server-side.
- A transform receives only the settings it declares.
- Remote transforms get them as `TransformFields`. Local transforms get them as `TRX_SETTING_<NAME>` environment variables (an extension: Maltego has no settings for local transforms).
- Secret values are never returned to the browser.

## Security model

- The server binds `127.0.0.1` and rejects non-loopback `Host` headers, which blocks DNS rebinding. It sends no CORS headers. This matters because the API can register local commands, so anyone who can reach it can run code.
- Local transforms run with:
  - an argv list (no shell),
  - a scrubbed environment,
  - no stdin,
  - a timeout and a 20 MB output cap.

  That is process-level isolation only; run the backend in a container for untrusted transforms.
- Settings are never sent over plain HTTP to non-loopback hosts.
- FTS queries are quoted so user input can't inject FTS5 syntax.

## Measured limits (10,000 entities / 11,999 links, Chrome, WebGL on)

| Operation | Time |
|---|---|
| Import | 1.5 s |
| Load (`GET /api/graph`) | 0.6 s |
| FTS search | 5 ms |

Layouts on graphs over 300 nodes run in a Web Worker (`layoutWorker.ts`) on a headless copy of the graph, so the page stays usable while they compute. The longest main-thread pause is applying the result. Smaller graphs lay out in-page with animation.

| Layout (worker) | Total time | Longest UI pause |
|---|---|---|
| Force (fCoSE draft) | 6.4 s | 0.3 s |
| Grid | 1.5 s | 0.2 s |
| Hierarchical (dagre) | did not finish in 2 min on this test graph (random cross-links) | UI stays responsive |

The `⟳ layout… ✕` indicator cancels a running layout, and starting another layout cancels the current one.

## Not built yet

- Link colour/style/thickness decorators (parsed but dropped)
- Overlays and remote entity icons in the canvas
- Maltego `.mtgl` (large-graph, Lucene) import — export as `.mtgx` from Maltego instead
- Transform Hub / TDS directory
- Per-account rate limiting; signed installers (SmartScreen will warn on first run)
- The `.mtgx` node/edge encoding is from public docs, not a real exported file — add one to `backend/fixtures/` to confirm

## God's Eye View bridge

Two halves, both working without running GEV's server:
- **Data** — `geo.py` calls the same public upstreams GEV uses, directly: **Nominatim** (geocode a place name → coordinates), **adsb.lol** (live aircraft within N nm, no key), **OSM Overpass** (nearby venues by type, with mirror rotation). On a `Location` with coordinates (from `ip-geo`, `To Coordinates [Nominatim]`, or a `lat,lon` value): *To Aircraft Overhead [ADS-B]*, *To Nearby Venues [OSM]*.
- **Visualization** — *Show on God's Eye View* (or right-click a Location → "🌍 Open in God's Eye View") opens GEV's 3D globe centered on the point (`#lat=..&lon=..`). In the **desktop app** it opens as a **native child window** (a Tauri WebviewWindow — top-level navigation, so GEV's anti-framing headers don't apply); in the **browser** it opens an in-app iframe panel (needs GEV to allow local framing) with an "Open in tab" fallback. Run GEV (`npm run dev`); set the `gev.url` setting to its address (default `http://localhost:4173`).

Settings (non-secret, in Transforms → API Keys): `geo.radius_nm` (aircraft), `geo.venue_type` (hookah/bar/nightclub/cafe/restaurant/hotel/any) and `geo.radius_m` (venues), `gev.url`.

Licensing: GEV is MIT; one bundled map layer is CC BY-NC-SA (fine for non-commercial use — keep attribution and share-alike). Data: aircraft © adsb.lol · map data © OpenStreetMap contributors · globe © God's Eye View (Bilawal Sidhu).

The same Overpass venue search is the engine a future ChronoSight image-geolocation mode would reuse.

# OSINT Graph — Design & Feature Review Brief

*Prepared for an external reviewer · generated from the codebase on 2026-10-13*

This document gives a reviewer everything needed to evaluate **OSINT Graph** on three
dimensions — **frontend design**, **usage simplicity**, and **UI/UX** — plus a complete
inventory of what the tool does. A self-assessment is included so you have something
concrete to agree with, push back on, or extend. Please treat the "Questions for the
reviewer" section as the main ask.

---

## 1. What it is

OSINT Graph is an open-source, non-commercial **link-analysis / OSINT workbench** modeled
on Maltego. You drop entities (a domain, email, phone number, person, image…) onto a graph
canvas and run **transforms** that pull related data from public sources, building an
entity-relationship graph you can pivot through iteratively. On top of the Maltego-style
core it adds an **image-geolocation / chronolocation** suite ("ChronoSight") and an embedded
**3D globe** ("God's Eye View") for geospatial work.

- **Backend:** Python / FastAPI + SQLite (FTS5 full-text search, adjacency-list graph,
  undo journal). Speaks the Maltego TRX transform protocol.
- **Frontend:** Vite + React 19 + TypeScript + Tailwind v4 + Cytoscape.js (WebGL renderer,
  Web-Worker graph layouts).
- **Desktop:** Tauri v2 native Windows app with a bundled Python sidecar — installs and runs
  as one `.exe`/`.msi`, no separate servers to start.
- **AI:** bring-your-own-key assist (entity extraction, pivot suggestions, case summaries) via
  Claude or any OpenAI-compatible / open-weight endpoint.

**How to run it for review:**
- Desktop: install `OSINT Graph_0.1.0_x64-setup.exe` (NSIS) or the `.msi`, launch the app.
- Web/dev: `uvicorn` backend + `npm run dev` in `frontend/` (see repo README).

---

## 2. Complete feature list

### Graph & canvas
- Entity-relationship graph on a **Cytoscape.js** canvas; standard **WebGL renderer toggle**
  for 10k+ element graphs.
- **Web-Worker layouts** (force / tree / radial / grid) so the UI never freezes during layout.
- **Minimap** for navigation on large graphs.
- **13 entity types**, each color- and glyph-coded: Domain, IP Address, Website, URL,
  Email Address, Phone Number, Person, Company, Affiliation, Location, Phrase, Snapshot, Image.
- **Entity palette** (left rail): drag onto the canvas or click to add.
- **Paste-to-entity**: paste text and it auto-detects the type (IPv4/IPv6, email, URL, domain,
  phone, etc.), Maltego-style.
- **Right-click context menu** on entities to run transforms.
- **Node/graph animations**: new-node fade-in + amber "discovery" ring, cyan hover ring.
- **Inspector** (right rail): entity properties, notes, evidence.
- **Undo / redo** (Ctrl+Z / Ctrl+Y), backed by a persistent journal.
- **Full-text search** across the graph (SQLite FTS5).
- **Cases**: multiple independent graphs, with create / rename / delete.

### Transforms (46 total)
Named Maltego-style — `To <Output> [<Source>]` — so intent is readable at a glance.
- **DNS / domain:** To IP Address [DNS], Mail Servers [MX], Name Servers [NS], TXT Records,
  Reverse DNS [PTR], Subdomains [crt.sh], WHOIS Contacts [RDAP], Website, Homepage URL, Domain.
- **IP:** Location / ASN [ipinfo], Reverse DNS [PTR].
- **URL / web:** To Snapshot, To Emails, Phones & Linked Sites.
- **Threat-intel connectors (bring-your-own-key, 17):** Shodan (ports, subdomains),
  VirusTotal (reputation, IPs, domains, subdomains, URL reputation), HIBP (breaches),
  urlscan, Wayback (archived URLs & snapshots), Hunter (emails & people), AbuseIPDB,
  GreyNoise, SecurityTrails, RIPEstat.
- **People / social:** To GitHub Profile Details, To GitHub Account.
- **Phone OSINT (6):** Details [libphonenumber, offline], Carrier & Country [numverify],
  Caller Name & Line Type [Twilio Lookup], HLR / Live Status [IPQualityScore],
  Reverse-Search [web], Country Code.
- **Geospatial:** To Coordinates [Nominatim], Aircraft Overhead [ADS-B], Nearby Venues [OSM],
  Show on God's Eye View.
- **Chronolocation:** To Sun Position [offline NOAA solar math], Historical Weather [Open-Meteo].

### ChronoSight — forensic image & chronolocation suite
- **Forensic Light Table**: non-destructive Canvas2D image pipeline — brightness, contrast,
  shadow-lift, gamma, invert, sharpness, channel isolation; presets (Shadow Recovery,
  Invert & High-Pass, RGB split, Reflective De-glare); pan/zoom with a pixel grid.
- **Split / overlay compare**: curtain split, blend modes, alignment.
- **Candidate funnel**: track location candidates through a status pipeline
  (Unreviewed → Promising → Matched / Ruled Out) with a verification checklist;
  nearby-venue results are auto-flagged as candidates.
- **Sightline resection** (Bellingcat / Gary Riddell technique): pick a far landmark, a near
  landmark, and a candidate building; solve the camera's facing azimuth/compass, height, floor,
  and collinearity error. Available both as a panel and **directly on the 3D globe** (click to
  place anchors, a glowing ray is cast, the floor ladder is drawn).

### God's Eye View — embedded 3D globe
- CesiumJS globe **bundled and served in-app** (no separate server, keyless Esri imagery).
- **Live data layers** via keyless proxies: military aircraft (ADS-B), satellite TLEs
  (Celestrak), OSM Overpass venues.
- Re-themed to match the app (amber accent + logo, cyan data trails).
- Opens as a **native child window** in the desktop app.

### Collaboration-adjacent & workflow
- **Machines**: chain transforms into reusable pipelines.
- **Monitors + alerts**: a background scheduler re-runs machines on entities on an interval and
  raises alerts on change.
- **Evidence trail**: every transform's raw response is stored per entity with a SHA-256 hash
  for provenance.
- **AI assist** (BYO-key): extract entities from pasted text, suggest next pivots, summarize a case.
- **Case report generator**: polished printable HTML (Print → Save as PDF) + Markdown export,
  with entity-type badges, numbered sections, evidence trail, and the sightline floor ladder.
- **Import**: Maltego `.mtgx` / `.mtz` and GraphML graphs.

---

## 3. Layout at a glance

A fixed three-pane grid (columns `200px · 1fr · 320px`, rows `toolbar · canvas · 150px`):

```
┌─────────────────────────────────────────────────────────────┐
│ Toolbar: [Case ▾] + ✎ 🗑 | ↶ ↷ | limit▭ | ✨AI ⌖Sightline     │
│          ⚙machines  monitors  report  import  [WebGL]  🔍search│
├──────────┬────────────────────────────────────┬──────────────┤
│ Entity   │                                    │  Inspector    │
│ Palette  │          Graph canvas              │  (properties, │
│ (13 types│          (Cytoscape)               │   notes,      │
│  drag or │                                    │   evidence,   │
│  click)  │                                    │   AI panel)   │
├──────────┴────────────────────────────────────┴──────────────┤
│ Transform output log (150px)                                  │
└─────────────────────────────────────────────────────────────┘
```

**Theme:** dark (`#0f1115` background), amber primary accent (`#f0a63c`), cyan secondary
(`#38bdf8`), per-type node colors. System-UI font at 13px.

---

## 4. Self-assessment (for you to challenge)

### Frontend design
**Working well**
- Familiar Maltego-style three-pane layout; analysts coming from Maltego will feel at home.
- Consistent dark theme; entity types are distinctly color- and glyph-coded, which reads well
  on a dense graph.
- Graph animations (discovery ring, hover ring) give useful feedback without being noisy.

**Worth scrutiny**
- **Toolbar is emoji-dense and label-light** (`↶ ↷ ✨ ⌖ ⚙ ✎ 🗑 ⟳`). It relies almost entirely on
  hover tooltips; a first-time user can't scan it. This is the single biggest design risk.
- **Accent-color inconsistency**: the brand accent is amber, but base form controls
  (`.field`, `.btn`) use a **sky-blue** focus/hover (`sky-500`). Focus states and brand color
  disagree.
- **Fixed-pixel grid** (200 / 320 columns, 150px log row): no responsive behavior and no panel
  resizing — fine on a wide desktop, cramped on a laptop or split screen.

### Usage simplicity
**Working well**
- Entity creation is low-friction: drag from palette, click to add, **or** paste text and let
  type-detection place it.
- Transform names (`To IP Address [DNS]`) state both the output and the data source, so you
  know what you'll get and where it comes from before running.
- One-executable desktop install; the globe and backend "just work" with nothing to start.

**Worth scrutiny**
- **No onboarding / empty state** beyond "Drag onto the graph, or click to add." New users
  won't discover transforms, the AI panel, machines, or ChronoSight on their own.
- **BYO-key reality**: 17 of 46 transforms need an API key. First-run value depends on how
  discoverable and painless the settings/key entry is — reviewer should test the cold-start path.
- **Native browser `prompt()` / `confirm()`** are used for renaming and deleting cases. They're
  unstyled, break the dark theme, and block the UI.

### UI/UX
**Working well**
- Right-click-to-transform, undo/redo, FTS search, and the minimap are the expected power-user
  affordances and they're present.
- Evidence trail + report generator make the output defensible/shareable — strong for the OSINT
  use case.

**Worth scrutiny**
- **Transform discoverability**: is right-click the only path? Is there search/filter when an
  entity has many applicable transforms? (46 and growing.)
- **Feedback during long/remote transforms**: the 150px bottom log is the main status surface —
  is it enough when several transforms or a machine run concurrently?
- **Accessibility**: emoji-only buttons, color-dependent node identity, and keyboard support
  limited to Delete / Ctrl+Z / Ctrl+Y. No obvious screen-reader or high-contrast story.

---

## 5. Questions for the reviewer

1. **Toolbar legibility** — is the emoji-dense, tooltip-only toolbar acceptable for the target
   analyst, or should it carry text labels / grouping / an overflow menu?
2. **Cold start** — install fresh, create a case, and try to get *one* useful result without
   reading docs. Where did you get stuck? Was the API-key requirement clear?
3. **Discoverability** — did you find the AI panel, Sightline, machines, monitors, and the
   forensic/ChronoSight tools on your own? What stayed hidden?
4. **Visual hierarchy** — does the three-pane density help or overwhelm? Should panels be
   collapsible/resizable?
5. **Color system** — is the amber/cyan-on-dark palette coherent? Does the sky-blue focus state
   read as a bug?
6. **The graph itself** — labels, spacing, node sizing, animation: readable at 50 nodes? at 500?
7. **Anything that felt unprofessional or broke the flow** (the native `prompt()` dialogs are a
   known one — what else?).

---

*When you've collected the reviewer's notes, send them back and I'll turn them into a
prioritized change list and implement the fixes.*

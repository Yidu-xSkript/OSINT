# Step 1 — Reconnaissance findings

## Method and evidence boundary

| Target | How it was analysed | Evidence type |
|---|---|---|
| `maltego-trx` 1.7.0 (PyPI wheel, pure Python) | Wheel extracted and its source read directly. The REA skill routes readable source to normal tools; REA's decompilers are for shipped binaries. | **Observed** (source) |
| Interop with maltego-trx | Our encoder/decoder run against trx's own `MaltegoMsg` / `MaltegoTransform` classes | **Observed** (executed) |
| Maltego desktop client | Not installed on this machine, so there was nothing to inspect | **Unknown** |
| SpiderFoot, OWASP Amass | Not analysed | **Unknown** |
| Graph renderer options | `cytoscape` 3.34.3 source/typings read, then measured in Chrome on 10k nodes | **Observed** (source + measured) |

Anything this file says about the Maltego *client's* internals is inference from trx, the client's reference implementation, not observation.

## 1. Entity schema representation

Source: `maltego_trx/maltego.py` (`MaltegoEntity.build_xml`), `entities.py`, `overlays.py`.

```xml
<Entity Type="maltego.Domain">            <!-- namespaced type id -->
  <Value>example.com</Value>
  <Weight>100</Weight>
  <DisplayInformation>
    <Label Name="Info" Type="text/html">…html…</Label>
  </DisplayInformation>
  <AdditionalFields>                      <!-- the property bag -->
    <Field Name="whois-info" DisplayName="Whois" MatchingRule="strict|loose">…</Field>
  </AdditionalFields>
  <Overlays><Overlay propertyName="…" position="N|S|W|NW|SW|C" type="image|colour|text"/></Overlays>
  <IconURL>https://…</IconURL>
</Entity>
```

- **Type ids** are namespaced strings, e.g. `maltego.Domain`, `maltego.IPv4Address`, `maltego.EmailAddress`, `maltego.Person`, `maltego.Company`, `maltego.Website`, `maltego.URL`, `maltego.PhoneNumber`, `maltego.Location`, `maltego.Phrase` (37 constants in `entities.py`). `maltego.Phrase` is the fallback when no type is given.
- **Properties** are flat `Name → text` fields. Each one has a `DisplayName` and a `MatchingRule`: `strict` fields take part in entity identity when the client merges entities, `loose` fields don't.
- **Legacy names:** `entity_property_map` translates v2 property names to v3 (e.g. `Person.firstname → person.firstnames`). This is driven by the request's `<Genealogy><Type Name=…/>` chain.
- **UI decorators** travel in the same bag under reserved prefixes:
  - `link#maltego.link.label` / `.color` / `.style` (0–3) / `.thickness`, plus `link#maltego.link.direction = output-to-input` to reverse an edge.
  - `bookmark#` (colours −1..4) and `notes#`.
  - So **link labels and edge direction are attributes of the *output entity***, not separate link objects.

## 2. Transform invocation protocol

### Remote (HTTP) — `server.py`
`POST /run/<name>/` with the body below. The name is lowercased and `_` becomes `-` (`utils.name_to_path`). A `GET` request only returns a help string.

```xml
<MaltegoMessage><MaltegoTransformRequestMessage>
  <Entities><Entity Type="maltego.Domain">
    <Genealogy><Type Name="maltego.Domain"/></Genealogy>
    <Value>example.com</Value><Weight>100</Weight>
    <AdditionalFields><Field Name="…">…</Field></AdditionalFields>
  </Entity></Entities>
  <TransformFields><Field Name="api.key">…</Field></TransformFields>   <!-- transform settings / secrets -->
  <Limits SoftLimit="256" HardLimit="256"/>                           <!-- the result "slider" -->
</MaltegoTransformRequestMessage></MaltegoMessage>
```

Caveat on how much of this is observed: trx's `MaltegoMsg` parses with `getElementsByTagName`, so the element names it reads (`Entity`, `Value`, `Weight`, `AdditionalFields/Field`, `Genealogy/Type`, `TransformFields/Field`, `Limits@SoftLimit`) are observed. The `MaltegoTransformRequestMessage` wrapper is **inferred** (trx never checks it), but it is harmless.

Response:

```xml
<MaltegoMessage><MaltegoTransformResponseMessage>
  <Entities>…Entity…</Entities>
  <UIMessages><UIMessage MessageType="FatalError|PartialError|Inform|Debug">…</UIMessage></UIMessages>
</MaltegoTransformResponseMessage></MaltegoMessage>
```

Errors come back as `<MaltegoTransformExceptionMessage><Exceptions><Exception>…`. An unhandled exception inside trx returns HTTP 200 with a `PartialError` UIMessage, not a 5xx.

### Local (CLI) — `handler.py`, `mtz.py`, `decorator_registry.py`
- The client spawns `transform.local.command` + `transform.local.parameters` in `transform.local.working-directory`. For trx projects the parameters are `project.py local <name>`.
- It then appends **argv[n] = entity value** and **argv[n+1] = properties**, encoded as `k=v#k2=v2`, with `\#`, `\=` and `\\` as escapes.
- The transform prints the same response XML on **stdout** and uses no stdin.
- The input type arrives as `local.Unknown`.
- trx states "Settings are not supported with local transforms", so local transforms can't receive API keys through the protocol.
- **Observed bug:** an *empty* properties argument crashes trx (`''.split('=')` unpacks into two names). Our encoder omits the argument when there are no properties.

### Distribution
`.mtz` (zip) and CSV exports describe servers, transforms (`TransformAdapterV2`), input/output entities and settings for bulk import into the client or a Transform Distribution Server (TDS).

## 3. Graph visualisation (measured)

| Option | Finding |
|---|---|
| Cytoscape.js 3.34 | Has an experimental **WebGL renderer**, a top-level `webgl: true` option (`index.d.ts`, `rendererDefaults` in `cytoscape.esm.mjs`). It rendered 10,000 nodes and 11,999 edges and stayed responsive to zoom and pan in Chrome. |
| Layout cost at 10k nodes (main thread) | Grid 0.35s; fCoSE `quality:'draft'` 4.7s; breadthfirst radial 4.4s; dagre not measured at this size. |
| Hidden costs found | A label-aware `boundingBox()` costs about 0.5s at 10k nodes. Calling it on every minimap redraw, plus fitting twice, added 3s to every layout. Both were removed. |
| PixiJS / React Flow + d3-force | Not evaluated. React Flow renders DOM nodes, which isn't viable at 10k. PixiJS would mean writing selection, hit-testing and layouts yourself. |

## 4. Security requirements found

- **Secrets:** remote transforms receive API keys as `TransformFields` in the request body. TDS-hosted OAuth secrets arrive RSA+AES encrypted (`oauth.py`, AES-ECB).
  - Our port keeps secrets server-side and never returns them to the UI.
  - Each transform receives only the settings it declares.
  - Settings are refused over plain HTTP to a non-loopback host.
- **Local execution:** the client runs whatever command line is configured, and trx adds no sandbox. Our runner adds:
  - an argv list (no shell),
  - a scrubbed environment,
  - no stdin,
  - a timeout and an output cap.
  - It does **not** isolate the filesystem or network; for untrusted transforms, run the backend in a container.
- **Remote endpoints:** trx binds `0.0.0.0` with no auth by default (`handle_run`). Our API binds `127.0.0.1`, rejects non-loopback `Host` headers (DNS rebinding), and sends no CORS headers.
- **XML:** trx uses `minidom`; we use `ElementTree`. Both use expat, which doesn't resolve external entities and, with expat ≥ 2.4, limits entity expansion.

## Open questions

- How the Maltego desktop client merges entities (`strict` vs `loose`) in practice. We merge on (type, value) only.
- The output-entity "matching" behaviour inside the client. This needs the client installed, at which point REA can analyse it.
- SpiderFoot / Amass data models: not analysed.

---

# Maltego Desktop 4.13.0 — install inventory

Scope: read the module list, launcher config and bundled **resources** (entity XML, sample files, machine scripts, UI strings) from `C:\Program Files (x86)\Paterva\Maltego\v4.13.0`. Java bytecode was **not** decompiled. It isn't needed for compatibility, and the licence almost certainly forbids it.

## Architecture (observed from module names and launcher config)
- NetBeans Platform desktop app on Java with G1GC, `-Xmx4000m` heap, and a Darcula look and feel. There are ~390 jars across `maltego`, `maltego-ui`, `maltego-core-platform`, `groovy` and `extra`.
- **Graph engine:** yFiles (`com-yworks-y-files`) handles rendering and layout. Graph store, cache, selection, undo/redo stack, table view and table import/export are separate modules.
- **Large-graph file `.mtgl`:** a ZIP containing `Entities/*.entity` plus per-graph Lucene indexes. They are split into `DataEntities`/`DataLinks` (properties), `LayoutEntities`/`LayoutLinks` (positions) and `StructureEntities`/`StructureLinks` (topology), plus a `Collection` file. So the big-graph store is Lucene-backed.
- **Classic file `.mtgx`:** a ZIP of `Graphs/GraphN.graphml` (the yWorks GraphML schema). Node payload encoding was not observed, since no populated sample was found.
- **Views:** main graph, Ball (bubble) view, Entity List, Mining view, satellite (overview), Detail view and Property view. "Viewlets" (view customisation) restyle nodes by property rules.
- **Search:** Lucene, including lucene-spatial with JTS and spatial4j for geographic queries.
- **Parsing helpers:** libphonenumber (phone normalisation) and an `ipaddress` library (IP and netblock maths).

## Entities (`entities-common`: 107 `.entity` definitions)
- The definitions fall into 12 categories: common, devices, events, groups, infrastructure, locations, people, personal, socialnetwork, tracking, transportation, weapons.
- Each `<MaltegoEntity>` has:
  - an id, display names and a description;
  - a **`<Converter>` regex**, which auto-detects the type of pasted text, ordered by `conversionOrder`;
  - `<Properties value="main-field">` with typed `<Field>`s (nullable/hidden/readonly, sample value);
  - `allowedRoot`, plus icon resources.

## Transforms
- **Protocol v2 and v3** are both present. v3 adds a `TransformPromptHandler` with choice controls (checkboxes and radio buttons), so a v3 transform can **ask the analyst a question mid-run**.
- Supporting modules:
  - discovery: `json-discovery`, `seeds` (TDS)
  - running: `transform-finder`, `transform-manager`, `runregistry`, `runviews`
  - inputs: `tx-inputs-global` (shared/global transform inputs, e.g. API keys)
  - other: `webtx`, tabular transforms (CSV/table-driven)

## Automation: Machines (`automation`, 18 bundled `.machine` scripts)
- Machines are written in a Groovy-like DSL:
  - `machine("id", displayName:…) { start { … } }`
  - `run("transformId", slider:N)`
  - `paths { … }` (parallel branches)
  - `log()`, `status()`, user filters
  - templates for timers (scheduled re-runs, i.e. monitoring) and macros
- Bundled machines include Footprint L1/L2/L3/XXL, Company Stalking, Person→Email, Prune Leaf, URL Info and Twitter monitors.

## Collaboration & platform
- **Collaboration:** sessions over XMPP (smack/jbosh) with a room name, **security key**, user aliases and colours, a chat panel, "Share Current Graph" and "Send Selection".
- **Accounts and cloud:** Keycloak (SSO/OIDC) login, licensing, and `cloud`/`cloud-ui` modules.
- **Other:** crash recovery, a guided tour, analytics via OpenTelemetry, and certificate management.
- **Export:** PDF reports (openpdf), Excel (POI), CSV and images (Batik SVG).

## Pricing page (maltego.com/pricing, fetched 2026-10-12)
| Plan | Price |
|---|---|
| Basic | €0 (200 credits/month) |
| Entry | €3,000/yr (10k credits) |
| Professional | €7,500/yr (20–40k credits, ≤5 users) |
| Enterprise | Custom |

Paid tiers unlock:
- the full desktop app (Community Edition limits it), plus Browser Graph, Search, Monitor, Evidence, Hunchly and Cases
- 100+ "Connectors" (data integrations), billed through **Data Pass credits**
- the Connector Builder (CSV-based below Enterprise)
- Admin and SSO

The client's paywalled value is mostly **data access** and **team/case workflow**.

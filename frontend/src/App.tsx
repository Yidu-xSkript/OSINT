import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api, type Alert, type Graph, type Suggestion } from './api'
import AIPanel from './components/AIPanel'
import CandidatePanel, { type CandStatus, isCandidate } from './components/CandidatePanel'
import ContextMenu, { type MenuItem } from './components/ContextMenu'
import ForensicCanvas from './components/ForensicCanvas'
import GlobeView from './components/GlobeView'
import GraphCanvas, { type ContextTarget, type GraphApi, type LayoutName } from './components/GraphCanvas'
import Inspector from './components/Inspector'
import Palette from './components/Palette'
import SightlinePanel from './components/SightlinePanel'
import TransformWizard from './components/TransformWizard'
import PrivacyPanel from './components/PrivacyPanel'
import { useDialog } from './components/Dialog'
import JobDrawer from './components/JobDrawer'
import ScanPanel from './components/ScanPanel'
import { MACHINES, type Machine } from './machines'
import { detectType, ENTITY_TYPES, type Entity, type EntityType, type Job, type Link, type Transform, type UIMessage } from './types'

type Pos = { x: number; y: number }
const LIMITS = [12, 50, 256, 1000, 10000]
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n))
const lsNum = (k: string, d: number) => { try { const v = localStorage.getItem(k); return v ? +v : d } catch { return d } }
const lsBool = (k: string, d: boolean) => { try { const v = localStorage.getItem(k); return v == null ? d : v === '1' } catch { return d } }
const storedWebgl = () => { try { return localStorage.getItem('osint.webgl') !== '0' } catch { return true } }
const lastGraph = () => { try { return localStorage.getItem('osint.graph') } catch { return null } }

export default function App() {
  const graph = useRef<GraphApi>(null)
  const ents = useRef(new Map<string, Entity>())
  const links = useRef(new Map<string, Link>())
  const [, bump] = useReducer((n: number) => n + 1, 0)
  const [graphs, setGraphs] = useState<Graph[]>([])
  const [gid, setGid] = useState<string | null>(null)
  const gidRef = useRef<string | null>(null)
  gidRef.current = gid
  const [selection, setSelection] = useState<string[]>([])
  const [transforms, setTransforms] = useState<Transform[]>([])
  const [menu, setMenu] = useState<ContextTarget | null>(null)
  const [drop, setDrop] = useState<{ type: EntityType; model: Pos; screen: Pos } | null>(null)
  const [running, setRunning] = useState(0)
  const [layingOut, setLayingOut] = useState(0)
  const [machine, setMachine] = useState<string | null>(null)
  const stopMachine = useRef(false)
  const [log, setLog] = useState<UIMessage[]>([])
  const [wizard, setWizard] = useState<false | 'list' | 'keys'>(false)
  const [ai, setAi] = useState<null | { tab: 'extract' | 'suggest' | 'summary'; seed?: Suggestion[] }>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [privacyOpen, setPrivacyOpen] = useState(false)
  const [scan, setScan] = useState<string | null>(null)
  const { ask, node: dialogNode } = useDialog()
  const [jobs, setJobs] = useState<Job[]>([])
  const jobActions = useRef(new Map<string, { retry?: () => void; cancel?: () => void }>())
  const addJob = (j: Omit<Job, 'id'>, actions: { retry?: () => void; cancel?: () => void } = {}) => {
    const id = crypto.randomUUID()
    jobActions.current.set(id, actions)
    setJobs((xs) => [{ ...j, id }, ...xs].slice(0, 200))
    return id
  }
  const patchJob = (id: string, p: Partial<Job>) => setJobs((xs) => xs.map((j) => (j.id === id ? { ...j, ...p } : j)))
  const [leftW, setLeftW] = useState(() => lsNum('osint.leftW', 200))
  const [rightW, setRightW] = useState(() => lsNum('osint.rightW', 320))
  const [leftOpen, setLeftOpen] = useState(() => lsBool('osint.leftOpen', true))
  const [rightOpen, setRightOpen] = useState(() => lsBool('osint.rightOpen', true))
  useEffect(() => { try { localStorage.setItem('osint.leftW', String(leftW)); localStorage.setItem('osint.rightW', String(rightW)); localStorage.setItem('osint.leftOpen', leftOpen ? '1' : '0'); localStorage.setItem('osint.rightOpen', rightOpen ? '1' : '0') } catch { /**/ } }, [leftW, rightW, leftOpen, rightOpen])
  const startDrag = (which: 'left' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault()
    const move = (ev: MouseEvent) => which === 'left'
      ? setLeftW(clamp(ev.clientX, 150, 560))
      : setRightW(clamp(window.innerWidth - ev.clientX, 180, 640))
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up); document.body.style.userSelect = '' }
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up)
  }
  const [forensic, setForensic] = useState<{ src: string; title: string } | null>(null)
  const [rightTab, setRightTab] = useState<'inspector' | 'candidates'>('inspector')
  const [caseTime, setCaseTime] = useState('')
  const [sightline, setSightline] = useState(false)
  const [globe, setGlobe] = useState<{ url: string; title: string } | null>(null)
  // bundled God's Eye View is served by our own sidecar at /gev (no separate server, keyless esri imagery).
  // Override with the gev.url setting to point at a full GEV dev server (adds its live data layers).
  const gevUrl = useRef(`${window.location.origin}/gev`)
  const [hist, setHist] = useState({ canUndo: false, canRedo: false })
  const [limit, setLimit] = useState(256)
  const [query, setQuery] = useState('')
  const [webgl, setWebgl] = useState(storedWebgl)
  const pendingPos = useRef<Record<string, Pos>>({})
  const posTimer = useRef(0)

  const say = (m: UIMessage) => setLog((l) => [{ at: Date.now(), ...m }, ...l].slice(0, 500))
  const fail = (e: unknown) => say({ type: 'FatalError', text: (e as Error).message })

  const merge = (entities: Entity[], newLinks: Link[]) => {
    entities.forEach((e) => ents.current.set(e.id, e))
    newLinks.forEach((l) => links.current.set(l.id, l))
    graph.current?.add(entities, newLinks)
    bump()
  }

  const refreshHistory = () => gidRef.current && api.history(gidRef.current).then(setHist).catch(() => {})
  const refreshAlerts = () => gidRef.current && api.alerts(gidRef.current).then(setAlerts).catch(() => {})

  const reload = useCallback(async (id: string) => {
    const g = await api.graph(id)
    ents.current = new Map(g.entities.map((e) => [e.id, e]))
    links.current = new Map(g.links.map((l) => [l.id, l]))
    graph.current?.clear()
    graph.current?.add(g.entities, g.links)
    bump()
    if (g.entities.some((e) => !e.position)) layout('force')
    else graph.current?.fit()
    refreshHistory()
    refreshAlerts()
  }, [])

  const layout = (name: LayoutName) => {
    setLayingOut((n) => n + 1)
    graph.current?.layout(name).catch(fail).finally(() => setLayingOut((n) => n - 1))
  }
  const loadTransforms = () => api.transforms().then(setTransforms).catch(fail)
  const loadGraphs = () => api.graphs().then((gs) => { setGraphs(gs); return gs }).catch((e) => (fail(e), [] as Graph[]))

  // pick the initial case
  useEffect(() => {
    api.settings().then((s) => {
      const v = s.find((x) => x.name === 'chrono.datetime')?.value
      if (v) setCaseTime(v.replace(' UTC', '').replace(' ', 'T').slice(0, 16))
      const g = s.find((x) => x.name === 'gev.url')?.value
      if (g) gevUrl.current = g.replace(/\/$/, '')
    }).catch(() => {})
    loadTransforms()
    loadGraphs().then((gs) => {
      if (!gs.length) return
      const want = gs.find((g) => g.id === lastGraph()) ?? gs[0]
      setGid(want.id)
    })
  }, [])

  // load whenever the case or renderer changes
  useEffect(() => {
    if (!gid) return
    try { localStorage.setItem('osint.graph', gid) } catch { /* private mode */ }
    reload(gid).catch(fail)
  }, [gid, webgl])

  // poll alerts for the monitor system
  useEffect(() => {
    const t = setInterval(refreshAlerts, 60_000)
    return () => clearInterval(t)
  }, [])

  const onPositions = useCallback((p: Record<string, Pos>) => {
    Object.assign(pendingPos.current, p)
    clearTimeout(posTimer.current)
    posTimer.current = window.setTimeout(() => {
      const batch = pendingPos.current
      pendingPos.current = {}
      api.positions(batch).catch(fail)
    }, 600)
  }, [])

  const selected = selection.map((id) => ents.current.get(id)).filter(Boolean) as Entity[]

  const run = async (t: Transform, ids: string[], max = limit): Promise<string[]> => {
    const g = gidRef.current
    const targets = ids.filter((id) => ents.current.get(id)?.type === t.inputType)
    if (!g || !targets.length) return []
    setRunning((n) => n + 1)
    const jobId = addJob(
      { label: `${t.name} · ${targets.length} ${t.inputType}`, kind: 'transform', status: 'running', startedAt: Date.now(), entities: 0, links: 0, entityIds: [] },
      { retry: () => { run(t, ids, max) } },
    )
    say({ type: 'Debug', transform: t.name, text: `running on ${targets.length} ${t.inputType}` })
    try {
      const before = ents.current.size
      const r = await api.run(g, t.id, targets, max)
      merge(r.entities, r.links)
      // "Show on God's Eye View" → open the embedded globe on the URL it produced
      if (t.id === 'geo-globe') {
        const src = ents.current.get(targets[0])
        if (src) openGlobe(src) // open the bundled globe centered on the source location
      }
      r.messages.forEach((m) => say({ ...m, transform: t.name }))
      const newN = ents.current.size - before
      say({ type: 'Inform', transform: t.name, text: `${newN} new entities, ${r.links.length} links` })
      const produced = r.entities.map((e) => e.id)
      patchJob(jobId, { status: newN === 0 && r.links.length === 0 ? 'no-results' : 'done', endedAt: Date.now(), entities: newN, links: r.links.length, entityIds: produced })
      refreshHistory()
      return produced
    } catch (e) {
      patchJob(jobId, { status: 'error', endedAt: Date.now(), detail: e instanceof Error ? e.message : String(e) })
      fail(e); return []
    } finally {
      setRunning((n) => n - 1)
    }
  }

  const runMachine = async (m: Machine, startIds: string[]) => {
    stopMachine.current = false
    setMachine(m.name)
    const jobId = addJob(
      { label: `${m.name} · machine (${m.phases.length} phases)`, kind: 'machine', status: 'running', startedAt: Date.now(), entities: 0, links: 0, entityIds: [] },
      { cancel: () => { stopMachine.current = true } },
    )
    const found = new Set(startIds)
    for (const [i, phase] of m.phases.entries()) {
      if (stopMachine.current) break
      say({ type: 'Debug', transform: m.name, text: `phase ${i + 1}/${m.phases.length}: ${phase.status}` })
      const ids = [...found]
      const outs = await Promise.all(phase.steps.map((s) => {
        const t = transforms.find((x) => x.id === s.transform)
        return t ? run(t, ids, s.limit ?? limit) : []
      }))
      outs.flat().forEach((id) => found.add(id))
    }
    const produced = [...found].filter((id) => !startIds.includes(id))
    say({ type: 'Inform', transform: m.name, text: `${stopMachine.current ? 'stopped' : 'finished'}: ${produced.length} entities found` })
    patchJob(jobId, { status: stopMachine.current ? 'cancelled' : 'done', endedAt: Date.now(), entities: produced.length, entityIds: produced })
    setMachine(null)
  }

  const runScan = async (targets: string[], profile: string) => {
    const g = gidRef.current; if (!g) return
    setRunning((n) => n + 1)
    const jobId = addJob(
      { label: `nmap ${profile} · ${targets.join(', ').slice(0, 60)}`, kind: 'transform', status: 'running', startedAt: Date.now(), entities: 0, links: 0, entityIds: [] },
      { retry: () => { runScan(targets, profile) } },
    )
    try {
      const before = ents.current.size
      const r = await api.scan(g, targets, profile, true)
      merge(r.entities, r.links)
      r.messages.forEach((m) => say({ ...m, transform: 'nmap' }))
      const newN = ents.current.size - before
      patchJob(jobId, { status: newN === 0 && r.links.length === 0 ? 'no-results' : 'done', endedAt: Date.now(), entities: newN, links: r.links.length, entityIds: r.entities.map((e) => e.id) })
      refreshHistory()
    } catch (e) {
      patchJob(jobId, { status: 'error', endedAt: Date.now(), detail: e instanceof Error ? e.message : String(e) })
      throw e  // let ScanPanel surface it and stay open for a retry
    } finally {
      setRunning((n) => n - 1)
    }
  }

  const remove = async (ids: string[]) => {
    const g = gidRef.current; if (!g) return
    await api.deleteEntities(g, ids).catch(fail)
    const gone = new Set(ids)
    ids.forEach((id) => ents.current.delete(id))
    for (const [id, l] of links.current) if (gone.has(l.sourceId) || gone.has(l.targetId)) links.current.delete(id)
    graph.current?.remove(ids)
    setSelection([])
    refreshHistory()
  }

  const patch = async (id: string, p: Partial<Entity> & { notes?: string | null }) => {
    try {
      const e = await api.patchEntity(id, p)
      ents.current.set(id, e); graph.current?.updateEntity(e); bump(); refreshHistory()
    } catch (err) { fail(err) }
  }

  // merge property changes (candidate.status / candidate.checklist …) and persist
  const patchProps = (id: string, changed: Record<string, { name: string; value: string; displayName: string }>, remove: string[] = []) => {
    const e = ents.current.get(id); if (!e) return
    const next = { ...e.properties, ...changed }
    for (const k of remove) delete next[k]
    patch(id, { properties: next })
  }
  const candidates = [...ents.current.values()].filter(isCandidate)

  const createAt = async (type: EntityType, value: string, position: Pos) => {
    const g = gidRef.current; if (!g) return
    try {
      const { entity } = await api.createEntity(g, { type, value, position })
      merge([entity], []); graph.current?.select([entity.id]); refreshHistory()
    } catch (e) { fail(e) }
  }

  const addFromPalette = (type: EntityType) => {
    const cy = graph.current?.cy(); if (!cy) return
    if (type === 'Image') return uploadImage()
    const e = cy.extent()
    setDrop({ type, model: { x: (e.x1 + e.x2) / 2, y: (e.y1 + e.y2) / 2 }, screen: { x: cy.width() / 2 - 120, y: cy.height() / 2 } })
  }

  const openImage = (e: Entity) => {
    const iid = e.properties['image.id']?.value
    if (iid) setForensic({ src: `/api/images/${iid}`, title: e.value })
  }

  // lat,lon from a Location's properties (set by ip-geo / To Coordinates), or a "lat,lon" value
  const coordsOf = (e: Entity): string | null => {
    for (const k of ['location.coordinates', 'coordinates', 'gps.coordinate']) {
      const v = e.properties[k]?.value
      if (typeof v === 'string' && /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(v)) return v
    }
    return /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(e.value) ? e.value : null
  }

  const showGlobeAt = (lat: number, lon: number, title: string) => {
    // esri-imagery flies keyless (no Cesium/Google token needed); bundled GEV uses it by default
    const bundled = gevUrl.current.endsWith('/gev')
    const url = `${gevUrl.current}/#${new URLSearchParams({ lat: lat.toFixed(5), lon: lon.toFixed(5), alt: '1200', pitch: '-35', heading: '0', map: bundled ? 'esri-imagery' : 'photoreal' })}`
    showGlobe(url, title)
  }
  const openGlobe = (e: Entity) => {
    const c = coordsOf(e)
    if (!c) { say({ type: 'PartialError', text: `${e.value} has no coordinates — run To Coordinates [Nominatim] first` }); return }
    const [lat, lon] = c.split(',')
    showGlobeAt(+lat, +lon, e.value)
  }

  // In the desktop app: open God's Eye View as a native child window (a top-level navigation, so GEV's
  // X-Frame-Options/CSP don't block it). In the browser: fall back to the in-app iframe panel.
  const showGlobe = async (url: string, title: string) => {
    if ('__TAURI_INTERNALS__' in window) {
      try {
        const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow')
        const existing = await WebviewWindow.getByLabel('globe')
        if (existing) await existing.close()
        const w = new WebviewWindow('globe', { url, title: `God's Eye View — ${title}`, width: 1280, height: 860, center: true })
        w.once('tauri://error', () => setGlobe({ url, title })) // iframe fallback if the window can't open
        return
      } catch { /* fall through to the iframe panel */ }
    }
    setGlobe({ url, title })
  }

  const uploadImage = () => {
    const g = gidRef.current, cy = graph.current?.cy()
    if (!g || !cy) return
    const ext = cy.extent()
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'image/*'
    input.onchange = async () => {
      const f = input.files?.[0]
      if (!f) return
      try {
        const { entity } = await api.uploadImage(g, f, { x: (ext.x1 + ext.x2) / 2, y: (ext.y1 + ext.y2) / 2 })
        merge([entity], [])
        graph.current?.select([entity.id])
        refreshHistory()
        openImage(entity)
      } catch (e) { fail(e) }
    }
    input.click()
  }

  const search = async () => {
    const g = gidRef.current
    if (!g || !query.trim()) return
    const ids = await api.search(g, query).catch((e) => (fail(e), []))
    graph.current?.select(ids, true)
    say({ type: 'Debug', text: `search "${query}": ${ids.length} matches` })
  }

  const doUndo = async (redo = false) => {
    const g = gidRef.current; if (!g) return
    const r = await (redo ? api.redo(g) : api.undo(g)).catch(fail)
    if (r) { setHist({ canUndo: r.canUndo, canRedo: r.canRedo }); if (r.applied) reload(g).catch(fail) }
  }

  // add AI-extracted or pasted entities to the graph, laid out in a grid near the centre
  const addEntities = async (rows: { type: EntityType; value: string }[]) => {
    const g = gidRef.current, cy = graph.current?.cy()
    if (!g || !cy || !rows.length) return
    const take = rows.slice(0, 200)
    const ext = cy.extent(), cols = Math.ceil(Math.sqrt(take.length))
    const cx = (ext.x1 + ext.x2) / 2 - (cols * 90) / 2, cyy = (ext.y1 + ext.y2) / 2 - (cols * 90) / 2
    const made = await Promise.all(take.map((r, i) =>
      api.createEntity(g, { type: r.type, value: r.value, position: { x: cx + (i % cols) * 90, y: cyy + Math.floor(i / cols) * 90 } })
        .then((x) => x.entity).catch((err) => (fail(err), null))))
    const ok = made.filter(Boolean) as Entity[]
    merge(ok, []); graph.current?.select(ok.map((x) => x.id)); refreshHistory()
    const tally: Record<string, number> = {}
    for (const x of ok) tally[x.type] = (tally[x.type] ?? 0) + 1
    say({ type: 'Inform', text: `added ${ok.length} entities (${Object.entries(tally).map(([t, n]) => `${n} ${t}`).join(', ')})` })
    return ok
  }

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)) return
      const lines = [...new Set((e.clipboardData?.getData('text') ?? '').split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean))]
      if (!lines.length) return
      e.preventDefault()
      addEntities(lines.slice(0, 200).map((v) => ({ type: detectType(v), value: v })))
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName, typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)
      if (typing) return
      if (e.key === 'Delete' && selection.length) remove(selection)
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(e.shiftKey) }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); doUndo(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const addMonitor = async (m: Machine, ids: string[]) => {
    const g = gidRef.current; if (!g) return
    const entered = await ask.prompt(`Monitor "${m.name}"`, '360', { message: 'Re-run every how many minutes? (minimum 5)', placeholder: 'minutes' })
    const mins = Number(entered)
    if (!mins || mins < 5) return
    await api.addMonitor(g, m.id, ids, mins).catch(fail)
    say({ type: 'Inform', text: `monitoring: ${m.name} every ${mins} min on ${ids.length} entities` })
  }

  const menuItems = (): MenuItem[] => {
    if (!menu) return []
    if (menu.edgeId) {
      const id = menu.edgeId
      return [{ label: 'Delete link', danger: true, onClick: () => api.deleteLink(id).then(() => { links.current.delete(id); graph.current?.remove([id]); bump(); refreshHistory() }).catch(fail) }]
    }
    const node = ents.current.get(menu.nodeId!); if (!node) return []
    const same = selected.filter((e) => e.type === node.type).map((e) => e.id)
    const ids = same.length ? same : [node.id]
    const ts = transforms.filter((t) => t.inputType === node.type)
    const cy = graph.current?.cy()
    const pick = (dir: 'outgoers' | 'incomers') => () => cy?.$('node:selected')[dir]('node').select()
    const ms = MACHINES.filter((m) => m.inputType === node.type)
    const notCand = ids.filter((id) => !isCandidate(ents.current.get(id)!))
    return [
      ...(node.type === 'Location' && coordsOf(node) ? [{ label: "🌍 Open in God's Eye View", onClick: () => openGlobe(node) }] as MenuItem[] : []),
      ...(node.type === 'URL' && node.value.includes('lat=') ? [{ label: "🌍 Open in God's Eye View", onClick: () => { const p = new URLSearchParams(node.value.split('#')[1] ?? ''); showGlobeAt(+(p.get('lat') ?? 0), +(p.get('lon') ?? 0), 'Location') } }] as MenuItem[] : []),
      { label: '✨ Suggest next steps (AI)', onClick: () => openSuggest(ids) },
      ...(notCand.length ? [{ label: `★ Add to candidate funnel`, onClick: () => { notCand.forEach((id) => patchProps(id, { 'candidate.status': { name: 'candidate.status', value: 'Unreviewed', displayName: 'Candidate Status' } })); setRightTab('candidates') } }] as MenuItem[] : []),
      ...(ms.length ? [{ header: 'Machines' } as MenuItem,
        ...ms.flatMap((m) => [
          { label: `⚙ ${m.name}`, hint: `${m.phases.length} phases`, onClick: () => runMachine(m, ids) },
          { label: `   ⏱ Monitor with ${m.name}`, onClick: () => addMonitor(m, ids) }] as MenuItem[])] : []),
      { header: `${node.type} transforms${ids.length > 1 ? ` (${ids.length} selected)` : ''}` },
      ...(ts.length ? [{ label: '▶ Run all', hint: `${ts.length}`, onClick: () => ts.forEach((t) => run(t, ids)) },
        ...ts.map((t) => ({ label: t.name, hint: t.kind === 'builtin' ? '' : t.kind, onClick: () => run(t, ids) }))] : [{ header: 'none: add one in Transforms' }]),
      'sep',
      { label: 'Select children', onClick: pick('outgoers') },
      { label: 'Select parents', onClick: pick('incomers') },
      { label: 'Select all of this type', onClick: () => cy?.nodes(`[type="${node.type}"]`).select() },
      'sep',
      { label: `Delete ${ids.length > 1 ? `${ids.length} entities` : 'entity'}`, danger: true, onClick: () => remove(ids) },
    ]
  }

  const openSuggest = async (ids: string[]) => {
    const g = gidRef.current; if (!g) return
    setAi({ tab: 'suggest' })
    try {
      const r = await api.aiSuggest(g, ids)
      setAi({ tab: 'suggest', seed: r.suggestions })
    } catch (e) { fail(e); setAi({ tab: 'suggest', seed: [] }) }
  }

  const runSuggestion = (s: Suggestion) => {
    if (s.machineId) { const m = MACHINES.find((x) => x.id === s.machineId); if (m && s.entityId) runMachine(m, [s.entityId]) }
    else if (s.transformId) { const t = transforms.find((x) => x.id === s.transformId); if (t && s.entityId) run(t, [s.entityId]) }
    if (s.entityId) graph.current?.select([s.entityId], true)
  }

  const selSet = new Set(selection)
  const touching = [...links.current.values()].filter((l) => selSet.has(l.sourceId) || selSet.has(l.targetId))
  const layoutBtn = (name: LayoutName, label: string) => <button className="btn" onClick={() => layout(name)}>{label}</button>
  const unseen = alerts.filter((a) => !a.seen).length

  const importFile = async (accept: string, kind: 'json' | 'mtgx') => {
    const g = gidRef.current; if (!g) return
    const input = document.createElement('input')
    input.type = 'file'; input.accept = accept
    input.onchange = async () => {
      const f = input.files?.[0]; if (!f) return
      try {
        const r = kind === 'json'
          ? await api.importGraph(g, JSON.parse(await f.text()))
          : await api.importFile(`/api/graphs/${g}/import/maltego`, f)
        say({ type: 'Inform', text: `imported ${r.imported} entities from ${f.name}` })
        reload(g)
      } catch (err) { fail(err) }
    }
    input.click()
  }

  const newCase = async () => {
    const name = await ask.prompt('New case', `Investigation ${graphs.length + 1}`, { placeholder: 'Case name' })
    if (!name) return
    const { id } = await api.createGraph(name).catch((e) => (fail(e), { id: '' }))
    if (id) { await loadGraphs(); setGid(id) }
  }

  const loadSample = async () => {
    const { id } = await api.sampleCase().catch((e) => (fail(e), { id: '' }))
    if (id) { await loadGraphs(); setGid(id) }
  }

  return (
    <div className="grid h-full grid-rows-[auto_1fr_150px]"
      style={{ gridTemplateColumns: `${leftOpen ? leftW : 0}px 1fr ${rightOpen ? rightW : 0}px` }}>
      <header className="col-span-3 flex flex-wrap items-center gap-1.5 border-b border-zinc-800 bg-zinc-900 px-3 py-1.5">
        <b className="mr-1">OSINT Graph</b>
        <select className="field !w-auto max-w-44" value={gid ?? ''} onChange={(e) => setGid(e.target.value)} title="Case">
          {graphs.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.entities})</option>)}
        </select>
        <button className="btn" title="New case" aria-label="New case" onClick={newCase}>+</button>
        <button className="btn" title="Rename case" aria-label="Rename case" onClick={async () => {
          if (!gid) return
          const name = await ask.prompt('Rename case', graphs.find((g) => g.id === gid)?.name ?? '', { placeholder: 'Case name' })
          if (name) { await api.renameGraph(gid, name).catch(fail); loadGraphs() }
        }}>✎</button>
        <button className="btn" title="Delete case" aria-label="Delete case" onClick={async () => {
          if (!gid || graphs.length < 2) return
          if (!await ask.confirm('Delete this entire case?', { message: 'All its entities, links and evidence are removed. This cannot be undone.', confirmLabel: 'Delete case', danger: true })) return
          await api.deleteGraph(gid).catch(fail)
          const gs = await loadGraphs(); setGid(gs[0]?.id ?? null)
        }}>🗑</button>

        <span className="mx-2 text-zinc-700">|</span>
        <button className="btn" disabled={!hist.canUndo} onClick={() => doUndo(false)} title="Undo (Ctrl+Z)" aria-label="Undo">↶</button>
        <button className="btn" disabled={!hist.canRedo} onClick={() => doUndo(true)} title="Redo (Ctrl+Y)" aria-label="Redo">↷</button>

        {layoutBtn('force', 'Force')}{layoutBtn('hierarchical', 'Tree')}{layoutBtn('radial', 'Radial')}{layoutBtn('grid', 'Grid')}
        <input className="field !w-40" placeholder="Search (FTS)… ⏎" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} />
        <label className="text-xs text-zinc-400" title="Max results per input entity (Maltego's slider)">
          Limit <select className="field !w-auto" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>{LIMITS.map((l) => <option key={l}>{l}</option>)}</select>
        </label>
        <button className="btn" onClick={() => setAi({ tab: 'extract' })} title="AI">✨ AI</button>
        <button className="btn" onClick={() => setSightline(true)} title="Sightline resection (chronolocation triangulation)">⌖ Sightline</button>
        <button className="btn" onClick={() => setWizard('list')}>Transforms…</button>

        <span className="ml-auto text-xs text-zinc-500">
          {running > 0 && <span className="mr-2 text-sky-400">⟳ {running} running</span>}
          {machine && <button className="mr-2 text-amber-400 hover:text-rose-400" title="Stop after current phase" onClick={() => { stopMachine.current = true }}>⚙ {machine} ■</button>}
          {layingOut > 0 && <button className="mr-2 text-sky-400 hover:text-rose-400" title="Cancel layout" onClick={() => graph.current?.cancelLayout()}>⟳ layout… ✕</button>}
          {ents.current.size} entities · {links.current.size} links
        </span>
        <button className="btn relative" title="Monitor alerts" aria-label="Monitor alerts" onClick={() => { if (unseen && gid) api.alertsSeen(gid).then(() => { refreshAlerts() }).catch(() => {}); setAlertsOpen((o) => !o) }}>
          🔔{unseen > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-rose-500 px-1 text-[10px] text-white">{unseen}</span>}
        </button>
        {gid && <>
          <a className="btn text-amber-400" href={`/api/graphs/${gid}/report?format=html`} target="_blank" rel="noreferrer" title="Open a printable case report (Print → Save as PDF)">Report</a>
          <a className="btn" href={`/api/graphs/${gid}/report?format=md`} title="Download the report as Markdown">.md</a>
          <a className="btn" href={`/api/graphs/${gid}/export?format=json`}>JSON</a>
          <a className="btn" href={`/api/graphs/${gid}/export?format=graphml`}>GraphML</a>
        </>}
        <button className="btn" title="Where does this investigation's data go?" onClick={() => setPrivacyOpen((o) => !o)}>🛡 Privacy</button>
        <button className="btn" onClick={() => importFile('.json', 'json')}>Import</button>
        <button className="btn" onClick={() => importFile('.mtgx,.graphml', 'mtgx')} title="Import a Maltego .mtgx or GraphML graph">.mtgx</button>
        <button className="btn" onClick={async () => { if (gid && await ask.confirm('Delete every entity in this case?', { message: 'Clears the whole graph for this case.', confirmLabel: 'Clear graph', danger: true })) api.clear(gid).then(() => reload(gid)).catch(fail) }}>Clear</button>
        <label className="flex items-center gap-1 text-xs text-zinc-400" title="Experimental Cytoscape WebGL renderer: much faster for 10k+ elements">
          <input type="checkbox" checked={webgl} onChange={(e) => { try { localStorage.setItem('osint.webgl', e.target.checked ? '1' : '0') } catch { /**/ } setWebgl(e.target.checked) }} />WebGL
        </label>
      </header>

      <aside className="col-start-1 row-start-2 overflow-auto border-r border-zinc-800 bg-zinc-900 p-3" style={{ display: leftOpen ? undefined : 'none' }}>
        <div className="h !mt-0">Case timestamp (UTC)</div>
        <input type="datetime-local" className="field" value={caseTime}
          onChange={(e) => { setCaseTime(e.target.value); api.putSetting('chrono.datetime', e.target.value, false).catch(fail) }} />
        <p className="mb-1 mt-1 text-[11px] text-zinc-500">The case's known time. Drives <b>To Sun Position</b> & <b>Weather</b> (chronolocation).</p>
        <Palette onAdd={addFromPalette} />
      </aside>

      <main className="col-start-2 row-start-2 relative min-h-0 min-w-0 overflow-hidden" onContextMenu={(e) => e.preventDefault()}>
        <GraphCanvas key={String(webgl)} apiRef={graph} webgl={webgl} onSelect={setSelection} onContext={setMenu}
          onDropType={(type, model, screen) => setDrop({ type, model, screen })} onPositions={onPositions} />
        {/* pane resize + collapse: bars sit on main's edges, which are the pane boundaries */}
        {leftOpen && <div onMouseDown={startDrag('left')} title="Drag to resize" className="absolute left-0 top-0 bottom-0 z-20 w-1.5 -ml-0.5 cursor-col-resize hover:bg-sky-600/50" />}
        {rightOpen && <div onMouseDown={startDrag('right')} title="Drag to resize" className="absolute right-0 top-0 bottom-0 z-20 w-1.5 -mr-0.5 cursor-col-resize hover:bg-sky-600/50" />}
        <button className="absolute left-1 top-1 z-30 rounded border border-zinc-700 bg-zinc-900/90 px-1 text-xs text-zinc-400 hover:text-white"
          title={leftOpen ? 'Collapse palette' : 'Show palette'} aria-label={leftOpen ? 'Collapse palette' : 'Show palette'}
          onMouseDown={(e) => e.stopPropagation()} onClick={() => setLeftOpen((o) => !o)}>{leftOpen ? '‹' : '›'}</button>
        <button className="absolute right-1 top-1 z-30 rounded border border-zinc-700 bg-zinc-900/90 px-1 text-xs text-zinc-400 hover:text-white"
          title={rightOpen ? 'Collapse inspector' : 'Show inspector'} aria-label={rightOpen ? 'Collapse inspector' : 'Show inspector'}
          onMouseDown={(e) => e.stopPropagation()} onClick={() => setRightOpen((o) => !o)}>{rightOpen ? '›' : '‹'}</button>
        {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems()} onClose={() => setMenu(null)} />}
        {drop && (
          <div className="absolute z-20 flex w-60 items-center gap-1.5 rounded border border-sky-600 bg-zinc-900 p-1.5 shadow-xl" style={{ left: drop.screen.x, top: drop.screen.y }}>
            <img src={ENTITY_TYPES[drop.type].icon} className="h-5 w-5" alt="" />
            <input autoFocus className="field" placeholder={`${drop.type}, e.g. ${ENTITY_TYPES[drop.type].example}`}
              onKeyDown={(e) => {
                const v = (e.target as HTMLInputElement).value.trim()
                if (e.key === 'Escape') setDrop(null)
                if (e.key === 'Enter' && v) { createAt(drop.type, v, drop.model); setDrop(null) }
              }} onBlur={() => setDrop(null)} />
          </div>
        )}
        {ents.current.size === 0 && !drop && (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div className="pointer-events-auto max-w-md rounded-lg border border-zinc-800 bg-zinc-900/90 p-5 text-sm text-zinc-300 shadow-xl">
              <div className="mb-2 text-base font-semibold text-amber-400">Start an investigation</div>
              <ol className="mb-3 list-decimal space-y-1 pl-5 text-zinc-400">
                <li>Add a lead — drag an entity from the palette, or paste an email, domain, IP, URL or phone number onto the canvas.</li>
                <li>Select it, then run a transform from the right-hand panel to pull related data.</li>
                <li>Open a node's <b>Evidence</b>, or the <b>Report</b>, to see each finding's source and provenance.</li>
              </ol>
              <div className="mb-3 text-xs text-zinc-500">
                Keyless transforms (DNS, crt.sh, RDAP, libphonenumber, Sun position, geocoding) work with no setup. Others are
                marked <span className="text-amber-400">· needs key</span> until you add an API key.
              </div>
              <div className="flex gap-2">
                <button className="btn text-amber-400" onClick={loadSample}>Load sample case</button>
                <button className="btn" onClick={() => setWizard('keys')}>Add API keys</button>
              </div>
            </div>
          </div>
        )}
        {alertsOpen && <AlertsPanel alerts={alerts} byId={(id) => ents.current.get(id)}
          onSelect={(ids) => graph.current?.select(ids, true)} onClose={() => setAlertsOpen(false)} />}
        {privacyOpen && <PrivacyPanel transforms={transforms} onClose={() => setPrivacyOpen(false)} />}
      </main>

      <aside className="col-start-3 row-start-2 overflow-auto border-l border-zinc-800 bg-zinc-900 p-3" style={{ display: rightOpen ? undefined : 'none' }}>
        <div className="mb-2 flex gap-1">
          <button className={`rounded px-2 py-0.5 text-xs ${rightTab === 'inspector' ? 'bg-sky-800 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-white'}`} onClick={() => setRightTab('inspector')}>Inspector</button>
          <button className={`rounded px-2 py-0.5 text-xs ${rightTab === 'candidates' ? 'bg-sky-800 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-white'}`} onClick={() => setRightTab('candidates')}>
            Candidates{candidates.length > 0 && <span className="ml-1 rounded-full bg-amber-500 px-1 text-[10px] text-black">{candidates.length}</span>}
          </button>
        </div>
        {rightTab === 'inspector' ? (
          <Inspector selection={selected} links={touching} byId={(id) => ents.current.get(id)}
            transforms={selected.length && new Set(selected.map((e) => e.type)).size === 1 ? transforms.filter((t) => t.inputType === selected[0].type) : []}
            busy={false} onPatch={patch} onRun={(t) => run(t, selection)} onSelect={(ids) => graph.current?.select(ids, true)}
            onDelete={remove} onSuggest={() => openSuggest(selection)} onOpenImage={openImage}
            onConfigure={() => setWizard('keys')}
            onScan={(target) => setScan(target)}
            onLink={(a, b, label) => gid && api.createLink(gid, { sourceId: a, targetId: b, label }).then((l) => { merge([], [l]); refreshHistory() }).catch(fail)} />
        ) : (
          <CandidatePanel candidates={candidates}
            onSelect={(ids) => graph.current?.select(ids, true)}
            onSetStatus={(id, s: CandStatus) => patchProps(id, { 'candidate.status': { name: 'candidate.status', value: s, displayName: 'Candidate Status' } })}
            onSetChecklist={(id, list) => patchProps(id, { 'candidate.checklist': { name: 'candidate.checklist', value: JSON.stringify(list), displayName: 'Checklist' } })}
            onRemove={(id) => patchProps(id, {}, ['candidate.status', 'candidate.checklist'])} />
        )}
      </aside>

      <footer className="col-span-3 min-h-0 border-t border-zinc-800 bg-zinc-950 px-3 py-1.5">
        <JobDrawer jobs={jobs} log={log}
          canRetry={(j) => !!jobActions.current.get(j.id)?.retry}
          onShow={(ids) => graph.current?.select(ids.filter((id) => ents.current.get(id)), true)}
          onRetry={(j) => jobActions.current.get(j.id)?.retry?.()}
          onCancel={(j) => jobActions.current.get(j.id)?.cancel?.()}
          onClear={() => setJobs([])}
          onClearLog={() => setLog([])} />
      </footer>

      {wizard && <TransformWizard transforms={transforms} initialTab={wizard} onChanged={loadTransforms} onClose={() => setWizard(false)} />}
      {ai && gid && <AIPanel gid={gid} tab={ai.tab} seed={ai.seed} onAdd={addEntities} onRun={runSuggestion}
        onFail={fail} onClose={() => setAi(null)} />}
      {forensic && <ForensicCanvas src={forensic.src} title={forensic.title} onClose={() => setForensic(null)} />}
      {globe && <GlobeView url={globe.url} title={globe.title} onClose={() => setGlobe(null)} />}
      {sightline && (
        <SightlinePanel
          locations={[...ents.current.values()].filter((e) => e.type === 'Location')}
          onApply={(id, props) => patchProps(id, Object.fromEntries(Object.entries(props).map(([k, v]) => [k, { name: k, value: v, displayName: k.replace('sightline.', 'Sightline ') }])))}
          onShowGlobe={showGlobeAt} onFail={fail} onClose={() => setSightline(false)} />
      )}
      {scan !== null && <ScanPanel seed={scan} onRun={runScan} onFail={fail} onClose={() => setScan(null)} />}
      {dialogNode}
    </div>
  )
}

function AlertsPanel({ alerts, byId, onSelect, onClose }: {
  alerts: Alert[]; byId: (id: string) => Entity | undefined
  onSelect: (ids: string[]) => void; onClose: () => void
}) {
  return (
    <div className="absolute right-3 top-3 z-20 max-h-[60vh] w-80 overflow-auto rounded border border-zinc-700 bg-zinc-900 p-2 shadow-xl">
      <div className="mb-1 flex justify-between text-xs text-zinc-500"><span>Monitor alerts</span><button onClick={onClose} className="hover:text-white">✕</button></div>
      {alerts.length === 0 && <p className="p-2 text-xs text-zinc-500">No alerts. Right-click an entity → Monitor to watch for changes.</p>}
      {alerts.map((a) => (
        <button key={a.id} className={`block w-full rounded px-2 py-1 text-left text-xs hover:bg-zinc-800 ${a.seen ? 'text-zinc-400' : 'text-amber-300'}`}
          onClick={() => onSelect(a.entity_ids.filter((id) => byId(id)))}>
          <span className="text-zinc-600">{new Date(a.created_at).toLocaleString()}</span><br />{a.text}
        </button>
      ))}
    </div>
  )
}

import type { Entity, EntityType, Link, Setting, Tool, Transform, UIMessage } from './types'

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await r.json().catch(() => null)
  if (!r.ok) {
    const d = data?.detail
    throw new Error(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : r.statusText)
  }
  return data as T
}

export interface Graph {
  id: string
  name: string
  created_at: number
  entities: number
}
export interface EvidenceRec {
  id: string
  transform: string | null
  url: string | null
  fetchedAt: number
  status: number | null
  sha256: string
  size: number
}
export interface Monitor {
  id: string
  graph_id: string
  machine_id: string
  entity_ids: string[]
  interval_min: number
  enabled: number
  last_run: number | null
  next_run: number
}
export interface Alert {
  id: string
  monitor_id: string | null
  created_at: number
  text: string
  entity_ids: string[]
  seen: number
}
export interface Suggestion {
  value: string | null
  type: EntityType | null
  entityId: string | null
  suggestion: string
  transformId: string | null
  machineId: string | null
  reason: string
}

export interface LatLonH { lat: number; lon: number; height?: number | null }
export interface SightlineResult {
  facing_azimuth: number; facing_compass: string; collinearity_error_deg: number
  distance_to_near_m: number; distance_to_far_m: number
  bearing_to_near: number; bearing_to_far: number
  camera_height_m: number | null; estimated_floor: number | null
}

const g = (gid: string) => `/api/graphs/${gid}`

export const api = {
  health: () => call<{ ok: boolean }>('GET', '/api/health'),

  // cases / graphs
  graphs: () => call<Graph[]>('GET', '/api/graphs'),
  createGraph: (name: string) => call<{ id: string }>('POST', '/api/graphs', { name }),
  sampleCase: () => call<{ id: string }>('POST', '/api/graphs/sample'),
  renameGraph: (gid: string, name: string) => call('PATCH', g(gid), { name }),
  deleteGraph: (gid: string) => call('DELETE', g(gid)),

  graph: (gid: string) => call<{ entities: Entity[]; links: Link[] }>('GET', `${g(gid)}/graph`),
  createEntity: (gid: string, e: { type: EntityType; value: string; position?: { x: number; y: number } }) =>
    call<{ entity: Entity; created: boolean }>('POST', `${g(gid)}/entities`, e),
  patchEntity: (id: string, patch: Partial<Entity> & { notes?: string | null }) =>
    call<Entity>('PATCH', `/api/entities/${id}`, patch),
  deleteEntities: (gid: string, ids: string[]) => call('POST', `${g(gid)}/entities/delete`, { ids }),
  positions: (p: Record<string, { x: number; y: number }>) => call('PUT', '/api/positions', p),
  createLink: (gid: string, l: { sourceId: string; targetId: string; label: string }) =>
    call<Link>('POST', `${g(gid)}/links`, l),
  deleteLink: (id: string) => call('DELETE', `/api/links/${id}`),
  search: (gid: string, q: string) => call<string[]>('GET', `${g(gid)}/search?q=${encodeURIComponent(q)}`),
  clear: (gid: string) => call('POST', `${g(gid)}/clear`),
  importGraph: (gid: string, data: unknown) => call<{ imported: number }>('POST', `${g(gid)}/import`, data),

  undo: (gid: string) => call<{ applied: boolean; canUndo: boolean; canRedo: boolean }>('POST', `${g(gid)}/undo`),
  redo: (gid: string) => call<{ applied: boolean; canUndo: boolean; canRedo: boolean }>('POST', `${g(gid)}/redo`),
  history: (gid: string) => call<{ canUndo: boolean; canRedo: boolean }>('GET', `${g(gid)}/history`),

  transforms: () => call<Transform[]>('GET', '/api/transforms'),
  tools: () => call<Tool[]>('GET', '/api/tools'),
  scanProfiles: () => call<{ id: string; label: string; args: string[] }[]>('GET', '/api/scan/profiles'),
  scan: (gid: string, targets: string[], profile: string, authorized: boolean) =>
    call<{ entities: Entity[]; links: Link[]; messages: UIMessage[] }>('POST', `${g(gid)}/scan`, { targets, profile, authorized }),
  addTransform: (t: Partial<Transform>) => call<Transform>('POST', '/api/transforms', t),
  deleteTransform: (id: string) => call('DELETE', `/api/transforms/${id}`),
  run: (gid: string, id: string, entityIds: string[], limit: number) =>
    call<{ entities: Entity[]; links: Link[]; messages: UIMessage[] }>('POST', `${g(gid)}/transforms/${id}/run`, {
      entityIds,
      limit,
    }),

  evidence: (eid: string) => call<EvidenceRec[]>('GET', `/api/entities/${eid}/evidence`),

  monitors: (gid: string) => call<Monitor[]>('GET', `${g(gid)}/monitors`),
  addMonitor: (gid: string, machineId: string, entityIds: string[], intervalMin: number) =>
    call<{ id: string }>('POST', `${g(gid)}/monitors`, { machineId, entityIds, intervalMin }),
  patchMonitor: (id: string, p: { enabled?: boolean; intervalMin?: number }) => call('PATCH', `/api/monitors/${id}`, p),
  deleteMonitor: (id: string) => call('DELETE', `/api/monitors/${id}`),
  alerts: (gid: string) => call<Alert[]>('GET', `${g(gid)}/alerts`),
  alertsSeen: (gid: string) => call('POST', `${g(gid)}/alerts/seen`),

  aiExtract: (text: string) => call<{ entities: { type: EntityType; value: string; label?: string }[] }>(
    'POST', '/api/ai/extract', { text }),
  aiSuggest: (gid: string, ids: string[]) => call<{ suggestions: Suggestion[] }>('POST', `${g(gid)}/ai/suggest`, { ids }),
  aiSummary: (gid: string) => call<{ summary: string }>('POST', `${g(gid)}/ai/summary`, {}),

  sightline: (far: LatLonH, near: LatLonH, camera: LatLonH) =>
    call<SightlineResult>('POST', '/api/sightline', { far, near, camera }),

  settings: () => call<Setting[]>('GET', '/api/settings'),
  putSetting: (name: string, value: string, secret: boolean) =>
    call('PUT', `/api/settings/${encodeURIComponent(name)}`, { value, secret }),
  deleteSetting: (name: string) => call('DELETE', `/api/settings/${encodeURIComponent(name)}`),

  uploadImage: async (gid: string, file: File, pos?: { x: number; y: number }) => {
    const fd = new FormData()
    fd.append('file', file)
    const qs = pos ? `?position_x=${pos.x}&position_y=${pos.y}` : ''
    const r = await fetch(`/api/graphs/${gid}/images${qs}`, { method: 'POST', body: fd })
    const data = await r.json().catch(() => null)
    if (!r.ok) throw new Error(data?.detail ?? r.statusText)
    return data as { entity: Entity; imageId: string }
  },

  importFile: async (path: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch(path, { method: 'POST', body: fd })
    const data = await r.json().catch(() => null)
    if (!r.ok) throw new Error(data?.detail ?? r.statusText)
    return data
  },
}

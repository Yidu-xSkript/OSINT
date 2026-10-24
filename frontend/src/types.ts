export interface EntityProperty {
  name: string
  value: string | number | boolean
  displayName: string
  isReadOnly?: boolean
}

// The spec's canonical union, plus Domain and IPAddress, which the DNS/IP pivots need.
export type EntityType =
  | 'Phrase'
  | 'Person'
  | 'Website'
  | 'URL'
  | 'EmailAddress'
  | 'PhoneNumber'
  | 'Location'
  | 'Company'
  | 'Affiliation'
  | 'Snapshot'
  | 'Domain'
  | 'IPAddress'
  | 'Image'

export interface Entity {
  id: string
  type: EntityType
  value: string
  label?: string | null
  icon?: string | null
  properties: Record<string, EntityProperty>
  metadata: {
    createdAt: number
    discoveredByTransform?: string | null
    notes?: string | null
  }
  position?: { x: number; y: number } | null
}

export type Classification = 'observed' | 'source-asserted' | 'derived' | 'hypothesis'

export interface Link {
  id: string
  sourceId: string
  targetId: string
  label: string // E.g., "Found On Page", "WHOIS Registrant", "Mutual Following"
  direction: 'source-to-target' | 'bidirectional'
  weight?: number | null
  // Provenance (null on analyst-drawn links): where this relationship came from and how to read it.
  transform?: string | null
  provider?: string | null
  classification?: Classification | null
  evidenceId?: string | null
  createdAt?: number | null
}

export interface Transform {
  id: string
  name: string
  kind: 'builtin' | 'local' | 'remote'
  inputType: EntityType
  description?: string
  settings: string[]
  credentialSettings?: string[]  // the settings that are API keys/tokens (gate the transform)
  missingSettings?: string[]     // credential settings not yet configured -> "needs setup"
  linkLabel?: string | null
  command?: string
  args?: string[]
  workingDir?: string | null
  url?: string
  timeout?: number
}

export interface UIMessage {
  entity?: string
  type: string
  text: string
  at?: number
  transform?: string
}

export interface Tool {
  id: string
  label: string
  kind: 'native' | 'external'
  state: 'built-in' | 'available' | 'needs-setup' | 'unsupported-version' | 'error'
  version: string | null
  transforms: string[]
  scoped: boolean
  detail: string
  install: string | null
}

export type JobStatus = 'running' | 'done' | 'no-results' | 'error' | 'cancelled'
export interface Job {
  id: string
  label: string          // what ran, e.g. "To Subdomains [crt.sh] · 3 Domain"
  kind: 'transform' | 'machine'
  status: JobStatus
  startedAt: number
  endedAt?: number
  entities: number       // entities produced
  links: number          // links produced
  entityIds: string[]    // produced entities, so a job's graph changes can be shown
  detail?: string        // error text / summary
}

export interface Setting {
  name: string
  secret: boolean
  value: string | null
}

const icon = (color: string, glyph: string) =>
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="31" fill="${color}"/>` +
      `<text x="32" y="34" font-family="Arial,sans-serif" font-size="${glyph.length > 2 ? 17 : 24}" font-weight="700" ` +
      `fill="#0b0d10" text-anchor="middle" dominant-baseline="middle">${glyph}</text></svg>`,
  )

const T = (color: string, glyph: string, example: string) => ({ color, glyph, example, icon: icon(color, glyph) })

export const ENTITY_TYPES: Record<EntityType, ReturnType<typeof T>> = {
  Domain: T('#4f8cff', 'D', 'example.com'),
  IPAddress: T('#f2a33a', 'IP', '8.8.8.8'),
  Website: T('#38bdf8', 'W', 'www.example.com'),
  URL: T('#38c172', 'URL', 'https://example.com/'),
  EmailAddress: T('#e3577a', '@', 'info@example.com'),
  PhoneNumber: T('#f472b6', '#', '+1 555 0100'),
  Person: T('#f5d547', 'P', 'Jane Doe'),
  Company: T('#2ec4c6', 'Co', 'Acme Inc.'),
  Affiliation: T('#a970ff', 'Af', 'github:octocat'),
  Location: T('#ff7b54', 'L', 'Berlin, DE'),
  Phrase: T('#c9b18a', 'Aa', 'octocat'),
  Snapshot: T('#9aa3b0', 'S', 'https://example.com/ @ now'),
  Image: T('#22d3ee', 'Img', 'evidence.jpg'),
}

// Paste-to-entity, like Maltego's per-entity <Converter> regexes: checked in order, most specific first.
const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/
const IPV6 = /^(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}$|^(?=.*::)[0-9a-f:]{2,39}$/i
const DETECT: [EntityType, (v: string) => boolean][] = [
  ['URL', (v) => /^https?:\/\/\S+$/i.test(v)],
  ['EmailAddress', (v) => /^[\w.+-]+@[\w-]+(\.[\w-]+)*\.[a-z]{2,}$/i.test(v)],
  ['IPAddress', (v) => IPV4.test(v) || IPV6.test(v)],
  ['PhoneNumber', (v) => /^\+?[\d\s().-]{7,20}$/.test(v) && v.replace(/\D/g, '').length >= 9], // 9+ digits: not a date
  ['Domain', (v) => /^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(v)],
]

export const detectType = (value: string): EntityType => DETECT.find(([, test]) => test(value.trim()))?.[0] ?? 'Phrase'

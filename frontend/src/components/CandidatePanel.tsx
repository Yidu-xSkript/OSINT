import { useState } from 'react'
import { ENTITY_TYPES, type Entity } from '../types'

export const CAND_STATUSES = ['Unreviewed', 'Promising', 'Matched', 'Ruled Out'] as const
export type CandStatus = (typeof CAND_STATUSES)[number]
const STATUS_COLOR: Record<CandStatus, string> = {
  Unreviewed: '#9aa3b0', Promising: '#f0a63c', Matched: '#38c172', 'Ruled Out': '#e3577a',
}
// Common architectural checks from the ChronoSight decomposition workflow — one-tap to add.
const PRESET_CHECKS = ['Ceiling match', 'Screen placement', 'Lighting / neon', 'Street furniture', 'Exterior facade', 'Floor / table']

type Check = { label: string; checked: boolean }
export const statusOf = (e: Entity): CandStatus => (e.properties['candidate.status']?.value as CandStatus) || 'Unreviewed'
export const isCandidate = (e: Entity) => 'candidate.status' in e.properties
const checklistOf = (e: Entity): Check[] => {
  try { return JSON.parse(String(e.properties['candidate.checklist']?.value || '[]')) } catch { return [] }
}
const prop = (e: Entity, k: string) => (e.properties[k]?.value ? String(e.properties[k].value) : '')

interface Props {
  candidates: Entity[]
  onSelect(ids: string[]): void
  onSetStatus(id: string, status: CandStatus): void
  onSetChecklist(id: string, list: Check[]): void
  onRemove(id: string): void
}

export default function CandidatePanel({ candidates, onSelect, onSetStatus, onSetChecklist, onRemove }: Props) {
  const [filter, setFilter] = useState<CandStatus | 'All'>('All')
  const counts = (s: CandStatus) => candidates.filter((c) => statusOf(c) === s).length
  const shown = candidates.filter((c) => filter === 'All' || statusOf(c) === filter)

  if (!candidates.length)
    return (
      <p className="text-zinc-500">
        No candidates yet. Run <b>To Nearby Venues [OSM]</b> on a Location, or right-click any entity → <b>★ Add to candidate funnel</b>.
      </p>
    )

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1">
        {(['All', ...CAND_STATUSES] as const).map((s) => (
          <button key={s} onClick={() => setFilter(s)}
            className={`rounded px-2 py-0.5 text-xs ${filter === s ? 'bg-sky-800 text-white' : 'bg-zinc-800 text-zinc-400 hover:text-white'}`}>
            {s === 'All' ? `All ${candidates.length}` : `${s} ${counts(s)}`}
          </button>
        ))}
      </div>

      {shown.map((c) => {
        const st = statusOf(c)
        const list = checklistOf(c)
        const done = list.filter((x) => x.checked).length
        const coords = prop(c, 'coordinates') || prop(c, 'location.coordinates')
        const website = prop(c, 'website')
        const toggle = (i: number) => onSetChecklist(c.id, list.map((x, j) => (j === i ? { ...x, checked: !x.checked } : x)))
        const add = (label: string) => { if (label && !list.some((x) => x.label === label)) onSetChecklist(c.id, [...list, { label, checked: false }]) }
        return (
          <div key={c.id} className="mb-2 rounded border border-zinc-800 p-2" style={{ borderLeft: `3px solid ${STATUS_COLOR[st]}` }}>
            <div className="flex items-start gap-2">
              <img src={ENTITY_TYPES[c.type].icon} className="mt-0.5 h-4 w-4" alt="" />
              <div className="min-w-0 flex-1">
                <button className="block truncate text-left font-medium hover:text-sky-400" onClick={() => onSelect([c.id])} title={c.value}>{c.value}</button>
                <div className="truncate text-xs text-zinc-500">{[prop(c, 'category'), prop(c, 'address')].filter(Boolean).join(' · ')}</div>
              </div>
              <button className="text-zinc-600 hover:text-rose-400" title="Remove from funnel" onClick={() => onRemove(c.id)}>✕</button>
            </div>

            <div className="mt-1.5 flex flex-wrap gap-1">
              {CAND_STATUSES.map((s) => (
                <button key={s} onClick={() => onSetStatus(c.id, s)}
                  className="rounded px-1.5 py-0.5 text-[11px] font-medium"
                  style={st === s ? { background: STATUS_COLOR[s], color: '#111' } : { background: '#26272b', color: '#9aa3b0' }}>
                  {s}
                </button>
              ))}
            </div>

            <div className="mt-1.5 flex flex-wrap gap-2 text-xs">
              {website && <a className="text-sky-400 hover:underline" href={website} target="_blank" rel="noreferrer">website</a>}
              {coords && <a className="text-sky-400 hover:underline" href={`https://www.google.com/maps?q=${encodeURIComponent(coords)}`} target="_blank" rel="noreferrer">map</a>}
              {coords && <a className="text-sky-400 hover:underline" href={`https://www.google.com/maps?q=&layer=c&cbll=${encodeURIComponent(coords)}`} target="_blank" rel="noreferrer">street view</a>}
            </div>

            <div className="mt-1.5 text-[11px] uppercase tracking-wide text-zinc-500">Verification {list.length ? `(${done}/${list.length})` : ''}</div>
            {list.map((x, i) => (
              <label key={i} className="flex items-center gap-1.5 text-xs">
                <input type="checkbox" checked={x.checked} onChange={() => toggle(i)} />
                <span className={x.checked ? 'text-zinc-300 line-through' : ''}>{x.label}</span>
                <button className="ml-auto text-zinc-700 hover:text-rose-400" onClick={() => onSetChecklist(c.id, list.filter((_, j) => j !== i))}>✕</button>
              </label>
            ))}
            <div className="mt-1 flex flex-wrap gap-1">
              {PRESET_CHECKS.filter((p) => !list.some((x) => x.label === p)).map((p) => (
                <button key={p} className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400 hover:text-white" onClick={() => add(p)}>+ {p}</button>
              ))}
            </div>
            <input className="field mt-1 !py-0.5 text-xs" placeholder="add check… ⏎"
              onKeyDown={(e) => { if (e.key === 'Enter') { add((e.target as HTMLInputElement).value.trim()); (e.target as HTMLInputElement).value = '' } }} />
          </div>
        )
      })}
    </div>
  )
}

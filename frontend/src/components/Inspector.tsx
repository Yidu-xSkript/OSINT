import { useEffect, useState } from 'react'
import { api, type EvidenceRec } from '../api'
import { ENTITY_TYPES, type Entity, type EntityProperty, type Link, type Transform } from '../types'

// How to read a relationship. Keep these honest: a drawn line is not the same as a verified fact.
const CLASS_META: Record<string, { label: string; cls: string; hint: string }> = {
  observed: { label: 'Observed', cls: 'bg-green-500/15 text-green-400', hint: 'Directly present in the collected material.' },
  'source-asserted': { label: 'Source-asserted', cls: 'bg-amber-500/15 text-amber-400', hint: "A source claims this; it hasn't been independently verified." },
  derived: { label: 'Derived', cls: 'bg-sky-500/15 text-sky-400', hint: 'Computed from observations by a documented method.' },
  hypothesis: { label: 'Hypothesis', cls: 'bg-rose-500/15 text-rose-400', hint: 'A plausible lead that still needs verification.' },
  manual: { label: 'Analyst-added', cls: 'bg-zinc-600/30 text-zinc-400', hint: 'Drawn by the analyst, not from a transform.' },
}

interface Props {
  selection: Entity[]
  links: Link[] // links touching the selection
  byId: (id: string) => Entity | undefined
  transforms: Transform[]
  busy: boolean
  onPatch(id: string, patch: Partial<Entity> & { notes?: string | null }): Promise<void>
  onRun(t: Transform): void
  onSelect(ids: string[]): void
  onDelete(ids: string[]): void
  onLink(sourceId: string, targetId: string, label: string): void
  onSuggest(): void
  onOpenImage(e: Entity): void
  onConfigure(settings: string[]): void
  onScan(target: string): void
}

function Evidence({ entityId }: { entityId: string }) {
  const [recs, setRecs] = useState<EvidenceRec[] | null>(null)
  useEffect(() => { setRecs(null); api.evidence(entityId).then(setRecs).catch(() => setRecs([])) }, [entityId])
  if (!recs?.length) return null
  return (
    <>
      <div className="h">Evidence ({recs.length})</div>
      {recs.map((r) => (
        <div key={r.id} className="mb-1 text-xs">
          <a className="text-sky-400 hover:underline" href={`/api/evidence/${r.id}`} title={`SHA-256 ${r.sha256}`}>
            {r.transform || 'fetch'} · {r.size.toLocaleString()} B
          </a>
          <div className="truncate text-zinc-500" title={r.url ?? ''}>{r.url}</div>
          <div className="text-zinc-600">{new Date(r.fetchedAt).toLocaleString()} · sha {r.sha256.slice(0, 12)}…</div>
        </div>
      ))}
    </>
  )
}

// Text input that commits on blur / Enter, and resets when the underlying value changes.
function Commit({ value, onCommit, disabled, multiline }: { value: string; onCommit(v: string): void; disabled?: boolean; multiline?: boolean }) {
  const p = {
    defaultValue: value,
    disabled,
    className: 'field',
    onBlur: (e: { target: { value: string } }) => e.target.value !== value && onCommit(e.target.value),
  }
  return multiline ? (
    <textarea key={value} {...p} rows={3} />
  ) : (
    <input key={value} {...p} onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()} />
  )
}

export default function Inspector(p: Props) {
  const [newProp, setNewProp] = useState({ name: '', value: '' })
  const [linkLabel, setLinkLabel] = useState('')
  const sel = p.selection

  if (!sel.length)
    return (
      <p className="text-zinc-500">
        Select an entity to inspect it. Right-click for transforms. Shift+drag box-selects; Delete removes.
      </p>
    )

  const transformList = (
    <>
      <button className="btn mb-1 mt-3 w-full" onClick={p.onSuggest}>✨ Suggest next steps (AI)</button>
      <div className="h">Transforms</div>
      {p.transforms.length === 0 && <p className="text-xs text-zinc-500">No transforms for this type.</p>}
      {p.transforms.map((t) => {
        const needs = (t.missingSettings?.length ?? 0) > 0
        return (
          <div key={t.id} className="mb-1 flex gap-1">
            <button disabled={p.busy} onClick={() => p.onRun(t)} className="btn flex-1 text-left" title={t.description}>
              {t.name} {t.kind !== 'builtin' && <span className="text-xs text-sky-400">[{t.kind}]</span>}
              {needs && <span className="ml-1 text-[10px] text-amber-400">· needs key</span>}
            </button>
            {needs && (
              <button className="btn px-2 text-amber-400" title={`Configure: ${t.missingSettings!.join(', ')}`}
                onClick={() => p.onConfigure(t.missingSettings!)}>⚙</button>
            )}
          </div>
        )
      })}
    </>
  )

  if (sel.length > 1) {
    const tally: Record<string, number> = {}
    for (const e of sel) tally[e.type] = (tally[e.type] ?? 0) + 1
    const counts = Object.entries(tally).map(([t, n]) => `${n} ${t}`)
    return (
      <div>
        <div className="text-base font-semibold">{sel.length} entities selected</div>
        <p className="text-zinc-400">{counts.join(', ')}</p>
        {sel.length === 2 && (
          <>
            <div className="h">Link {sel[0].value} → {sel[1].value}</div>
            <input className="field mb-1" placeholder="Link label" value={linkLabel} onChange={(e) => setLinkLabel(e.target.value)} />
            <button className="btn w-full" onClick={() => p.onLink(sel[0].id, sel[1].id, linkLabel)}>
              Create link
            </button>
          </>
        )}
        {new Set(sel.map((e) => e.type)).size === 1 && transformList}
        <button className="btn mt-4 w-full text-rose-400" onClick={() => p.onDelete(sel.map((e) => e.id))}>
          Delete selected
        </button>
      </div>
    )
  }

  const e = sel[0]
  const props = Object.values(e.properties)
  const setProps = (next: Record<string, EntityProperty>) => p.onPatch(e.id, { properties: next })
  const incoming = p.links.filter((l) => l.targetId === e.id)
  const outgoing = p.links.filter((l) => l.sourceId === e.id)
  const linkRow = (l: Link, otherId: string, arrow: string) => {
    const o = p.byId(otherId)
    const c = CLASS_META[l.classification ?? 'manual'] ?? CLASS_META.manual
    const when = l.createdAt ? new Date(l.createdAt).toISOString().slice(0, 10) : null
    return (
      <div key={l.id} className="mb-1.5">
        <button onClick={() => p.onSelect([otherId])} className="block w-full truncate text-left hover:text-sky-400" title={o?.value}>
          {arrow} <span className="text-zinc-500">{l.label || 'link'}:</span> {o?.value ?? otherId}
        </button>
        <div className="flex flex-wrap items-center gap-1 pl-3 text-[10px] text-zinc-500" title={c.hint}>
          <span className={`rounded px-1 ${c.cls}`}>{c.label}</span>
          {l.provider && <span>· {l.provider}</span>}
          {when && <span>· {when}</span>}
          {l.evidenceId && <a className="text-sky-500 hover:underline" href={`/api/evidence/${l.evidenceId}`} title="Raw response that produced this relationship">· evidence</a>}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center gap-2">
        <img src={ENTITY_TYPES[e.type].icon} className="h-7 w-7" alt="" />
        <div className="min-w-0">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">{e.type}</div>
          <div className="truncate font-semibold" title={e.value}>{e.label || e.value}</div>
        </div>
      </div>

      {e.type === 'Image' && e.properties['image.id'] && (
        <>
          <img src={`/api/images/${e.properties['image.id'].value}`} alt={e.value}
            className="mt-2 max-h-40 w-full cursor-pointer rounded border border-zinc-700 object-contain"
            onClick={() => p.onOpenImage(e)} />
          <button className="btn mt-2 w-full text-amber-400" onClick={() => p.onOpenImage(e)}>⊡ Open in Light Table</button>
        </>
      )}

      <div className="h">Value</div>
      <Commit value={e.value} onCommit={(v) => v.trim() && p.onPatch(e.id, { value: v.trim() })} />
      <div className="h">Label</div>
      <Commit value={e.label ?? ''} onCommit={(v) => p.onPatch(e.id, { label: v || null })} />
      <div className="h">Notes</div>
      <Commit multiline value={e.metadata.notes ?? ''} onCommit={(v) => p.onPatch(e.id, { notes: v || null })} />

      <div className="h">Properties</div>
      {props.length === 0 && <p className="text-xs text-zinc-500">None.</p>}
      {props.map((pr) => (
        <div key={pr.name} className="mb-1.5">
          <div className="flex justify-between text-xs text-zinc-400">
            <span title={pr.name}>{pr.displayName}</span>
            {!pr.isReadOnly && (
              <button
                className="text-zinc-600 hover:text-rose-400"
                onClick={() => setProps(Object.fromEntries(Object.entries(e.properties).filter(([k]) => k !== pr.name)))}
              >
                ✕
              </button>
            )}
          </div>
          <Commit
            value={String(pr.value)}
            disabled={pr.isReadOnly}
            onCommit={(v) => setProps({ ...e.properties, [pr.name]: { ...pr, value: v } })}
          />
        </div>
      ))}
      <div className="mt-2 flex gap-1">
        <input className="field" placeholder="name" value={newProp.name} onChange={(ev) => setNewProp({ ...newProp, name: ev.target.value })} />
        <input className="field" placeholder="value" value={newProp.value} onChange={(ev) => setNewProp({ ...newProp, value: ev.target.value })} />
        <button
          className="btn"
          disabled={!newProp.name}
          onClick={() => {
            setProps({ ...e.properties, [newProp.name]: { name: newProp.name, displayName: newProp.name, value: newProp.value } })
            setNewProp({ name: '', value: '' })
          }}
        >
          +
        </button>
      </div>

      <div className="h">Links ({incoming.length} in, {outgoing.length} out)</div>
      <div className="max-h-48 overflow-auto">
        {incoming.map((l) => linkRow(l, l.sourceId, '←'))}
        {outgoing.map((l) => linkRow(l, l.targetId, '→'))}
      </div>

      {['IPAddress', 'Domain', 'Website'].includes(e.type) && (
        <button className="btn mb-1 mt-3 w-full text-left text-rose-300"
          title="Opens a scope + authorization dialog. Discovered IPs are never scanned automatically."
          onClick={() => p.onScan(e.value)}>⊙ Scan authorized target…</button>
      )}

      {transformList}

      {/* key on link/property counts so a run on this entity refreshes its evidence without reselecting */}
      <Evidence key={`${e.id}:${incoming.length + outgoing.length}:${props.length}`} entityId={e.id} />

      <div className="h">Metadata</div>
      <p className="text-xs text-zinc-400">
        Created {new Date(e.metadata.createdAt).toLocaleString()}
        {e.metadata.discoveredByTransform && <><br />Found by: {e.metadata.discoveredByTransform}</>}
        <br />
        <span className="select-all text-zinc-600">{e.id}</span>
      </p>
      <button className="btn mt-3 w-full text-rose-400" onClick={() => p.onDelete([e.id])}>
        Delete entity
      </button>
    </div>
  )
}

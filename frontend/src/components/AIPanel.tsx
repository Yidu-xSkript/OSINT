import { useEffect, useState } from 'react'
import { api, type Suggestion } from '../api'
import { ENTITY_TYPES, type EntityType } from '../types'

type Tab = 'extract' | 'suggest' | 'summary'
type Found = { type: EntityType; value: string; label?: string }

export default function AIPanel({ gid, tab: initial, seed, onAdd, onRun, onFail, onClose }: {
  gid: string
  tab: Tab
  seed?: Suggestion[]
  onAdd: (rows: Found[]) => Promise<unknown>
  onRun: (s: Suggestion) => void
  onFail: (e: unknown) => void
  onClose: () => void
}) {
  const [tab, setTab] = useState<Tab>(initial)
  const [busy, setBusy] = useState(false)
  const [text, setText] = useState('')
  const [found, setFound] = useState<Found[] | null>(null)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [suggestions, setSuggestions] = useState<Suggestion[] | null>(seed ?? null)
  const [summary, setSummary] = useState<string | null>(null)

  useEffect(() => { if (seed) { setSuggestions(seed); setTab('suggest') } }, [seed])
  useEffect(() => { if (tab === 'summary' && summary === null) void getSummary() }, [tab])

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true)
    try { await fn() } catch (e) { onFail(e) } finally { setBusy(false) }
  }

  const extract = () => guard(async () => {
    const r = await api.aiExtract(text)
    setFound(r.entities)
    setPicked(new Set(r.entities.map((_, i) => i)))
  })
  const getSummary = () => guard(async () => setSummary((await api.aiSummary(gid)).summary))
  const addPicked = () => guard(async () => {
    await onAdd((found ?? []).filter((_, i) => picked.has(i)))
    onClose()
  })

  const tabBtn = (t: Tab, label: string) => (
    <button onClick={() => setTab(t)} className={`rounded px-3 py-1 ${tab === t ? 'bg-sky-800' : 'hover:bg-zinc-800'}`}>{label}</button>
  )

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/60" onMouseDown={onClose}>
      <div className="flex max-h-[85vh] w-[640px] flex-col rounded-lg border border-zinc-700 bg-zinc-900" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1 border-b border-zinc-800 p-2">
          <span className="mr-1 font-semibold">✨ AI assist</span>
          {tabBtn('extract', 'Extract from text')}
          {tabBtn('suggest', 'Suggest pivots')}
          {tabBtn('summary', 'Summarize graph')}
          <button className="ml-auto px-2 text-zinc-400 hover:text-white" onClick={onClose}>✕</button>
        </div>

        <div className="overflow-auto p-4">
          {tab === 'extract' && (
            <>
              <p className="mb-2 text-xs text-zinc-400">Paste an article, profile, breach dump, or notes. The model pulls out entities for you to add.</p>
              <textarea className="field mb-2 h-40" placeholder="Paste text here…" value={text} onChange={(e) => setText(e.target.value)} />
              <button className="btn" disabled={busy || !text.trim()} onClick={extract}>{busy ? 'Working…' : 'Extract entities'}</button>
              {found && (
                <>
                  <div className="h">Found {found.length} — pick what to add</div>
                  {found.length === 0 && <p className="text-xs text-zinc-500">Nothing recognized.</p>}
                  {found.map((f, i) => (
                    <label key={i} className="flex items-center gap-2 py-0.5">
                      <input type="checkbox" checked={picked.has(i)} onChange={(e) => {
                        const n = new Set(picked); e.target.checked ? n.add(i) : n.delete(i); setPicked(n)
                      }} />
                      <img src={ENTITY_TYPES[f.type].icon} className="h-4 w-4" alt="" />
                      <span className="text-zinc-400">{f.type}</span>
                      <span className="truncate">{f.value}</span>
                    </label>
                  ))}
                  {found.length > 0 && <button className="btn mt-2" disabled={busy || !picked.size} onClick={addPicked}>Add {picked.size} to graph</button>}
                </>
              )}
            </>
          )}

          {tab === 'suggest' && (
            <>
              <p className="mb-2 text-xs text-zinc-400">Next-step ideas for the selected entities. Click one to run it.</p>
              {suggestions === null && <p className="text-sky-400">Thinking…</p>}
              {suggestions?.length === 0 && <p className="text-xs text-zinc-500">No suggestions (select some entities first, and set an AI key in Transforms → API Keys).</p>}
              {suggestions?.map((s, i) => (
                <div key={i} className="mb-2 rounded border border-zinc-800 p-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{s.suggestion}</div>
                      <div className="text-xs text-zinc-500">{s.value && <span className="text-zinc-400">{s.value}: </span>}{s.reason}</div>
                    </div>
                    {(s.transformId || s.machineId) && <button className="btn shrink-0" onClick={() => onRun(s)}>Run</button>}
                  </div>
                </div>
              ))}
            </>
          )}

          {tab === 'summary' && (
            <>
              {summary === null && <p className="text-sky-400">Summarizing…</p>}
              {summary !== null && (
                <>
                  <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{summary}</pre>
                  <button className="btn mt-3" disabled={busy} onClick={() => { setSummary(null); getSummary() }}>Regenerate</button>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

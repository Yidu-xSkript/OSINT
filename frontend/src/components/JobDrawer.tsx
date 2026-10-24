import { useState } from 'react'
import type { Job, JobStatus, UIMessage } from '../types'

// The bottom drawer: one row per operation with its lifecycle, what it produced, and controls — so a
// timeout or an empty result is never mistaken for a hang, and each graph change traces to the job that made it.
const MSG_COLOR: Record<string, string> = { FatalError: 'text-rose-400', PartialError: 'text-amber-400', Debug: 'text-zinc-500' }
const STATUS: Record<JobStatus, { label: string; cls: string }> = {
  running: { label: 'running', cls: 'text-sky-400' },
  done: { label: 'done', cls: 'text-green-400' },
  'no-results': { label: 'no results', cls: 'text-zinc-400' },
  error: { label: 'failed', cls: 'text-rose-400' },
  cancelled: { label: 'cancelled', cls: 'text-amber-400' },
}

const secs = (j: Job) => `${(((j.endedAt ?? Date.now()) - j.startedAt) / 1000).toFixed(1)}s`

export default function JobDrawer({ jobs, log, canRetry, onShow, onRetry, onCancel, onClear, onClearLog }: {
  jobs: Job[]
  log: UIMessage[]
  canRetry: (j: Job) => boolean
  onShow: (ids: string[]) => void
  onRetry: (j: Job) => void
  onCancel: (j: Job) => void
  onClear: () => void
  onClearLog: () => void
}) {
  const [tab, setTab] = useState<'jobs' | 'output'>('jobs')
  const running = jobs.filter((j) => j.status === 'running').length

  return (
    <div className="flex h-full flex-col font-mono text-xs">
      <div className="mb-1 flex items-center gap-3 text-zinc-500">
        <button className={tab === 'jobs' ? 'text-zinc-200' : 'hover:text-zinc-300'} onClick={() => setTab('jobs')}>
          Jobs{running > 0 && <span className="ml-1 text-sky-400">⟳ {running}</span>}
        </button>
        <button className={tab === 'output' ? 'text-zinc-200' : 'hover:text-zinc-300'} onClick={() => setTab('output')}>Output</button>
        <button className="ml-auto hover:text-white" onClick={tab === 'jobs' ? onClear : onClearLog}>clear</button>
      </div>

      {tab === 'jobs' ? (
        <div className="min-h-0 flex-1 overflow-auto">
          {jobs.length === 0 && <p className="text-zinc-600">No jobs yet. Run a transform to see its progress, result and provenance here.</p>}
          {jobs.map((j) => {
            const s = STATUS[j.status]
            return (
              <div key={j.id} className="flex items-center gap-2 border-b border-zinc-900 py-1">
                <span className={`w-20 shrink-0 ${s.cls}`}>{j.status === 'running' ? '⟳ ' : ''}{s.label}</span>
                <span className="min-w-0 flex-1 truncate text-zinc-300" title={j.label}>{j.label}</span>
                {j.status !== 'running' && (
                  <span className="shrink-0 text-zinc-500">
                    {j.entities > 0 || j.links > 0 ? `+${j.entities}e / +${j.links}l` : '—'} · {secs(j)}
                  </span>
                )}
                <span className="flex shrink-0 gap-2">
                  {j.entityIds.length > 0 && <button className="text-sky-400 hover:underline" onClick={() => onShow(j.entityIds)}>show</button>}
                  {j.status === 'running' && j.kind === 'machine' && <button className="text-amber-400 hover:underline" onClick={() => onCancel(j)}>cancel</button>}
                  {j.status !== 'running' && canRetry(j) && <button className="text-zinc-400 hover:text-white" onClick={() => onRetry(j)}>retry</button>}
                </span>
                {j.detail && <span className="w-full shrink-0 basis-full truncate pl-20 text-rose-400/80" title={j.detail}>{j.detail}</span>}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto">
          {log.length === 0 && <p className="text-zinc-600">No output.</p>}
          {log.map((m, i) => (
            <div key={i} className={MSG_COLOR[m.type] ?? 'text-zinc-300'}>
              <span className="text-zinc-600">{new Date(m.at!).toLocaleTimeString()}</span>{' '}
              {m.transform && <span className="text-sky-400">[{m.transform}]</span>} {m.entity && <span className="text-zinc-400">{m.entity}: </span>}{m.text}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

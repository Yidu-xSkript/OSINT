import { useEffect, useRef, useState } from 'react'

// In-app replacement for window.prompt / window.confirm: keeps the dark theme, keyboard behaviour and
// focus trap instead of a native OS dialog. Promise-based so callers can `await ask.prompt(...)`.
export interface DialogSpec {
  kind: 'prompt' | 'confirm'
  title: string
  message?: string
  value?: string
  placeholder?: string
  confirmLabel?: string
  danger?: boolean
  resolve: (v: string | boolean | null) => void
}

export function useDialog() {
  const [spec, setSpec] = useState<DialogSpec | null>(null)
  const ask = {
    prompt: (title: string, value = '', opts: Partial<DialogSpec> = {}) =>
      new Promise<string | null>((resolve) => setSpec({ kind: 'prompt', title, value, ...opts, resolve: resolve as DialogSpec['resolve'] })),
    confirm: (title: string, opts: Partial<DialogSpec> = {}) =>
      new Promise<boolean>((resolve) => setSpec({ kind: 'confirm', title, ...opts, resolve: resolve as DialogSpec['resolve'] })),
  }
  const node = spec ? <Dialog spec={spec} onDone={() => setSpec(null)} /> : null
  return { ask, node }
}

function Dialog({ spec, onDone }: { spec: DialogSpec; onDone: () => void }) {
  const [val, setVal] = useState(spec.value ?? '')
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select() }, [])

  const done = (result: string | boolean | null) => { spec.resolve(result); onDone() }
  const cancel = () => done(spec.kind === 'confirm' ? false : null)
  const ok = () => done(spec.kind === 'confirm' ? true : val)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" role="dialog" aria-modal="true"
      aria-label={spec.title} onMouseDown={cancel}
      onKeyDown={(e) => { if (e.key === 'Escape') cancel() }}>
      <div className="w-[380px] rounded-lg border border-zinc-700 bg-zinc-900 p-4 shadow-xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-2 font-semibold text-zinc-100">{spec.title}</div>
        {spec.message && <p className="mb-3 text-xs text-zinc-400">{spec.message}</p>}
        {spec.kind === 'prompt' && (
          <input ref={inputRef} className="field mb-3" value={val} placeholder={spec.placeholder}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') ok() }} />
        )}
        <div className="flex justify-end gap-2">
          <button className="btn" onClick={cancel}>Cancel</button>
          <button className={`btn ${spec.danger ? 'border-rose-600 text-rose-300 hover:border-rose-400' : 'text-amber-400'}`}
            disabled={spec.kind === 'prompt' && !val.trim()} onClick={ok} autoFocus={spec.kind === 'confirm'}>
            {spec.confirmLabel ?? (spec.kind === 'confirm' ? 'Confirm' : 'OK')}
          </button>
        </div>
      </div>
    </div>
  )
}

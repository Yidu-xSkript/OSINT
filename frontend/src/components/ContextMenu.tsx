import { useEffect } from 'react'

export type MenuItem = { label: string; hint?: string; onClick(): void; danger?: boolean } | { header: string } | 'sep'

export default function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose(): void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  return (
    <div
      className="absolute z-20 max-h-[70vh] min-w-56 overflow-auto rounded border border-zinc-700 bg-zinc-900 py-1 shadow-xl"
      style={{ left: x, top: y }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {items.map((it, i) =>
        it === 'sep' ? (
          <div key={i} className="my-1 border-t border-zinc-800" />
        ) : 'header' in it ? (
          <div key={i} className="px-3 pb-0.5 pt-1.5 text-[11px] uppercase tracking-wider text-zinc-500">
            {it.header}
          </div>
        ) : (
          <button
            key={i}
            onClick={() => {
              onClose()
              it.onClick()
            }}
            className={`flex w-full justify-between gap-4 px-3 py-1 text-left hover:bg-sky-900/50 ${it.danger ? 'text-rose-400' : ''}`}
          >
            {it.label}
            {it.hint && <span className="text-zinc-500">{it.hint}</span>}
          </button>
        ),
      )}
    </div>
  )
}

// Embeds God's Eye View in a wide in-app popup (iframe), centered on a location.
export default function GlobeView({ url, title, onClose }: { url: string; title: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-zinc-950/90" onMouseDown={onClose}>
      <div className="m-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950 shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-1.5">
          <span className="font-semibold text-cyan-300">🌍 God's Eye View</span>
          <span className="truncate text-zinc-400">{title}</span>
          <a className="btn ml-auto" href={url} target="_blank" rel="noreferrer" title="Open in a new tab">Open in tab ↗</a>
          <button className="btn text-rose-400" onClick={onClose}>✕ Close</button>
        </div>
        <div className="relative min-h-0 flex-1">
          <iframe title="God's Eye View" src={url} className="h-full w-full border-0"
            allow="accelerometer; gyroscope; magnetometer; microphone; xr-spatial-tracking; fullscreen" />
          <div className="pointer-events-none absolute bottom-2 left-3 text-[11px] text-zinc-600">
            Bundled God's Eye View · keyless Esri imagery. Set the <code>gev.url</code> setting to a full GEV server for its live data layers.
          </div>
        </div>
      </div>
    </div>
  )
}

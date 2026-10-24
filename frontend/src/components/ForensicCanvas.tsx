import { useEffect, useRef, useState } from 'react'
import { apply, DEFAULT_FILTER, isDefault, PRESETS, type ImageFilterState } from '../forensics/ImageForensicsEngine'

// The Forensic Light Table: non-destructive filter pipeline, pan/zoom to pixel level, forensic presets,
// plus split-curtain / opacity-blend comparison of the evidence against a candidate reference image.
type CompareMode = 'off' | 'split' | 'blend'
type Adjust = { dx: number; dy: number; scale: number; rot: number }
const NO_ADJUST: Adjust = { dx: 0, dy: 0, scale: 1, rot: 0 }

export default function ForensicCanvas({ src, title, onClose }: { src: string; title: string; onClose: () => void }) {
  const view = useRef<HTMLCanvasElement>(null)
  const source = useRef<HTMLCanvasElement | null>(null) // filtered full-res offscreen (evidence)
  const img = useRef<HTMLImageElement | null>(null)
  const cand = useRef<HTMLImageElement | null>(null)
  const dpr = useRef(1)
  const [filter, setFilter] = useState<ImageFilterState>(DEFAULT_FILTER)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [nearest, setNearest] = useState(false)
  const [err, setErr] = useState('')
  const [loaded, setLoaded] = useState(false)
  // comparison
  const [candUrl, setCandUrl] = useState<string | null>(null)
  const [candReady, setCandReady] = useState(false)
  const [mode, setMode] = useState<CompareMode>('off')
  const [split, setSplit] = useState(0.5)
  const [opacity, setOpacity] = useState(0.5)
  const [adj, setAdj] = useState<Adjust>(NO_ADJUST)
  const drag = useRef<{ x: number; y: number; px: number; py: number; cand: boolean } | null>(null)
  const candInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      img.current = image
      const off = document.createElement('canvas')
      off.width = image.naturalWidth
      off.height = image.naturalHeight
      source.current = off
      setLoaded(true)
      fitToView(image.naturalWidth, image.naturalHeight)
    }
    image.onerror = () => setErr('could not load the image')
    image.src = src
  }, [src])

  // load candidate reference
  useEffect(() => {
    setCandReady(false)
    if (!candUrl) { cand.current = null; return }
    const c = new Image()
    c.crossOrigin = 'anonymous'
    c.onload = () => { cand.current = c; setCandReady(true); if (mode === 'off') setMode('split') }
    c.onerror = () => setErr('could not load the candidate image')
    c.src = candUrl
  }, [candUrl])

  const fitToView = (iw: number, ih: number) => {
    const c = view.current
    if (!c) return
    const z = Math.min(c.width / iw, c.height / ih, 1)
    setZoom(z)
    setPan({ x: (c.width - iw * z) / 2, y: (c.height - ih * z) / 2 })
  }

  // re-filter the evidence offscreen when the filter changes
  useEffect(() => {
    if (!loaded || !img.current || !source.current) return
    const off = source.current
    const ctx = off.getContext('2d', { willReadFrequently: true })!
    ctx.drawImage(img.current, 0, 0)
    if (!isDefault(filter)) {
      const data = ctx.getImageData(0, 0, off.width, off.height)
      apply(data, filter)
      ctx.putImageData(data, 0, 0)
    }
    render()
  }, [filter, loaded])

  const render = () => {
    const c = view.current, off = source.current
    if (!c || !off) return
    const ctx = c.getContext('2d')!
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = '#0b0d10'
    ctx.fillRect(0, 0, c.width, c.height)
    ctx.imageSmoothingEnabled = !nearest

    const world = () => { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.translate(pan.x, pan.y); ctx.scale(zoom, zoom) }
    world(); ctx.drawImage(off, 0, 0)

    if (cand.current && mode !== 'off') {
      const cw = cand.current.naturalWidth, ch = cand.current.naturalHeight
      const drawCand = () => {
        world()
        ctx.translate(adj.dx, adj.dy)
        ctx.translate(cw / 2, ch / 2); ctx.rotate((adj.rot * Math.PI) / 180); ctx.scale(adj.scale, adj.scale); ctx.translate(-cw / 2, -ch / 2)
        ctx.drawImage(cand.current!, 0, 0)
      }
      if (mode === 'split') {
        const x = split * c.width
        ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.beginPath(); ctx.rect(x, 0, c.width - x, c.height); ctx.clip()
        drawCand(); ctx.restore()
        ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.strokeStyle = '#f0a63c'; ctx.lineWidth = 2 * dpr.current
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, c.height); ctx.stroke()
      } else {
        ctx.save(); ctx.globalAlpha = opacity; drawCand(); ctx.restore()
      }
    }
    ctx.setTransform(1, 0, 0, 1, 0, 0)
  }
  useEffect(render, [pan, zoom, nearest, mode, split, opacity, adj, candReady])

  useEffect(() => {
    const c = view.current
    if (!c) return
    const resize = () => {
      const r = c.parentElement!.getBoundingClientRect()
      if (!r.width || !r.height) return
      dpr.current = Math.min(window.devicePixelRatio || 1, 2)
      c.width = Math.round(r.width * dpr.current)
      c.height = Math.round(r.height * dpr.current)
      if (img.current) render()
    }
    const ro = new ResizeObserver(resize)
    ro.observe(c.parentElement!)
    resize()
    return () => ro.disconnect()
  }, [loaded])

  // device-pixel mouse position
  const devPos = (e: { clientX: number; clientY: number }) => {
    const rect = view.current!.getBoundingClientRect()
    return { x: (e.clientX - rect.left) * dpr.current, y: (e.clientY - rect.top) * dpr.current }
  }

  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const { x, y } = devPos(e)
    const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2
    const nz = Math.max(0.05, Math.min(32, zoom * factor))
    setPan({ x: x - (x - pan.x) * (nz / zoom), y: y - (y - pan.y) * (nz / zoom) })
    setZoom(nz)
  }

  const onDown = (e: React.MouseEvent) => {
    const p = devPos(e)
    // Alt-drag nudges the candidate's alignment; plain drag pans the view
    drag.current = { x: p.x, y: p.y, px: e.altKey ? adj.dx : pan.x, py: e.altKey ? adj.dy : pan.y, cand: e.altKey }
  }
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return
    const p = devPos(e)
    const d = drag.current
    if (d.cand) setAdj((a) => ({ ...a, dx: d.px + (p.x - d.x) / zoom, dy: d.py + (p.y - d.y) / zoom }))
    else setPan({ x: d.px + (p.x - d.x), y: d.py + (p.y - d.y) })
  }

  const set = (k: keyof ImageFilterState, v: number | boolean | string) => setFilter((f) => ({ ...f, [k]: v }))
  const slider = (k: keyof ImageFilterState, label: string, min: number, max: number, step = 1) => (
    <label className="mb-2 block text-xs">
      <div className="flex justify-between text-zinc-400"><span>{label}</span><span>{String(filter[k])}</span></div>
      <input type="range" min={min} max={max} step={step} value={filter[k] as number}
        onChange={(e) => set(k, Number(e.target.value))} className="w-full accent-amber-500" />
    </label>
  )
  const rng = (label: string, val: number, min: number, max: number, step: number, on: (v: number) => void, fmt = (v: number) => String(v)) => (
    <label className="mb-2 block text-xs">
      <div className="flex justify-between text-zinc-400"><span>{label}</span><span>{fmt(val)}</span></div>
      <input type="range" min={min} max={max} step={step} value={val} onChange={(e) => on(Number(e.target.value))} className="w-full accent-cyan-400" />
    </label>
  )

  const onCandFile = (f: File | undefined) => {
    if (f) { setCandUrl((u) => { if (u) URL.revokeObjectURL(u); return URL.createObjectURL(f) }); setAdj(NO_ADJUST) }
  }

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-zinc-950">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-1.5">
        <span className="font-semibold text-amber-400">⊡ Forensic Light Table</span>
        <span className="truncate text-zinc-400">{title}</span>
        <span className="ml-auto text-xs text-zinc-500">{Math.round(zoom * 100)}%</span>
        <button className="btn" onClick={() => img.current && fitToView(img.current.naturalWidth, img.current.naturalHeight)}>Fit</button>
        <button className="btn" onClick={() => { setZoom(dpr.current); setPan({ x: 0, y: 0 }) }}>100%</button>
        <label className="flex items-center gap-1 text-xs text-zinc-400" title="Nearest-neighbor: shows the pixel grid at high zoom">
          <input type="checkbox" checked={nearest} onChange={(e) => setNearest(e.target.checked)} />Pixel grid
        </label>
        <button className="btn text-rose-400" onClick={onClose}>✕ Close</button>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {err && <div className="absolute inset-0 flex items-center justify-center text-rose-400">{err}</div>}
          <canvas ref={view} className="h-full w-full cursor-grab active:cursor-grabbing" onWheel={onWheel}
            onMouseDown={onDown} onMouseMove={onMove} onMouseUp={() => (drag.current = null)} onMouseLeave={() => (drag.current = null)} />
        </div>

        <aside className="w-64 shrink-0 overflow-auto border-l border-zinc-800 bg-zinc-900 p-3">
          <div className="h !mt-0">Forensic Presets</div>
          <div className="grid grid-cols-2 gap-1">
            {Object.keys(PRESETS).map((name) => (
              <button key={name} className="btn !px-1.5 text-[11px]" onClick={() => setFilter({ ...DEFAULT_FILTER, ...PRESETS[name] })}>{name}</button>
            ))}
          </div>

          <div className="h">Dynamic Range</div>
          {slider('brightness', 'Brightness', -100, 100)}
          {slider('contrast', 'Contrast', -100, 100)}
          {slider('shadowLift', 'Shadow Lift', 0, 100)}
          {slider('gamma', 'Gamma', 0.2, 3, 0.05)}
          <div className="h">Structure</div>
          {slider('sharpness', 'Sharpness / High-Pass', 0, 100)}
          <label className="mb-2 flex items-center gap-2 text-xs">
            <input type="checkbox" checked={filter.invert} onChange={(e) => set('invert', e.target.checked)} /> Invert
          </label>
          <label className="mb-2 block text-xs">
            <span className="text-zinc-400">Channel isolation</span>
            <select className="field" value={filter.channelIsolation} onChange={(e) => set('channelIsolation', e.target.value)}>
              <option value="ALL">All (RGB)</option><option value="R">Red</option><option value="G">Green</option><option value="B">Blue</option>
            </select>
          </label>
          <button className="btn mb-2 w-full" onClick={() => setFilter(DEFAULT_FILTER)}>Reset filters</button>

          <div className="h">Compare with Candidate</div>
          <input ref={candInput} type="file" accept="image/*" hidden data-testid="candidate-input"
            onChange={(e) => onCandFile(e.target.files?.[0])} />
          <button className="btn w-full" onClick={() => candInput.current?.click()}>{candUrl ? 'Replace candidate image' : 'Load candidate image'}</button>
          {candReady && (
            <>
              <div className="mt-2 grid grid-cols-3 gap-1">
                {(['off', 'split', 'blend'] as CompareMode[]).map((m) => (
                  <button key={m} className={`btn !px-1 text-[11px] ${mode === m ? '!border-cyan-400 text-cyan-300' : ''}`} onClick={() => setMode(m)}>{m}</button>
                ))}
              </div>
              {mode === 'split' && rng('Split position', split, 0, 1, 0.01, setSplit, (v) => `${Math.round(v * 100)}%`)}
              {mode === 'blend' && rng('Candidate opacity', opacity, 0, 1, 0.01, setOpacity, (v) => `${Math.round(v * 100)}%`)}
              {mode !== 'off' && (
                <>
                  <div className="mt-1 text-[11px] text-zinc-500">Align the candidate (Alt+drag to move):</div>
                  {rng('Scale', adj.scale, 0.1, 4, 0.01, (v) => setAdj((a) => ({ ...a, scale: v })), (v) => `${v.toFixed(2)}×`)}
                  {rng('Rotation', adj.rot, -180, 180, 0.5, (v) => setAdj((a) => ({ ...a, rot: v })), (v) => `${v}°`)}
                  <button className="btn w-full" onClick={() => setAdj(NO_ADJUST)}>Reset alignment</button>
                </>
              )}
            </>
          )}
          <p className="mt-3 text-[11px] text-zinc-600">Non-destructive. Scroll to zoom (to pixel level), drag to pan, Alt+drag to move the candidate.</p>
        </aside>
      </div>
    </div>
  )
}

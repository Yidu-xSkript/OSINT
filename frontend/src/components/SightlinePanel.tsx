import { useMemo, useState } from 'react'
import { api, type SightlineResult } from '../api'
import type { Entity } from '../types'

// Collinear sightline resection (Bellingcat / Gary Riddell technique): two landmarks that line up in a
// photo + the candidate camera building → the window's facing direction, floor, and which façade.
const coordsOf = (e: Entity): [number, number] | null => {
  for (const k of ['location.coordinates', 'coordinates', 'gps.coordinate']) {
    const v = e.properties[k]?.value
    if (typeof v === 'string' && /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(v)) { const [a, b] = v.split(','); return [+a, +b] }
  }
  return /^-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(e.value) ? (e.value.split(',').map(Number) as [number, number]) : null
}

const quality = (err: number) => err < 1 ? ['excellent', 'text-green-400'] : err < 3 ? ['good', 'text-amber-400'] : ['poor — landmarks may not be collinear, or coords are rough', 'text-rose-400']

export default function SightlinePanel({ locations, onApply, onShowGlobe, onFail, onClose }: {
  locations: Entity[]
  onApply: (id: string, props: Record<string, string>) => void
  onShowGlobe: (lat: number, lon: number, title: string) => void
  onFail: (e: unknown) => void
  onClose: () => void
}) {
  const geo = useMemo(() => locations.filter(coordsOf), [locations])
  const [farId, setFarId] = useState('')
  const [nearId, setNearId] = useState('')
  const [camId, setCamId] = useState('')
  const [farH, setFarH] = useState('')
  const [nearH, setNearH] = useState('')
  const [res, setRes] = useState<SightlineResult | null>(null)
  const [busy, setBusy] = useState(false)

  const ent = (id: string) => geo.find((e) => e.id === id)
  const pick = (val: string, set: (v: string) => void, label: string) => (
    <label className="mb-2 block text-xs">
      <span className="text-zinc-400">{label}</span>
      <select className="field" value={val} onChange={(e) => set(e.target.value)}>
        <option value="">— pick a Location —</option>
        {geo.map((e) => <option key={e.id} value={e.id}>{e.value}</option>)}
      </select>
    </label>
  )

  const compute = async () => {
    const far = ent(farId), near = ent(nearId), cam = ent(camId)
    if (!far || !near || !cam) { onFail(new Error('pick a far landmark, a near landmark, and the camera building')); return }
    const [flat, flon] = coordsOf(far)!, [nlat, nlon] = coordsOf(near)!, [clat, clon] = coordsOf(cam)!
    setBusy(true)
    try {
      setRes(await api.sightline(
        { lat: flat, lon: flon, height: farH ? +farH : null },
        { lat: nlat, lon: nlon, height: nearH ? +nearH : null },
        { lat: clat, lon: clon }))
    } catch (e) { onFail(e) } finally { setBusy(false) }
  }

  const apply = () => {
    if (!res || !camId) return
    const p: Record<string, string> = {
      'sightline.facing': `${res.facing_azimuth}° (${res.facing_compass})`,
      'sightline.collinearity_err': `${res.collinearity_error_deg}°`,
    }
    if (res.camera_height_m != null) p['sightline.camera_height'] = `${res.camera_height_m} m`
    if (res.estimated_floor != null) p['sightline.estimated_floor'] = String(res.estimated_floor)
    onApply(camId, p)
    onClose()
  }

  const row = (k: string, v: string) => <div className="flex justify-between py-0.5"><span className="text-zinc-500">{k}</span><span className="font-mono">{v}</span></div>

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/60" onMouseDown={onClose}>
      <div className="flex max-h-[85vh] w-[560px] flex-col rounded-lg border border-zinc-700 bg-zinc-900" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-zinc-800 p-2">
          <span className="font-semibold text-amber-400">⌖ Sightline Resection</span>
          <button className="ml-auto px-2 text-zinc-400 hover:text-white" onClick={onClose}>✕</button>
        </div>
        <div className="overflow-auto p-4">
          <p className="mb-3 text-xs text-zinc-400">
            Two landmarks that line up vertically in the evidence photo (a nearer one in front of a farther one) fix the
            camera on the ray through them. Pick both plus the candidate building; add landmark heights (m) for a floor estimate.
            Geolocate landmarks with <b>To Coordinates [Nominatim]</b> first.
          </p>
          {geo.length < 3 && <p className="mb-2 text-amber-400/80 text-xs">Need at least 3 geolocated Locations in the graph.</p>}

          {pick(farId, setFarId, 'Far landmark (distant — e.g. a spire)')}
          <input className="field mb-2" placeholder="far landmark height (m, optional)" value={farH} onChange={(e) => setFarH(e.target.value)} />
          {pick(nearId, setNearId, 'Near landmark (foreground — e.g. a bridge arch)')}
          <input className="field mb-2" placeholder="near landmark height (m, optional)" value={nearH} onChange={(e) => setNearH(e.target.value)} />
          {pick(camId, setCamId, 'Camera building (the candidate)')}

          <button className="btn mt-1" disabled={busy} onClick={compute}>{busy ? 'Computing…' : 'Compute resection'}</button>

          {res && (
            <div className="mt-3 rounded border border-zinc-800 p-3 text-sm">
              <div className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">Result</div>
              {row('Window faces', `${res.facing_azimuth}° ${res.facing_compass}`)}
              {row('Camera height', res.camera_height_m != null ? `${res.camera_height_m} m` : '(add landmark heights)')}
              {row('Estimated floor', res.estimated_floor != null ? `~${res.estimated_floor}` : '—')}
              {row('Distance to near / far', `${res.distance_to_near_m} m / ${res.distance_to_far_m} m`)}
              <div className="mt-1 flex justify-between py-0.5">
                <span className="text-zinc-500">Collinearity</span>
                <span className={quality(res.collinearity_error_deg)[1]}>{res.collinearity_error_deg}° — {quality(res.collinearity_error_deg)[0]}</span>
              </div>
              <div className="mt-2 flex gap-2">
                <button className="btn" onClick={apply}>Annotate building</button>
                <button className="btn" onClick={() => { const c = coordsOf(ent(camId)!); if (c) onShowGlobe(c[0], c[1], ent(camId)!.value) }}>Show on Globe</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

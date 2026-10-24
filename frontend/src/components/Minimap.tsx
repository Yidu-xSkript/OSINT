import type { Core } from 'cytoscape'
import { useEffect, useRef } from 'react'
import { bounds } from '../layouts'
import { ENTITY_TYPES, type EntityType } from '../types'

const W = 200, H = 140

// Bird's-eye view: dots for every node + the current viewport; click/drag to pan.
export default function Minimap({ cy }: { cy: Core }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const map = useRef({ s: 1, ox: 0, oy: 0 })

  useEffect(() => {
    let timer = 0
    const draw = () => {
      timer = 0
      const ctx = canvas.current?.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, W, H)
      const nodes = cy.nodes()
      if (nodes.empty()) return
      const b = bounds(nodes.map((n) => n.position()))
      const s = Math.min((W - 10) / b.w, (H - 10) / b.h)
      const ox = (W - b.w * s) / 2 - b.x1 * s, oy = (H - b.h * s) / 2 - b.y1 * s
      map.current = { s, ox, oy }
      nodes.forEach((n) => {
        const p = n.position()
        ctx.fillStyle = ENTITY_TYPES[n.data('type') as EntityType]?.color ?? '#888'
        ctx.fillRect(p.x * s + ox - 1, p.y * s + oy - 1, 2.5, 2.5)
      })
      const e = cy.extent()
      ctx.strokeStyle = '#38bdf8'
      ctx.strokeRect(e.x1 * s + ox, e.y1 * s + oy, e.w * s, e.h * s)
    }
    const schedule = () => { if (!timer) timer = window.setTimeout(draw, 120) } // throttle: big graphs render often
    cy.on('render viewport add remove position', schedule)
    schedule()
    return () => { cy.off('render viewport add remove position', schedule); clearTimeout(timer) }
  }, [cy])

  const panTo = (e: React.MouseEvent) => {
    if (!(e.buttons & 1) && e.type !== 'mousedown') return
    const r = canvas.current!.getBoundingClientRect()
    const { s, ox, oy } = map.current
    const mx = (e.clientX - r.left - ox) / s, my = (e.clientY - r.top - oy) / s
    cy.pan({ x: cy.width() / 2 - mx * cy.zoom(), y: cy.height() / 2 - my * cy.zoom() })
  }

  return (
    <canvas
      ref={canvas}
      width={W}
      height={H}
      onMouseDown={panTo}
      onMouseMove={panTo}
      className="absolute bottom-3 right-3 cursor-crosshair rounded border border-zinc-700 bg-zinc-950/85"
      title="Bird's-eye view: click or drag to pan"
    />
  )
}

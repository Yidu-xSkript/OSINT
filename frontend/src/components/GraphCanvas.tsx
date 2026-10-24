import cytoscape, { type Core, type LayoutOptions } from 'cytoscape'
import dagre from 'cytoscape-dagre'
import fcose from 'cytoscape-fcose'
import { useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { bounds, INLINE_MAX_NODES, layoutOptions, type LayoutJob, type LayoutName, type Pos } from '../layouts'
import { ENTITY_TYPES, type Entity, type EntityType, type Link } from '../types'
import Minimap from './Minimap'

cytoscape.use(dagre)
cytoscape.use(fcose)

// Honour the OS "reduce motion" setting: skip the new-node fade/ring and layout tweening (reviewer §11).
const REDUCE_MOTION = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export type { LayoutName }

export interface GraphApi {
  add(entities: Entity[], links: Link[]): void
  updateEntity(e: Entity): void
  remove(ids: string[]): void
  clear(): void
  layout(name: LayoutName): Promise<boolean> // false = cancelled or superseded by a newer layout
  cancelLayout(): void
  select(ids: string[], fit?: boolean): void
  fit(): void
  cy(): Core | null
}

export interface ContextTarget {
  x: number
  y: number
  nodeId?: string
  edgeId?: string
}

const nodeData = (e: Entity) => ({ id: e.id, type: e.type, display: e.label || e.value })
const edgeData = (l: Link) => ({
  id: l.id,
  source: l.sourceId,
  target: l.targetId,
  label: l.label,
  bidirectional: l.direction === 'bidirectional',
})
const EDGE = '#4a505a'

function fitTo(cy: Core, pts: Pos[], pad = 40) {
  if (!pts.length) return
  const b = bounds(pts)
  const z = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), (cy.width() - 2 * pad) / b.w, (cy.height() - 2 * pad) / b.h))
  cy.viewport({ zoom: z, pan: { x: (cy.width() - z * (b.x1 + b.x2)) / 2, y: (cy.height() - z * (b.y1 + b.y2)) / 2 } })
}

const STYLE = [
  {
    selector: 'node',
    style: {
      width: 34,
      height: 34,
      'background-color': '#666',
      'background-fit': 'contain',
      label: 'data(display)',
      color: '#eef0f3',
      'font-size': 11,
      'font-weight': 600,
      'text-valign': 'bottom',
      'text-margin-y': 5,
      'text-max-width': '150px',
      'text-wrap': 'wrap',
      'text-overflow-wrap': 'anywhere',
      // halo so labels stay readable over edges and neighbouring nodes
      'text-outline-color': '#0f1115',
      'text-outline-width': 2.5,
      'text-outline-opacity': 0.9,
      'min-zoomed-font-size': 6,
      'border-color': '#f0a63c',
      'border-width': 0,
      'border-opacity': 0,
    },
  },
  ...Object.entries(ENTITY_TYPES).map(([t, m]) => ({
    selector: `node[type="${t}"]`,
    style: { 'background-color': m.color, 'background-image': m.icon },
  })),
  { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#ffffff', 'border-opacity': 1, 'text-outline-color': '#1e3a5f' } },
  {
    selector: 'edge',
    style: {
      width: 1.2,
      'line-color': EDGE,
      'target-arrow-color': EDGE,
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.8,
      'curve-style': 'bezier', // separates parallel links between the same pair
      label: 'data(label)',
      'font-size': 8,
      color: '#aeb4bf',
      'text-outline-color': '#0f1115',
      'text-outline-width': 2,
      'text-outline-opacity': 0.85,
      'text-rotation': 'autorotate',
      'min-zoomed-font-size': 10,
    },
  },
  { selector: 'edge[?bidirectional]', style: { 'source-arrow-shape': 'triangle', 'source-arrow-color': EDGE } },
  { selector: 'edge:selected', style: { 'line-color': '#38bdf8', 'target-arrow-color': '#38bdf8', width: 2 } },
] as cytoscape.StylesheetJson

interface Props {
  apiRef: Ref<GraphApi>
  webgl: boolean
  onSelect(ids: string[]): void
  onContext(t: ContextTarget | null): void
  onDropType(type: EntityType, model: Pos, screen: Pos): void
  onPositions(p: Record<string, Pos>): void
}

export default function GraphCanvas(props: Props) {
  const el = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const job = useRef<{ worker: Worker; done(applied: boolean): void } | null>(null)
  const inline = useRef<cytoscape.Layouts | null>(null)
  const cancelLayout = () => {
    job.current?.done(false)
    job.current = null
    inline.current?.stop()
    inline.current = null
  }
  const [cyState, setCy] = useState<Core | null>(null)
  const cb = useRef(props)
  cb.current = props

  useEffect(() => {
    const cy = cytoscape({
      container: el.current,
      style: STYLE,
      webgl: props.webgl,
      minZoom: 0.02,
      maxZoom: 4,
      boxSelectionEnabled: true,
    })
    cyRef.current = cy
    setCy(cy)

    const positions = (nodes: cytoscape.NodeCollection) =>
      Object.fromEntries(nodes.map((n) => [n.id(), { ...n.position() }]))
    let pending = false
    cy.on('select unselect', () => {
      if (pending) return
      pending = true
      setTimeout(() => {
        pending = false
        cb.current.onSelect(cy.$('node:selected').map((n) => n.id()))
      })
    })
    cy.on('cxttap', 'node', (e) => {
      if (!e.target.selected()) {
        cy.$(':selected').unselect()
        e.target.select()
      }
      cb.current.onContext({ ...e.renderedPosition, nodeId: e.target.id() })
    })
    cy.on('cxttap', 'edge', (e) => cb.current.onContext({ ...e.renderedPosition, edgeId: e.target.id() }))
    cy.on('tap', () => cb.current.onContext(null))
    // hover highlight (direct style — WebGL renderer ignores size/class transitions, but draws borders)
    cy.on('mouseover', 'node', (e) => { if (!e.target.selected()) e.target.style({ 'border-color': '#38bdf8', 'border-width': 3, 'border-opacity': 0.85 }) })
    cy.on('mouseout', 'node', (e) => { if (!e.target.selected()) e.target.removeStyle('border-width border-color border-opacity') })
    cy.on('dragfree', 'node', (e) => cb.current.onPositions(positions(cy.$('node:selected').union(e.target))))
    cy.on('layoutstop', () => cb.current.onPositions(positions(cy.nodes())))
    return () => {
      job.current?.worker.terminate()
      cy.destroy()
    }
  }, [props.webgl])

  useImperativeHandle(props.apiRef, () => ({
    cy: () => cyRef.current,
    add(entities, links) {
      const cy = cyRef.current!
      const fresh = new Map(entities.filter((e) => cy.getElementById(e.id).empty()).map((e) => [e.id, e]))
      // Place new nodes in a ring around the entity they were discovered from (Maltego-style), not a global relayout.
      const groups = new Map<string, Entity[]>()
      const assigned = new Set<string>()
      for (const l of links) {
        for (const [me, other] of [[l.targetId, l.sourceId], [l.sourceId, l.targetId]]) {
          const e = fresh.get(me)
          if (!e || e.position || fresh.has(other) || assigned.has(me)) continue
          assigned.add(me)
          if (!groups.has(other)) groups.set(other, [])
          groups.get(other)!.push(e)
        }
      }
      const placed: Record<string, Pos> = {}
      for (const [anchor, list] of groups) {
        const p = cy.getElementById(anchor).position()
        const r = Math.min(220 + list.length * 14, 1600)
        list.forEach((e, i) => {
          const a = (2 * Math.PI * i) / list.length
          placed[e.id] = { x: p.x + r * Math.cos(a), y: p.y + r * Math.sin(a) }
        })
      }
      const ext = cy.extent()
      const center = { x: (ext.x1 + ext.x2) / 2, y: (ext.y1 + ext.y2) / 2 }
      cy.batch(() => {
        for (const e of entities) if (!fresh.has(e.id)) cy.getElementById(e.id).data(nodeData(e))
        cy.add([
          ...[...fresh.values()].map((e) => ({
            group: 'nodes' as const,
            data: nodeData(e),
            position: e.position ?? placed[e.id] ?? { x: center.x + Math.random() * 360 - 180, y: center.y + Math.random() * 360 - 180 },
          })),
          ...links.filter((l) => cy.getElementById(l.id).empty()).map((l) => ({ group: 'edges' as const, data: edgeData(l) })),
        ])
      })
      // Animate newly discovered entities in: fade up (animated) + a brief amber discovery ring. Skip bulk loads.
      // Opacity is the only size/border style the experimental WebGL renderer animates reliably; the ring is a
      // timed flash, and the timeout guarantees cleanup so nodes never get stuck invisible.
      if (fresh.size && fresh.size <= 120 && !REDUCE_MOTION) {
        const added = cy.nodes().filter((n) => fresh.has(n.id()))
        added.style({ opacity: 0, 'border-color': '#f0a63c', 'border-width': 7, 'border-opacity': 1 })
        added.animate({ style: { opacity: 1 } }, { duration: 400, easing: 'ease-out-cubic' })
        setTimeout(() => added.removeStyle('opacity border-width border-color border-opacity'), 850)
      }
      if (Object.keys(placed).length) cb.current.onPositions(placed)
    },
    updateEntity(e) {
      cyRef.current?.getElementById(e.id).data(nodeData(e))
    },
    remove(ids) {
      const cy = cyRef.current!
      cy.batch(() => ids.forEach((id) => cy.getElementById(id).remove()))
    },
    clear() {
      cyRef.current?.elements().remove()
    },
    cancelLayout,
    fit() {
      const cy = cyRef.current!
      fitTo(cy, cy.nodes().map((n) => n.position()))
    },
    select(ids, fit = false) {
      const cy = cyRef.current!
      cy.$(':selected').unselect()
      const sel = ids.reduce((c, id) => c.union(cy.getElementById(id)), cy.collection())
      sel.select()
      if (fit && sel.nonempty()) cy.fit(sel, 80)
    },
    layout(name) {
      const cy = cyRef.current!
      const n = cy.nodes().length
      const sel = cy.$('node:selected')
      cancelLayout() // newest layout wins
      if (n <= INLINE_MAX_NODES) {
        const opts = layoutOptions(name, n, sel.nonempty() ? sel : cy.nodes().roots())
        inline.current = cy.layout({ fit: true, padding: 40, animate: !REDUCE_MOTION, animationDuration: 300, ...opts } as unknown as LayoutOptions)
        inline.current.run()
        return Promise.resolve(true)
      }
      return new Promise((resolve, reject) => {
        const worker = new Worker(new URL('../layoutWorker.ts', import.meta.url), { type: 'module' })
        const done = (applied: boolean) => { worker.terminate(); resolve(applied) }
        job.current = { worker, done }
        worker.onmessage = (e: MessageEvent<Record<string, Pos>>) => {
          job.current = null
          // Nodes added while the worker ran aren't in the result; they keep their current position.
          cy.layout({ name: 'preset', positions: (node: cytoscape.NodeSingular) => e.data[node.id()] ?? node.position(), fit: false } as LayoutOptions).run()
          fitTo(cy, Object.values(e.data))
          done(true)
        }
        worker.onerror = (e) => {
          job.current = null
          worker.terminate()
          reject(new Error(`layout worker: ${e.message}`))
        }
        const msg: LayoutJob = {
          name,
          nodes: cy.nodes().map((x) => x.id()),
          edges: cy.edges().map((x) => [x.source().id(), x.target().id()] as [string, string]),
          roots: sel.map((x) => x.id()),
        }
        worker.postMessage(msg)
      })
    },
  }))

  return (
    <div
      className="relative h-full w-full"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        const type = e.dataTransfer.getData('application/x-entity-type') as EntityType
        const cy = cyRef.current
        if (!type || !cy) return
        e.preventDefault()
        const r = el.current!.getBoundingClientRect()
        const screen = { x: e.clientX - r.left, y: e.clientY - r.top }
        const pan = cy.pan(), z = cy.zoom()
        props.onDropType(type, { x: (screen.x - pan.x) / z, y: (screen.y - pan.y) / z }, screen)
      }}
    >
      <div ref={el} className="h-full w-full" />
      {cyState && <Minimap cy={cyState} />}
    </div>
  )
}

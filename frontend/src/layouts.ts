// Shared by the canvas (small graphs, animated, main thread) and layoutWorker.ts (large graphs, off-thread).
export type LayoutName = 'force' | 'hierarchical' | 'radial' | 'grid'

export const INLINE_MAX_NODES = 300 // below this a worker's startup costs more than the layout itself

export function layoutOptions(name: LayoutName, n: number, roots: unknown) {
  return {
    // fCoSE: spectral init + force-directed refinement; 'draft' (spectral only) for big graphs.
    // Roomy spacing so nodes + their labels don't overlap; tighten a little as the graph grows.
    force: { name: 'fcose', quality: n > 2000 ? 'draft' : 'default', randomize: true, nodeRepulsion: n > 2000 ? 16000 : 24000, idealEdgeLength: n > 2000 ? 110 : 150, nodeSeparation: 160, gravity: 0.2, numIter: 2500 },
    hierarchical: { name: 'dagre', rankDir: 'TB', nodeSep: 55, rankSep: 130, edgeSep: 20 },
    radial: { name: 'breadthfirst', circle: true, directed: true, spacingFactor: 1.6, roots },
    grid: { name: 'grid', avoidOverlap: true, avoidOverlapPadding: 40, condense: false },
  }[name]
}

export interface LayoutJob {
  name: LayoutName
  nodes: string[]
  edges: [string, string][]
  roots: string[] // empty = graph roots (nodes with no incoming links)
}

export type Pos = { x: number; y: number }

// Plain min/max over node centres. cy.boundingBox()/cy.fit() measure every label: ~1s at 10k nodes.
export function bounds(points: Pos[]) {
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity
  for (const p of points) {
    x1 = Math.min(x1, p.x); y1 = Math.min(y1, p.y); x2 = Math.max(x2, p.x); y2 = Math.max(y2, p.y)
  }
  return { x1, y1, x2, y2, w: x2 - x1 || 1, h: y2 - y1 || 1 }
}

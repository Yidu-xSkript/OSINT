// Runs a layout on a headless Cytoscape copy of the graph and posts back {id: {x, y}}, so the UI thread never blocks.
import cytoscape, { type LayoutOptions } from 'cytoscape'
import dagre from 'cytoscape-dagre'
import fcose from 'cytoscape-fcose'
import { layoutOptions, type LayoutJob } from './layouts'

cytoscape.use(dagre)
cytoscape.use(fcose)

self.onmessage = (e: MessageEvent<LayoutJob>) => {
  const { name, nodes, edges, roots } = e.data
  const cy = cytoscape({
    headless: true,
    styleEnabled: true, // layouts need node sizes; match the 30px nodes on the canvas
    style: [{ selector: 'node', style: { width: 30, height: 30 } }],
    elements: [
      ...nodes.map((id) => ({ data: { id } })),
      ...edges.map(([source, target]) => ({ data: { source, target } })),
    ],
  })
  const r = roots.length ? roots.reduce((c, id) => c.union(cy.getElementById(id)), cy.collection()) : cy.nodes().roots()
  cy.layout({ ...layoutOptions(name, nodes.length, r), animate: false, fit: false } as unknown as LayoutOptions).run()
  postMessage(Object.fromEntries(cy.nodes().map((n) => [n.id(), n.position()])))
}

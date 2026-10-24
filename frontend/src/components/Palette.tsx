import { ENTITY_TYPES, type EntityType } from '../types'

export default function Palette({ onAdd }: { onAdd(type: EntityType): void }) {
  return (
    <div>
      <div className="h">Entity Palette</div>
      <p className="mb-2 text-xs text-zinc-500">Drag onto the graph, or click to add.</p>
      {(Object.keys(ENTITY_TYPES) as EntityType[]).map((t) => (
        <div
          key={t}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData('application/x-entity-type', t)
            e.dataTransfer.effectAllowed = 'copy'
          }}
          onClick={() => onAdd(t)}
          className="flex cursor-grab items-center gap-2 rounded px-1.5 py-1 hover:bg-zinc-800"
        >
          <img src={ENTITY_TYPES[t].icon} className="h-5 w-5" alt="" />
          {t}
        </div>
      ))}
    </div>
  )
}

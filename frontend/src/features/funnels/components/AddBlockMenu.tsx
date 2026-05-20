import { Plus } from 'lucide-react'

import { blockGroups, type BlockMenuItem } from '../blockCatalog'

type AddBlockMenuProps = {
  onAdd: (item: BlockMenuItem) => void
}

export default function AddBlockMenu({ onAdd }: AddBlockMenuProps) {
  return (
    <div className="h-full overflow-y-auto rounded-lg border border-white/8 bg-surface/90 p-3">
      <h2 className="px-1 text-sm font-semibold text-white">Добавить блок</h2>
      <div className="mt-3 space-y-4">
        {blockGroups.map((group) => (
          <section key={group.title}>
            <p className="mb-2 px-1 text-xs font-medium uppercase tracking-wide text-gray-500">
              {group.title}
            </p>
            <div className="grid gap-1">
              {group.items.map((item) => (
                <button
                  key={`${item.stepType}:${item.blockType}`}
                  type="button"
                  onClick={() => onAdd(item)}
                  className="flex min-h-9 items-center justify-between gap-2 rounded-lg border border-transparent px-2 py-2 text-left text-sm text-gray-200 transition hover:border-accent-300/25 hover:bg-accent-300/10 hover:text-white"
                >
                  <span className="min-w-0 truncate">{item.label}</span>
                  <Plus size={14} className="shrink-0 text-gray-500" />
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

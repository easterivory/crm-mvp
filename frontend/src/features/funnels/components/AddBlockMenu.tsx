import { Plus } from 'lucide-react'

import { universalBlocks, type BlockMenuItem } from '../blockCatalog'

type AddBlockMenuProps = {
  onAdd: (item: BlockMenuItem) => void
}

export default function AddBlockMenu({ onAdd }: AddBlockMenuProps) {
  return (
    <div className="h-full overflow-y-auto rounded-lg border border-white/8 bg-surface/90 p-3">
      <h2 className="px-1 text-sm font-semibold text-white">Добавить блок</h2>
      <p className="mt-1 px-1 text-xs leading-5 text-gray-500">
        Конкретное поведение настраивается внутри выбранного блока.
      </p>
      <div className="mt-3 grid gap-2">
        {universalBlocks.map((item) => (
          <button
            key={`${item.stepType}:${item.blockType}`}
            type="button"
            onClick={() => onAdd(item)}
            className="flex min-h-[58px] items-start justify-between gap-2 rounded-lg border border-white/8 bg-white/[0.025] px-3 py-2 text-left transition hover:border-accent-300/25 hover:bg-accent-300/10"
          >
            <span className="min-w-0">
              <span className="block text-sm font-medium text-gray-100">{item.label}</span>
              <span className="mt-0.5 block text-xs leading-4 text-gray-500">
                {item.description}
              </span>
            </span>
            <Plus size={14} className="mt-1 shrink-0 text-gray-500" />
          </button>
        ))}
      </div>
    </div>
  )
}

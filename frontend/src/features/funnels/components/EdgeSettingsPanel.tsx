import { Trash2 } from 'lucide-react'

import type { FunnelEdge, FunnelStep } from '../types'

type EdgeSettingsPanelProps = {
  edges: FunnelEdge[]
  steps: FunnelStep[]
  onUpdate: (edgeId: string, patch: Partial<FunnelEdge>) => void
  onRemove: (edgeId: string) => void
}

export default function EdgeSettingsPanel({
  edges,
  steps,
  onUpdate,
  onRemove,
}: EdgeSettingsPanelProps) {
  const titleById = new Map(steps.map((step) => [step.id, step.title]))

  return (
    <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
      <h3 className="text-sm font-semibold text-white">Связи</h3>
      {edges.length === 0 ? (
        <p className="mt-2 text-sm text-gray-500">Связей пока нет.</p>
      ) : (
        <div className="mt-3 space-y-2">
          {edges.map((edge) => (
            <div key={edge.id} className="rounded-lg border border-white/8 bg-background/45 p-2">
              <p className="truncate text-xs text-gray-500">
                {titleById.get(edge.from_step_id) ?? 'Блок'} → {titleById.get(edge.to_step_id) ?? 'Блок'}
              </p>
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="number"
                  value={edge.priority}
                  onChange={(event) =>
                    onUpdate(edge.id, { priority: Number(event.target.value) || 0 })
                  }
                  className="h-8 w-20 rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-100 outline-none"
                  aria-label="Приоритет связи"
                />
                <button
                  type="button"
                  onClick={() => onRemove(edge.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35"
                  title="Удалить связь"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

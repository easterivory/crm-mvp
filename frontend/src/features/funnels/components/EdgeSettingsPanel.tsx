import { ChevronDown, Trash2 } from 'lucide-react'
import { useState } from 'react'

import type { FunnelEdge, FunnelStep } from '../types'
import { funnelStepLabel, funnelStepNumberMap } from '../funnelConfig'

type EdgeSettingsPanelProps = {
  selectedEdge: FunnelEdge | null
  edges: FunnelEdge[]
  steps: FunnelStep[]
  onUpdate: (edgeId: string, patch: Partial<FunnelEdge>) => void
  onRemove: (edgeId: string) => void
  onSelect: (edgeId: string) => void
}

function textValue(value: unknown) {
  return typeof value === 'string' ? value : ''
}

export default function EdgeSettingsPanel({
  selectedEdge,
  edges,
  steps,
  onUpdate,
  onRemove,
  onSelect,
}: EdgeSettingsPanelProps) {
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false)
  const numberById = funnelStepNumberMap(steps)
  const titleById = new Map(
    steps.map((step) => [step.id, funnelStepLabel(step, numberById)]),
  )

  const updateCondition = (patch: Record<string, unknown>) => {
    if (!selectedEdge) {
      return
    }
    onUpdate(selectedEdge.id, {
      condition_json: { ...(selectedEdge.condition_json ?? {}), ...patch },
    })
  }

  return (
    <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
      <h3 className="text-sm font-semibold text-white">Выбранная связь</h3>
      {!selectedEdge ? (
        <p className="mt-2 text-sm text-gray-500">
          Выберите линию на полотне, чтобы изменить подпись или удалить связь.
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          <p className="truncate text-xs text-gray-500">
            {titleById.get(selectedEdge.from_step_id) ?? 'Блок'} →{' '}
            {titleById.get(selectedEdge.to_step_id) ?? 'Блок'}
          </p>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Подпись / исход</span>
            <input
              value={textValue(
                selectedEdge.condition_json?.label ?? selectedEdge.condition_json?.outcome,
              )}
              onChange={(event) =>
                updateCondition({ label: event.target.value, outcome: event.target.value })
              }
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Приоритет</span>
            <input
              type="number"
              value={selectedEdge.priority}
              onChange={(event) =>
                onUpdate(selectedEdge.id, { priority: Number(event.target.value) || 0 })
              }
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
          <button
            type="button"
            onClick={() => onRemove(selectedEdge.id)}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/15 px-3 text-sm text-red-200 transition hover:border-red-300/35"
          >
            <Trash2 size={14} />
            Удалить связь
          </button>
        </div>
      )}

      <button
        type="button"
        onClick={() => setIsAdvancedOpen((value) => !value)}
        className="mt-4 flex w-full items-center justify-between rounded-lg border border-white/8 bg-background/40 px-3 py-2 text-left text-xs text-gray-400"
      >
        <span>Advanced: список связей</span>
        <ChevronDown size={14} className={isAdvancedOpen ? 'rotate-180' : ''} />
      </button>
      {isAdvancedOpen ? (
        <div className="mt-2 max-h-48 space-y-2 overflow-y-auto">
          {edges.length === 0 ? (
            <p className="text-sm text-gray-500">Связей пока нет.</p>
          ) : (
            edges.map((edge) => (
              <button
                key={edge.id}
                type="button"
                onClick={() => onSelect(edge.id)}
                className="block w-full rounded-lg border border-white/8 bg-background/45 p-2 text-left text-xs text-gray-400 transition hover:border-accent-300/25"
              >
                {titleById.get(edge.from_step_id) ?? 'Блок'} →{' '}
                {titleById.get(edge.to_step_id) ?? 'Блок'}
              </button>
            ))
          )}
        </div>
      ) : null}
    </section>
  )
}

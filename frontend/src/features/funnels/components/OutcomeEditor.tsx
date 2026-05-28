import { Plus, Trash2 } from 'lucide-react'

import type { FunnelStep } from '../types'
import { configId, type OutcomeConfig } from '../funnelConfig'
import { TargetSelect } from './ButtonListEditor'

type OutcomeEditorProps = {
  outcomes: OutcomeConfig[]
  currentStepId: string
  steps: FunnelStep[]
  onChange: (outcomes: OutcomeConfig[]) => void
}

export default function OutcomeEditor({
  outcomes,
  currentStepId,
  steps,
  onChange,
}: OutcomeEditorProps) {
  const update = (index: number, patch: Partial<OutcomeConfig>) => {
    onChange(outcomes.map((outcome, idx) => (idx === index ? { ...outcome, ...patch } : outcome)))
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">Выходы</span>
        <button
          type="button"
          onClick={() =>
            onChange([...outcomes, { id: configId('outcome'), label: 'Новый исход', target_step_id: '' }])
          }
          className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить исход
        </button>
      </div>

      {outcomes.map((outcome, index) => {
        const isDefault = ['true', 'false', 'fallback'].includes(outcome.id)
        return (
          <div key={outcome.id} className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-2">
            <div className="flex gap-2">
              <input
                value={outcome.label}
                onChange={(event) => update(index, { label: event.target.value })}
                className="min-w-0 flex-1 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
              <button
                type="button"
                disabled={isDefault}
                onClick={() => onChange(outcomes.filter((_, idx) => idx !== index))}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35 disabled:cursor-not-allowed disabled:opacity-35"
                title={isDefault ? 'Базовый исход нельзя удалить' : 'Удалить исход'}
              >
                <Trash2 size={13} />
              </button>
            </div>
            <TargetSelect
              value={outcome.target_step_id}
              currentStepId={currentStepId}
              steps={steps}
              onChange={(value) => update(index, { target_step_id: value })}
            />
          </div>
        )
      })}
    </div>
  )
}

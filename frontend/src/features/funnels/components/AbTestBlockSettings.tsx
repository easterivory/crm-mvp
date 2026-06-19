import { Plus, Trash2 } from 'lucide-react'

import { configId, normalizeAbVariants, type AbTestVariantConfig } from '../funnelConfig'
import type { FunnelStep } from '../types'
import { TargetSelect } from './ButtonListEditor'

type AbTestBlockSettingsProps = {
  step: FunnelStep
  steps: FunnelStep[]
  onConfigChange: (config: Record<string, unknown>) => void
}

export default function AbTestBlockSettings({
  step,
  steps,
  onConfigChange,
}: AbTestBlockSettingsProps) {
  const variants = normalizeAbVariants(step.config_json.variants)
  const totalWeight = variants.reduce((sum, variant) => sum + variant.weight, 0)

  const updateVariants = (nextVariants: AbTestVariantConfig[]) => {
    onConfigChange({
      ...step.config_json,
      mode: 'ab_test',
      variants: nextVariants,
    })
  }

  const update = (index: number, patch: Partial<AbTestVariantConfig>) => {
    updateVariants(variants.map((variant, idx) => (idx === index ? { ...variant, ...patch } : variant)))
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Варианты A/B
          </span>
          <p className="mt-1 text-xs text-gray-500">Суммарный вес: {totalWeight}%</p>
        </div>
        <button
          type="button"
          onClick={() =>
            updateVariants([
              ...variants,
              {
                id: configId('variant'),
                label: `Вариант ${variants.length + 1}`,
                weight: 0,
                target_step_id: '',
              },
            ])
          }
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      {variants.map((variant, index) => (
        <div key={variant.id} className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-2">
          <div className="flex gap-2">
            <input
              value={variant.label}
              onChange={(event) => update(index, { label: event.target.value })}
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
            <input
              type="number"
              min={0}
              max={100}
              value={variant.weight}
              onChange={(event) => update(index, { weight: Number(event.target.value) || 0 })}
              className="w-24 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
            <button
              type="button"
              disabled={variants.length <= 2}
              onClick={() => updateVariants(variants.filter((_, idx) => idx !== index))}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35 disabled:cursor-not-allowed disabled:opacity-35"
              title="Удалить вариант"
            >
              <Trash2 size={13} />
            </button>
          </div>
          <TargetSelect
            value={variant.target_step_id}
            currentStepId={step.id}
            steps={steps}
            onChange={(value) => update(index, { target_step_id: value })}
          />
        </div>
      ))}
    </div>
  )
}

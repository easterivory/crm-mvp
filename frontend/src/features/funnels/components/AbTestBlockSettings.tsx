import { Plus, Trash2 } from 'lucide-react'

import { configId, normalizeAbVariants, type AbTestVariantConfig } from '../funnelConfig'
import type { FunnelStep } from '../types'
import { TargetSelect } from './ButtonListEditor'

type AbTestBlockSettingsProps = {
  step: FunnelStep
  steps: FunnelStep[]
  onConfigChange: (config: Record<string, unknown>) => void
}

function clampPercent(value: number) {
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, Math.round(value)))
}

function distributeEvenly(variants: AbTestVariantConfig[]) {
  if (variants.length === 0) return variants
  const base = Math.floor(100 / variants.length)
  let remainder = 100 - base * variants.length
  return variants.map((variant) => {
    const weight = base + (remainder > 0 ? 1 : 0)
    remainder -= 1
    return { ...variant, weight }
  })
}

function rebalanceWeights(
  variants: AbTestVariantConfig[],
  lockedIndex: number,
  lockedWeight: number,
) {
  if (variants.length <= 1) {
    return variants.map((variant, index) => ({
      ...variant,
      weight: index === lockedIndex ? 100 : variant.weight,
    }))
  }

  const fixedWeight = clampPercent(lockedWeight)
  const remainingWeight = 100 - fixedWeight
  const unlocked = variants.filter((_, index) => index !== lockedIndex)
  const unlockedTotal = unlocked.reduce((sum, variant) => sum + Math.max(0, variant.weight), 0)
  let remaining = remainingWeight

  return variants.map((variant, index) => {
    if (index === lockedIndex) {
      return { ...variant, weight: fixedWeight }
    }
    const isLastUnlocked = variants.slice(index + 1).every((_, nextIndex) => {
      const originalIndex = index + 1 + nextIndex
      return originalIndex === lockedIndex
    })
    const nextWeight = isLastUnlocked
      ? remaining
      : unlockedTotal > 0
        ? Math.round((Math.max(0, variant.weight) / unlockedTotal) * remainingWeight)
        : Math.floor(remainingWeight / unlocked.length)
    remaining -= nextWeight
    return { ...variant, weight: Math.max(0, nextWeight) }
  })
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

  const updateWeight = (index: number, rawValue: number) => {
    updateVariants(rebalanceWeights(variants, index, rawValue))
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Варианты A/B
          </span>
          <p className="mt-1 text-xs text-gray-500">
            Распределение: {totalWeight}% · веса всегда приводятся к 100%.
          </p>
        </div>
        <button
          type="button"
          onClick={() =>
            updateVariants(distributeEvenly([
              ...variants,
              {
                id: configId('variant'),
                label: `Вариант ${variants.length + 1}`,
                weight: 0,
                target_step_id: '',
              },
            ]))
          }
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-white/8">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-cyan-300 transition-all"
          style={{ width: `${Math.min(totalWeight, 100)}%` }}
        />
      </div>

      {variants.map((variant, index) => (
        <div key={variant.id} className="grid gap-2 rounded-xl border border-white/8 bg-white/[0.03] p-2">
          <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_104px_auto]">
            <input
              value={variant.label}
              onChange={(event) => update(index, { label: event.target.value })}
              className="min-w-0 rounded-lg border border-white/10 bg-background/70 px-2 py-2 text-sm text-gray-100 outline-none"
            />
            <label className="relative block min-w-0">
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={variant.weight}
                onChange={(event) => updateWeight(index, Number(event.target.value))}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-2 pr-7 text-sm text-gray-100 outline-none"
              />
              <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500">
                %
              </span>
            </label>
            <button
              type="button"
              disabled={variants.length <= 2}
              onClick={() => updateVariants(distributeEvenly(variants.filter((_, idx) => idx !== index)))}
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

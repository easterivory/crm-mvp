import { Copy, Plus, Trash2 } from 'lucide-react'

import {
  conditionOperators,
  conditionSources,
  configId,
  leadFields,
  type ConditionRuleConfig,
} from '../funnelConfig'

type VisualRuleBuilderProps = {
  rules: ConditionRuleConfig[]
  onChange: (rules: ConditionRuleConfig[]) => void
}

function fieldOptionsForSource(source: string) {
  if (source === 'lead_field') {
    return leadFields.filter(([value]) => value)
  }
  if (source === 'last_answer') {
    return [['', 'Последний ответ']] as const
  }
  if (source === 'operator_assigned') {
    return [['', 'Назначение']] as const
  }
  return [['', 'ID / код / значение']] as const
}

export default function VisualRuleBuilder({ rules, onChange }: VisualRuleBuilderProps) {
  const update = (index: number, patch: Partial<ConditionRuleConfig>) => {
    onChange(rules.map((rule, idx) => (idx === index ? { ...rule, ...patch } : rule)))
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
          Условия
        </span>
        <button
          type="button"
          onClick={() =>
            onChange([
              ...rules,
              { id: configId('cond'), source: 'last_answer', field: '', operator: 'equals', value: '' },
            ])
          }
          className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить условие
        </button>
      </div>

      {rules.map((rule, index) => {
        const sourceLabel = conditionSources.find(([value]) => value === rule.source)?.[1]
        return (
          <div key={rule.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-2">
            <div className="grid gap-2">
              <select
                value={rule.source}
                onChange={(event) =>
                  update(index, { source: event.target.value, field: '', value: '' })
                }
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                {conditionSources.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>

              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
                <select
                  value={rule.field}
                  onChange={(event) => update(index, { field: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  {fieldOptionsForSource(rule.source).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <select
                  value={rule.operator}
                  onChange={(event) => update(index, { operator: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  {conditionOperators.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              {rule.operator !== 'exists' && rule.operator !== 'empty' ? (
                <input
                  value={rule.value}
                  onChange={(event) => update(index, { value: event.target.value })}
                  placeholder={`${sourceLabel ?? 'Значение'}...`}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              ) : null}

              <div className="flex items-center justify-end gap-1">
                <button
                  type="button"
                  onClick={() => onChange([...rules, { ...rule, id: configId('cond') }])}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-300 transition hover:border-accent-300/35"
                >
                  <Copy size={13} />
                  Дублировать
                </button>
                <button
                  type="button"
                  onClick={() => onChange(rules.filter((_, idx) => idx !== index))}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-red-300/15 px-2 text-xs text-red-200 transition hover:border-red-300/35"
                >
                  <Trash2 size={13} />
                  Удалить
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

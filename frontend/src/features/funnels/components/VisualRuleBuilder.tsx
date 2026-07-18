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
  tags?: Array<{ id: string; name?: string }>
  statuses?: Array<{ id: string; code?: string; name?: string }>
  trackingLinks?: Array<{ id: string; code?: string; title?: string; ref_code?: string }>
  onChange: (rules: ConditionRuleConfig[]) => void
}

function fieldOptionsForSource(source: string) {
  if (source === 'lead_field') {
    return [
      ...leadFields.filter(([value]) => value),
      ['__custom__', 'Произвольное поле'],
    ] as const
  }
  if (source === 'last_answer') {
    return [['', 'Последний ответ']] as const
  }
  if (source === 'hold_mode') {
    return [['', 'Hold-флаг версии']] as const
  }
  if (source === 'operator_assigned') {
    return [['', 'Назначение']] as const
  }
  if (source === 'confidence_score') {
    return [['', 'Score лида, 0–100']] as const
  }
  return [['', 'ID / код / значение']] as const
}

export default function VisualRuleBuilder({
  rules,
  tags = [],
  statuses = [],
  trackingLinks = [],
  onChange,
}: VisualRuleBuilderProps) {
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
        const standardLeadFieldKeys = new Set<string>(
          leadFields.map(([value]) => value).filter(Boolean),
        )
        const isCustomLeadField =
          rule.source === 'lead_field'
          && Boolean(rule.field)
          && !standardLeadFieldKeys.has(rule.field)
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
                  value={isCustomLeadField ? '__custom__' : rule.field}
                  onChange={(event) =>
                    update(index, {
                      field:
                        event.target.value === '__custom__'
                          ? 'custom_field'
                          : event.target.value,
                    })
                  }
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
              {isCustomLeadField ? (
                <input
                  value={rule.field}
                  onChange={(event) =>
                    update(index, {
                      field: event.target.value
                        .toLowerCase()
                        .replace(/[^a-z0-9_]/g, '_')
                        .replace(/^[^a-z]+/, '')
                        .slice(0, 100),
                    })
                  }
                  maxLength={100}
                  placeholder="Ключ произвольного поля"
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              ) : null}

              {rule.operator !== 'exists' && rule.operator !== 'empty' ? (
                <RuleValueInput
                  rule={rule}
                  tags={tags}
                  statuses={statuses}
                  trackingLinks={trackingLinks}
                  placeholder={`${sourceLabel ?? 'Значение'}...`}
                  onChange={(value) => update(index, { value })}
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

function RuleValueInput({
  rule,
  tags,
  statuses,
  trackingLinks,
  placeholder,
  onChange,
}: {
  rule: ConditionRuleConfig
  tags: Array<{ id: string; name?: string }>
  statuses: Array<{ id: string; code?: string; name?: string }>
  trackingLinks: Array<{ id: string; code?: string; title?: string; ref_code?: string }>
  placeholder: string
  onChange: (value: string) => void
}) {
  if (rule.source === 'tag') {
    return (
      <select
        value={rule.value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
      >
        <option value="">Выберите тег</option>
        {tags.map((tag) => (
          <option key={tag.id} value={tag.id}>
            {tag.name}
          </option>
        ))}
      </select>
    )
  }

  if (rule.source === 'status') {
    return (
      <select
        value={rule.value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
      >
        <option value="">Выберите статус</option>
        {statuses.map((status) => (
          <option key={status.id} value={status.code ?? ''}>
            {status.name ?? status.code}
          </option>
        ))}
      </select>
    )
  }

  if (rule.source === 'tracking_link') {
    return (
      <select
        value={rule.value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
      >
        <option value="">Выберите ссылку</option>
        {trackingLinks.map((link) => {
          const value = link.ref_code ?? link.code ?? link.id
          return (
            <option key={link.id} value={value}>
              {link.title ?? link.code ?? link.ref_code}
            </option>
          )
        })}
      </select>
    )
  }

  if (rule.source === 'hold_mode' || rule.source === 'operator_assigned') {
    return (
      <select
        value={rule.value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
      >
        <option value="true">Да</option>
        <option value="false">Нет</option>
      </select>
    )
  }

  if (rule.source === 'confidence_score') {
    return (
      <input
        type="number"
        min={0}
        max={100}
        step={1}
        value={rule.value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="80"
        className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
      />
    )
  }

  return (
    <input
      value={rule.value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
    />
  )
}

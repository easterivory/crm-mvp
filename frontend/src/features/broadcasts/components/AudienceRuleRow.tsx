import { Trash2 } from 'lucide-react'

import type { AudienceRule, BroadcastOption } from '../types'

type AudienceRuleRowProps = {
  rule: AudienceRule
  tags: BroadcastOption[]
  statuses: BroadcastOption[]
  trackingLinks: BroadcastOption[]
  users: BroadcastOption[]
  bots: BroadcastOption[]
  funnels: BroadcastOption[]
  onChange: (rule: AudienceRule) => void
  onRemove: () => void
}

const fields = [
  ['tag', 'Тег'],
  ['lead_status', 'Статус лида'],
  ['funnel_state', 'Состояние воронки'],
  ['funnel_id', 'Воронка'],
  ['completed_funnel_id', 'Завершил воронку'],
  ['current_step_id', 'Текущий шаг'],
  ['not_in_funnel', 'Не в воронке'],
  ['tracking_link', 'Ссылка / источник'],
  ['assigned_user', 'Менеджер'],
  ['last_message_at', 'Последнее сообщение'],
  ['created_at', 'Дата добавления'],
  ['has_unanswered_incoming', 'Не отвечено'],
  ['bot_id', 'Бот'],
  ['custom_field', 'Произвольное поле'],
]

const operators = [
  ['equals', 'равно'],
  ['not_equals', 'не равно'],
  ['in', 'в списке'],
  ['not_in', 'не в списке'],
  ['exists', 'заполнено'],
  ['empty', 'пусто'],
  ['before', 'до'],
  ['after', 'после'],
  ['between', 'между'],
  ['gt', 'больше'],
  ['lt', 'меньше'],
]

const funnelStates = [
  ['in_funnel', 'В воронке'],
  ['waiting_for_answer', 'Ждёт ответ'],
  ['completed', 'Завершил воронку'],
  ['manual', 'Ручная обработка'],
]

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : []
}

function ChipMulti({
  options,
  values,
  onChange,
}: {
  options: BroadcastOption[]
  values: string[]
  onChange: (values: string[]) => void
}) {
  if (options.length === 0) {
    return <p className="text-xs text-gray-500">Нет доступных значений.</p>
  }
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => {
        const active = values.includes(option.id)
        return (
          <button
            key={option.id}
            type="button"
            onClick={() =>
              onChange(active ? values.filter((id) => id !== option.id) : [...values, option.id])
            }
            className={`rounded-full border px-3 py-1 text-xs transition ${
              active
                ? 'border-accent-300/50 bg-accent-300/15 text-accent-50'
                : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-white/20'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

export default function AudienceRuleRow({
  rule,
  tags,
  statuses,
  trackingLinks,
  users,
  bots,
  funnels,
  onChange,
  onRemove,
}: AudienceRuleRowProps) {
  const valueArray = asStringArray(rule.value)

  const renderValue = () => {
    if (rule.operator === 'exists' || rule.operator === 'empty') {
      return null
    }
    if (rule.field === 'tag') {
      return <ChipMulti options={tags} values={valueArray} onChange={(value) => onChange({ ...rule, value })} />
    }
    if (rule.field === 'lead_status') {
      return <ChipMulti options={statuses} values={valueArray} onChange={(value) => onChange({ ...rule, value })} />
    }
    if (rule.field === 'funnel_state') {
      return (
        <ChipMulti
          options={funnelStates.map(([id, label]) => ({ id, label }))}
          values={valueArray}
          onChange={(value) => onChange({ ...rule, value })}
        />
      )
    }
    if (rule.field === 'funnel_id' || rule.field === 'completed_funnel_id') {
      return <ChipMulti options={funnels} values={valueArray} onChange={(value) => onChange({ ...rule, value })} />
    }
    if (rule.field === 'not_in_funnel') {
      return (
        <select
          value={String(rule.value ?? true)}
          onChange={(event) => onChange({ ...rule, value: event.target.value === 'true' })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          <option value="true">Да</option>
          <option value="false">Нет</option>
        </select>
      )
    }
    if (rule.field === 'tracking_link') {
      return (
        <select
          value={String(rule.value || '')}
          onChange={(event) => onChange({ ...rule, value: event.target.value })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          <option value="">Выберите ссылку</option>
          {trackingLinks.map((option) => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </select>
      )
    }
    if (rule.field === 'assigned_user') {
      return (
        <select
          value={String(rule.value || '')}
          onChange={(event) => onChange({ ...rule, value: event.target.value })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          <option value="">Выберите менеджера</option>
          {users.map((option) => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </select>
      )
    }
    if (rule.field === 'bot_id') {
      return (
        <select
          value={String(rule.value || '')}
          onChange={(event) => onChange({ ...rule, value: event.target.value })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          <option value="">Выберите бота</option>
          {bots.map((option) => (
            <option key={option.id} value={option.id}>{option.label}</option>
          ))}
        </select>
      )
    }
    if (rule.field === 'has_unanswered_incoming') {
      return (
        <select
          value={String(rule.value ?? true)}
          onChange={(event) => onChange({ ...rule, value: event.target.value === 'true' })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          <option value="true">Да</option>
          <option value="false">Нет</option>
        </select>
      )
    }
    if (rule.operator === 'between') {
      const values = valueArray
      return (
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            type={rule.field.includes('_at') ? 'date' : 'text'}
            value={values[0] ?? ''}
            onChange={(event) => onChange({ ...rule, value: [event.target.value, values[1] ?? ''] })}
            className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
          />
          <input
            type={rule.field.includes('_at') ? 'date' : 'text'}
            value={values[1] ?? ''}
            onChange={(event) => onChange({ ...rule, value: [values[0] ?? '', event.target.value] })}
            className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
          />
        </div>
      )
    }
    return (
      <div className="grid gap-2 sm:grid-cols-[140px_minmax(0,1fr)]">
        {rule.field === 'custom_field' ? (
          <input
            value={rule.custom_field ?? ''}
            onChange={(event) => onChange({ ...rule, custom_field: event.target.value })}
            placeholder="Поле"
            className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
          />
        ) : null}
        <input
          type={rule.field.includes('_at') ? 'date' : 'text'}
          value={String(rule.value ?? '')}
          onChange={(event) => onChange({ ...rule, value: event.target.value })}
          placeholder="Значение"
          className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        />
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <select
          value={rule.field}
          onChange={(event) => onChange({ ...rule, field: event.target.value, value: [] })}
          className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          {fields.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <select
          value={rule.operator}
          onChange={(event) => onChange({ ...rule, operator: event.target.value })}
          className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
        >
          {operators.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={onRemove}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35"
        >
          <Trash2 size={15} />
        </button>
      </div>
      <div className="mt-3">{renderValue()}</div>
    </div>
  )
}

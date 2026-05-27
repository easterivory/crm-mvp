import { X } from 'lucide-react'

import type { ChatFiltersState, FilterOption } from '../types'

type ChatFilterChipsProps = {
  filters: ChatFiltersState
  trackingOptions: FilterOption[]
  tagOptions: FilterOption[]
  statusOptions: FilterOption[]
  userOptions: FilterOption[]
  onChange: (filters: ChatFiltersState) => void
  onReset: () => void
}

const funnelLabels: Record<string, string> = {
  in_funnel: 'В воронке',
  waiting_for_answer: 'Ждёт ответ',
  completed: 'Завершил воронку',
  manual: 'Ручная обработка',
}

const dateLabels: Record<string, string> = {
  today: 'Сегодня',
  yesterday: 'Вчера',
  '7d': '7 дней',
  '30d': '30 дней',
}

function optionLabel(options: FilterOption[], id: string, fallback: string) {
  return options.find((option) => option.id === id)?.label ?? fallback
}

export default function ChatFilterChips({
  filters,
  trackingOptions,
  tagOptions,
  statusOptions,
  userOptions,
  onChange,
  onReset,
}: ChatFilterChipsProps) {
  const chips: Array<{ key: string; label: string; remove: () => void }> = []

  if (filters.q.trim()) {
    chips.push({
      key: 'q',
      label: `Поиск: ${filters.q.trim()}`,
      remove: () => onChange({ ...filters, q: '' }),
    })
  }
  if (filters.hasUnansweredIncoming) {
    chips.push({
      key: 'unanswered',
      label: 'Не отвечено',
      remove: () =>
        onChange({
          ...filters,
          hasUnansweredIncoming: false,
          quickFilter: filters.quickFilter === 'unanswered' ? '' : filters.quickFilter,
        }),
    })
  }
  if (filters.isRed) {
    chips.push({
      key: 'hot',
      label: 'Горячие',
      remove: () =>
        onChange({
          ...filters,
          isRed: false,
          quickFilter: filters.quickFilter === 'hot' ? '' : filters.quickFilter,
        }),
    })
  }
  if (filters.trackingLinkId) {
    chips.push({
      key: 'tracking',
      label: `Ссылка: ${optionLabel(trackingOptions, filters.trackingLinkId, 'выбрана')}`,
      remove: () => onChange({ ...filters, trackingLinkId: '' }),
    })
  }
  if (filters.dateFrom || filters.dateTo) {
    chips.push({
      key: 'date',
      label:
        filters.datePreset && filters.datePreset !== 'custom'
          ? `Дата: ${dateLabels[filters.datePreset]}`
          : `Дата: ${filters.dateFrom || '...'} - ${filters.dateTo || '...'}`,
      remove: () => onChange({ ...filters, datePreset: '', dateFrom: '', dateTo: '' }),
    })
  }
  if (filters.tagIds.length > 0) {
    const tagNames = filters.tagIds
      .map((tagId) => optionLabel(tagOptions, tagId, tagId.slice(0, 8)))
      .join(', ')
    chips.push({
      key: 'tags',
      label: `Теги: ${tagNames} · ${filters.tagMode === 'all' ? 'все' : 'любой'}`,
      remove: () => onChange({ ...filters, tagIds: [], tagMode: 'any' }),
    })
  }
  for (const status of filters.leadStatuses) {
    chips.push({
      key: `status-${status}`,
      label: `Статус: ${optionLabel(statusOptions, status, status)}`,
      remove: () =>
        onChange({
          ...filters,
          leadStatuses: filters.leadStatuses.filter((item) => item !== status),
        }),
    })
  }
  if (filters.funnelState) {
    chips.push({
      key: 'funnel',
      label: `Воронка: ${funnelLabels[filters.funnelState]}`,
      remove: () => onChange({ ...filters, funnelState: '' }),
    })
  }
  if (filters.assignedUserId) {
    chips.push({
      key: 'manager',
      label: `Менеджер: ${optionLabel(userOptions, filters.assignedUserId, 'выбран')}`,
      remove: () =>
        onChange({
          ...filters,
          assignedUserId: '',
          quickFilter: filters.quickFilter === 'mine' ? '' : filters.quickFilter,
        }),
    })
  }
  if (filters.unassigned) {
    chips.push({
      key: 'unassigned',
      label: 'Без менеджера',
      remove: () => onChange({ ...filters, unassigned: false, quickFilter: '' }),
    })
  }

  if (chips.length === 0) {
    return null
  }

  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex h-7 shrink-0 items-center gap-1 rounded-full border border-accent-300/20 bg-accent-400/10 pl-2.5 pr-1 text-xs text-accent-50"
        >
          {chip.label}
          <button
            type="button"
            onClick={chip.remove}
            className="inline-flex h-5 w-5 items-center justify-center rounded-full transition hover:bg-white/10"
            title="Убрать фильтр"
          >
            <X size={12} />
          </button>
        </span>
      ))}
      <button
        type="button"
        onClick={onReset}
        className="h-7 shrink-0 rounded-full border border-white/10 px-2.5 text-xs text-gray-300 transition hover:border-red-300/35 hover:text-red-100"
      >
        Сбросить всё
      </button>
    </div>
  )
}

import { X } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { ChatDatePreset, ChatFiltersState, FilterOption } from '../types'

type ChatFiltersPanelProps = {
  isOpen: boolean
  filters: ChatFiltersState
  trackingOptions: FilterOption[]
  tagOptions: FilterOption[]
  statusOptions: FilterOption[]
  userOptions: FilterOption[]
  onApply: (filters: ChatFiltersState) => void
  onClose: () => void
  onReset: () => void
}

const funnelOptions = [
  { id: '', label: 'Любое состояние' },
  { id: 'in_funnel', label: 'В воронке' },
  { id: 'waiting_for_answer', label: 'Ждёт ответ' },
  { id: 'completed', label: 'Завершил воронку' },
  { id: 'manual', label: 'Ручная обработка' },
]

const datePresets: Array<{ id: ChatDatePreset; label: string }> = [
  { id: '', label: 'Любая дата' },
  { id: 'today', label: 'Сегодня' },
  { id: 'yesterday', label: 'Вчера' },
  { id: '7d', label: '7 дней' },
  { id: '30d', label: '30 дней' },
  { id: 'custom', label: 'Период' },
]

function isoDate(offsetDays = 0) {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  return date.toISOString().slice(0, 10)
}

function presetRange(preset: ChatDatePreset) {
  if (preset === 'today') {
    const today = isoDate()
    return { dateFrom: today, dateTo: today }
  }
  if (preset === 'yesterday') {
    const yesterday = isoDate(-1)
    return { dateFrom: yesterday, dateTo: yesterday }
  }
  if (preset === '7d') {
    return { dateFrom: isoDate(-6), dateTo: isoDate() }
  }
  if (preset === '30d') {
    return { dateFrom: isoDate(-29), dateTo: isoDate() }
  }
  return { dateFrom: '', dateTo: '' }
}

export default function ChatFiltersPanel({
  isOpen,
  filters,
  trackingOptions,
  tagOptions,
  statusOptions,
  userOptions,
  onApply,
  onClose,
  onReset,
}: ChatFiltersPanelProps) {
  const [draft, setDraft] = useState(filters)

  useEffect(() => {
    if (isOpen) {
      setDraft(filters)
    }
  }, [filters, isOpen])

  if (!isOpen) {
    return null
  }

  const setPreset = (datePreset: ChatDatePreset) => {
    const range = presetRange(datePreset)
    setDraft({
      ...draft,
      datePreset,
      dateFrom: datePreset === 'custom' ? draft.dateFrom : range.dateFrom,
      dateTo: datePreset === 'custom' ? draft.dateTo : range.dateTo,
    })
  }

  return (
    <div className="fixed inset-0 z-40 xl:absolute xl:inset-auto xl:left-4 xl:right-4 xl:top-[152px]">
      <button
        type="button"
        aria-label="Закрыть фильтры"
        onClick={onClose}
        className="absolute inset-0 bg-black/45 xl:hidden"
      />
      <div className="absolute inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto rounded-t-2xl border border-white/10 bg-surface p-4 shadow-2xl xl:static xl:max-h-[calc(100dvh-220px)] xl:rounded-xl xl:bg-surface/98">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-white">Фильтры чатов</h2>
            <p className="text-xs text-gray-500">Дата добавления: current cycle, иначе дата создания.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-gray-300"
          >
            <X size={15} />
          </button>
        </div>

        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Ссылка / источник</span>
            <select
              value={draft.trackingLinkId}
              onChange={(event) => setDraft({ ...draft, trackingLinkId: event.target.value })}
              className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none"
            >
              <option value="">Все источники</option>
              {trackingOptions.map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>

          <div>
            <span className="mb-1 block text-xs text-gray-500">Дата</span>
            <div className="grid grid-cols-2 gap-2">
              {datePresets.map((preset) => (
                <button
                  key={preset.id || 'all'}
                  type="button"
                  onClick={() => setPreset(preset.id)}
                  className={`h-8 rounded-lg border px-2 text-xs transition ${
                    draft.datePreset === preset.id
                      ? 'border-accent-300/45 bg-accent-400/10 text-accent-50'
                      : 'border-white/10 bg-white/[0.03] text-gray-400 hover:text-gray-100'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {draft.datePreset === 'custom' ? (
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Дата с</span>
                <input
                  type="date"
                  value={draft.dateFrom}
                  onChange={(event) => setDraft({ ...draft, dateFrom: event.target.value })}
                  className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Дата до</span>
                <input
                  type="date"
                  value={draft.dateTo}
                  onChange={(event) => setDraft({ ...draft, dateTo: event.target.value })}
                  className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none"
                />
              </label>
            </div>
          ) : null}

          <MultiSelect
            label="Теги"
            options={tagOptions}
            values={draft.tagIds}
            onChange={(tagIds) => setDraft({ ...draft, tagIds })}
          />

          <MultiSelect
            label="Статусы"
            options={statusOptions}
            values={draft.leadStatuses}
            onChange={(leadStatuses) => setDraft({ ...draft, leadStatuses })}
          />

          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Воронка</span>
            <select
              value={draft.funnelState}
              onChange={(event) =>
                setDraft({ ...draft, funnelState: event.target.value as ChatFiltersState['funnelState'] })
              }
              className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none"
            >
              {funnelOptions.map((option) => (
                <option key={option.id || 'any'} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Менеджер</span>
            <select
              value={draft.unassigned ? '__unassigned__' : draft.assignedUserId}
              onChange={(event) => {
                if (event.target.value === '__unassigned__') {
                  setDraft({ ...draft, assignedUserId: '', unassigned: true })
                  return
                }
                setDraft({ ...draft, assignedUserId: event.target.value, unassigned: false })
              }}
              className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none"
            >
              <option value="">Все менеджеры</option>
              <option value="__unassigned__">Без менеджера</option>
              {userOptions.map((option) => (
                <option key={option.id} value={option.id}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm text-gray-200">
            <input
              type="checkbox"
              checked={draft.hasUnansweredIncoming}
              onChange={(event) =>
                setDraft({ ...draft, hasUnansweredIncoming: event.target.checked })
              }
            />
            Только не отвеченные
          </label>
        </div>

        <div className="mt-5 grid grid-cols-3 gap-2">
          <button
            type="button"
            onClick={() => {
              onReset()
              onClose()
            }}
            className="h-10 rounded-xl border border-white/10 text-sm text-gray-300"
          >
            Сбросить
          </button>
          <button
            type="button"
            onClick={onClose}
            className="h-10 rounded-xl border border-white/10 text-sm text-gray-300"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={() => {
              onApply(draft)
              onClose()
            }}
            className="h-10 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 text-sm font-semibold text-white"
          >
            Применить
          </button>
        </div>
      </div>
    </div>
  )
}

function MultiSelect({
  label,
  options,
  values,
  onChange,
}: {
  label: string
  options: FilterOption[]
  values: string[]
  onChange: (values: string[]) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-gray-500">{label}</span>
      <select
        multiple
        value={values}
        onChange={(event) =>
          onChange(Array.from(event.target.selectedOptions, (option) => option.value))
        }
        className="min-h-20 w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1 text-sm text-gray-200 outline-none"
      >
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
        ))}
      </select>
    </label>
  )
}

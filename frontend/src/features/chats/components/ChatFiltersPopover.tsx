import { RefreshCw, Save, Search, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import type {
  ChatDatePreset,
  ChatFilterPreset,
  ChatFiltersState,
  FilterOption,
} from '../types'

type ChatFiltersPopoverProps = {
  canManageSharedPresets: boolean
  currentUserId: string | null
  filterPresets: ChatFilterPreset[]
  filters: ChatFiltersState
  isOpen: boolean
  isSelectedPresetDirty: boolean
  selectedPresetId: string
  statusOptions: FilterOption[]
  tagOptions: FilterOption[]
  trackingOptions: FilterOption[]
  userOptions: FilterOption[]
  onApply: (filters: ChatFiltersState) => void
  onApplyPreset: (preset: ChatFilterPreset) => void
  onClose: () => void
  onDeletePreset: (presetId: string) => void
  onReset: () => void
  onSavePreset: (name: string, isShared: boolean, filters: ChatFiltersState) => void
  onUpdatePreset: (presetId: string) => void
}

const funnelOptions = [
  { id: 'in_funnel', label: 'В воронке' },
  { id: 'waiting_for_answer', label: 'Ждёт ответ' },
  { id: 'completed', label: 'Завершил воронку' },
  { id: 'manual', label: 'Ручная обработка' },
]

const datePresets: Array<{ id: ChatDatePreset; label: string }> = [
  { id: '', label: 'Все даты' },
  { id: 'today', label: 'Сегодня' },
  { id: 'yesterday', label: 'Вчера' },
  { id: '7d', label: '7 дней' },
  { id: '30d', label: '30 дней' },
  { id: 'custom', label: 'Произвольно' },
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

function withoutSearch(filters: ChatFiltersState) {
  return {
    ...filters,
    assignedUserId: '',
    dateFrom: '',
    datePreset: '' as ChatDatePreset,
    dateTo: '',
    funnelState: '' as ChatFiltersState['funnelState'],
    hasUnansweredIncoming: false,
    isRed: false,
    leadStatuses: [] as string[],
    quickFilter: '' as const,
    tagIds: [] as string[],
    tagMode: 'any' as const,
    trackingLinkId: '',
    unassigned: false,
  }
}

export default function ChatFiltersPopover({
  canManageSharedPresets,
  currentUserId,
  filterPresets,
  filters,
  isOpen,
  isSelectedPresetDirty,
  selectedPresetId,
  statusOptions,
  tagOptions,
  trackingOptions,
  userOptions,
  onApply,
  onApplyPreset,
  onClose,
  onDeletePreset,
  onReset,
  onSavePreset,
  onUpdatePreset,
}: ChatFiltersPopoverProps) {
  const [draft, setDraft] = useState(filters)
  const [trackingSearch, setTrackingSearch] = useState('')
  const [presetName, setPresetName] = useState('')
  const [presetShared, setPresetShared] = useState(false)

  const selectedPreset = useMemo(
    () => filterPresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [filterPresets, selectedPresetId],
  )

  useEffect(() => {
    if (isOpen) {
      setDraft(filters)
      setTrackingSearch('')
      setPresetName('')
      setPresetShared(false)
    }
  }, [filters, isOpen])

  useEffect(() => {
    if (!isOpen) {
      return undefined
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const filteredTrackingOptions = useMemo(() => {
    const needle = trackingSearch.trim().toLowerCase()
    if (!needle) {
      return trackingOptions
    }
    return trackingOptions.filter((option) =>
      option.label.toLowerCase().includes(needle),
    )
  }, [trackingOptions, trackingSearch])

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

  const apply = () => {
    onApply(draft)
    onClose()
  }

  const reset = () => {
    onReset()
    onClose()
  }

  const savePreset = () => {
    const name = presetName.trim()
    if (!name) {
      return
    }
    onSavePreset(name, presetShared, draft)
    setPresetName('')
    setPresetShared(false)
  }

  return (
    <div className="fixed inset-0 z-40 xl:absolute xl:inset-0">
      <button
        type="button"
        aria-label="Закрыть фильтры"
        onClick={onClose}
        className="absolute inset-0 bg-black/45 xl:bg-transparent"
      />

      <div className="absolute inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto rounded-t-2xl border border-white/10 bg-surface p-4 shadow-2xl xl:bottom-auto xl:left-4 xl:right-4 xl:top-[118px] xl:max-h-[calc(100dvh-170px)] xl:rounded-xl xl:bg-surface/98">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-white">Фильтры</h2>
            <p className="text-xs text-gray-500">
              Дата добавления: текущий цикл, затем дата создания.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-accent-300/40"
            title="Закрыть"
          >
            <X size={15} />
          </button>
        </div>

        <section className="mb-4 rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-gray-400">Шаблоны</span>
            {isSelectedPresetDirty && selectedPreset ? (
              <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-xs text-amber-200">
                изменён
              </span>
            ) : null}
          </div>

          <select
            value={selectedPresetId}
            onChange={(event) => {
              const preset = filterPresets.find((item) => item.id === event.target.value)
              if (preset) {
                setDraft(preset.filters_json)
                onApplyPreset(preset)
              }
            }}
            className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none"
          >
            <option value="">Выберите шаблон</option>
            {filterPresets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.is_shared ? 'Общий · ' : ''}{preset.name}
              </option>
            ))}
          </select>

          {selectedPreset ? (
            <div className="mt-2 grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => onUpdatePreset(selectedPreset.id)}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-white/10 text-xs text-gray-200 transition hover:border-accent-300/40"
              >
                <RefreshCw size={13} />
                Обновить шаблон
              </button>
              <button
                type="button"
                onClick={() => {
                  if (window.confirm('Удалить шаблон фильтра?')) {
                    onDeletePreset(selectedPreset.id)
                  }
                }}
                className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-white/10 text-xs text-red-100 transition hover:border-red-300/40"
              >
                <Trash2 size={13} />
                Удалить шаблон
              </button>
            </div>
          ) : null}

          <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto] gap-2">
            <input
              value={presetName}
              onChange={(event) => setPresetName(event.target.value)}
              placeholder="Название фильтра"
              className="h-9 min-w-0 rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-100 outline-none placeholder:text-gray-600"
            />
            <button
              type="button"
              onClick={savePreset}
              disabled={!presetName.trim()}
              className="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border border-accent-300/30 px-2 text-xs text-accent-50 transition hover:bg-accent-400/10 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Save size={13} />
              Сохранить фильтр
            </button>
          </div>
          {canManageSharedPresets ? (
            <label className="mt-2 flex items-center gap-2 text-xs text-gray-300">
              <input
                type="checkbox"
                checked={presetShared}
                onChange={(event) => setPresetShared(event.target.checked)}
              />
              Общий для проекта
            </label>
          ) : null}
        </section>

        <div className="space-y-4">
          <section className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-gray-400">Ссылка / источник</span>
              {draft.trackingLinkId ? (
                <button
                  type="button"
                  onClick={() => setDraft({ ...draft, trackingLinkId: '' })}
                  className="text-xs text-gray-500 transition hover:text-gray-200"
                >
                  Все ссылки
                </button>
              ) : null}
            </div>
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                value={trackingSearch}
                onChange={(event) => setTrackingSearch(event.target.value)}
                placeholder="Найти ссылку"
                className="h-9 w-full rounded-lg border border-white/10 bg-background/70 pl-8 pr-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-accent-300/50"
              />
            </div>
            <div className="max-h-32 overflow-y-auto rounded-lg border border-white/8 bg-background/35 p-1">
              <button
                type="button"
                onClick={() => setDraft({ ...draft, trackingLinkId: '' })}
                className={`mb-1 flex h-8 w-full items-center rounded-md px-2 text-left text-xs transition ${
                  !draft.trackingLinkId
                    ? 'bg-accent-400/12 text-accent-50'
                    : 'text-gray-400 hover:bg-white/[0.04] hover:text-gray-100'
                }`}
              >
                Все ссылки
              </button>
              {filteredTrackingOptions.length > 0 ? (
                filteredTrackingOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setDraft({ ...draft, trackingLinkId: option.id })}
                    className={`flex min-h-8 w-full items-center rounded-md px-2 text-left text-xs transition ${
                      draft.trackingLinkId === option.id
                        ? 'bg-accent-400/12 text-accent-50'
                        : 'text-gray-400 hover:bg-white/[0.04] hover:text-gray-100'
                    }`}
                  >
                    <span className="truncate">{option.label}</span>
                  </button>
                ))
              ) : (
                <p className="px-2 py-3 text-xs text-gray-500">Ссылок нет</p>
              )}
            </div>
          </section>

          <section className="space-y-2">
            <span className="text-xs font-medium text-gray-400">Дата</span>
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
          </section>

          <SelectableChipGroup
            emptyLabel="Тегов нет"
            label="Теги"
            options={tagOptions}
            values={draft.tagIds}
            onChange={(tagIds) =>
              setDraft({ ...draft, tagIds, tagMode: tagIds.length > 1 ? draft.tagMode : 'any' })
            }
          />

          {draft.tagIds.length > 1 ? (
            <div className="grid grid-cols-2 gap-2">
              {[
                ['any', 'Любой тег'],
                ['all', 'Все теги'],
              ].map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setDraft({ ...draft, tagMode: mode as ChatFiltersState['tagMode'] })}
                  className={`h-8 rounded-lg border px-2 text-xs transition ${
                    draft.tagMode === mode
                      ? 'border-accent-300/45 bg-accent-400/10 text-accent-50'
                      : 'border-white/10 bg-white/[0.03] text-gray-400 hover:text-gray-100'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}

          <SelectableChipGroup
            emptyLabel="Статусов нет"
            label="Статусы"
            options={statusOptions}
            values={draft.leadStatuses}
            onChange={(leadStatuses) => setDraft({ ...draft, leadStatuses })}
          />

          <SelectableChipGroup
            label="Состояние воронки"
            options={funnelOptions}
            values={draft.funnelState ? [draft.funnelState] : []}
            single
            onChange={(values) =>
              setDraft({
                ...draft,
                funnelState: (values[0] ?? '') as ChatFiltersState['funnelState'],
              })
            }
          />

          <SelectableChipGroup
            label="Менеджер"
            options={[
              ...(currentUserId ? [{ id: '__me__', label: 'Мои' }] : []),
              { id: '__unassigned__', label: 'Без менеджера' },
              ...userOptions.filter((option) => option.id !== currentUserId),
            ]}
            values={
              draft.unassigned
                ? ['__unassigned__']
                : currentUserId && draft.assignedUserId === currentUserId
                  ? ['__me__']
                  : draft.assignedUserId
                    ? [draft.assignedUserId]
                    : []
            }
            single
            onChange={(values) => {
              const value = values[0] ?? ''
              setDraft({
                ...draft,
                assignedUserId:
                  value === '__me__'
                    ? currentUserId ?? ''
                    : value && value !== '__unassigned__'
                      ? value
                      : '',
                quickFilter: '',
                unassigned: value === '__unassigned__',
              })
            }}
          />

          <label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-gray-200">
            <span>Не отвечено</span>
            <input
              type="checkbox"
              checked={draft.hasUnansweredIncoming}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  hasUnansweredIncoming: event.target.checked,
                  quickFilter: '',
                })
              }
            />
          </label>
        </div>

        <div className="mt-5 grid grid-cols-3 gap-2">
          <button
            type="button"
            onClick={() => setDraft(withoutSearch(draft))}
            className="h-10 rounded-xl border border-white/10 text-sm text-gray-300 transition hover:border-red-300/35 hover:text-red-100"
          >
            Очистить
          </button>
          <button
            type="button"
            onClick={onClose}
            className="h-10 rounded-xl border border-white/10 text-sm text-gray-300 transition hover:border-accent-300/40"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={apply}
            className="h-10 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent"
          >
            Применить
          </button>
        </div>

        <button
          type="button"
          onClick={reset}
          className="mt-2 h-9 w-full rounded-xl text-xs text-gray-500 transition hover:text-gray-200"
        >
          Сбросить всё вместе с поиском
        </button>
      </div>
    </div>
  )
}

function SelectableChipGroup({
  emptyLabel,
  label,
  options,
  single = false,
  values,
  onChange,
}: {
  emptyLabel?: string
  label: string
  options: FilterOption[]
  single?: boolean
  values: string[]
  onChange: (values: string[]) => void
}) {
  const selected = new Set(values)

  const toggle = (id: string) => {
    if (single) {
      onChange(selected.has(id) ? [] : [id])
      return
    }
    if (selected.has(id)) {
      onChange(values.filter((value) => value !== id))
      return
    }
    onChange([...values, id])
  }

  return (
    <section className="space-y-2">
      <span className="text-xs font-medium text-gray-400">{label}</span>
      {options.length === 0 ? (
        <p className="rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-xs text-gray-500">
          {emptyLabel ?? 'Нет вариантов'}
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {options.map((option) => {
            const isActive = selected.has(option.id)
            return (
              <button
                key={option.id}
                type="button"
                onClick={() => toggle(option.id)}
                className={`min-h-8 max-w-full rounded-full border px-3 text-xs font-medium transition ${
                  isActive
                    ? 'border-accent-300/45 bg-accent-400/12 text-accent-50'
                    : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-accent-300/35 hover:text-gray-100'
                }`}
              >
                <span className="block truncate">{option.label}</span>
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

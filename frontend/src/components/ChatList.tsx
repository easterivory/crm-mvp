import { Filter, LoaderCircle, RefreshCw, RotateCcw, UserRound } from 'lucide-react'

export type Chat = {
  id: string
  project_id: string
  bot_id: string | null
  external_chat_id: string
  external_user_id: string
  contact_name: string | null
  last_message_at: string | null
  last_user_message_at: string | null
  last_manager_reply_at: string | null
  last_incoming_at: string | null
  last_outgoing_at: string | null
  last_read_at: string | null
  unread: boolean
  unanswered: boolean
  has_unanswered_incoming: boolean
  is_red: boolean
  active_funnel_id: string | null
  active_funnel_name: string | null
  active_funnel_version_id: string | null
  active_funnel_version_number: number | null
  active_funnel_version_status: string | null
  current_step_id: string | null
  current_step_title: string | null
  waiting_for_answer: boolean
  completed_at: string | null
  lifecycle_status: 'in_progress' | 'waiting_for_answer' | 'completed' | 'manual'
  updated_at: string
  created_at: string
  is_deleted: boolean
}

export type ChatFilter = 'all' | 'mine' | 'unanswered' | 'red'

export type ChatAdvancedFilters = {
  trackingLinkId: string
  dateFrom: string
  dateTo: string
  tagIds: string[]
  leadStatuses: string[]
}

export type FilterOption = {
  id: string
  label: string
}

type ChatListProps = {
  activeFilter: ChatFilter
  chats: Chat[]
  currentUserId: string | null
  isLoading: boolean
  scopeLabel: string
  selectedChatId: string | null
  total: number
  getBotLabel?: (chat: Chat) => string
  advancedFilters: ChatAdvancedFilters
  trackingOptions: FilterOption[]
  tagOptions: FilterOption[]
  statusOptions: FilterOption[]
  onFilterChange: (filter: ChatFilter) => void
  onAdvancedFiltersChange: (filters: ChatAdvancedFilters) => void
  onResetAdvancedFilters: () => void
  onRefresh: () => void
  onSelectChat: (chatId: string) => void
}

const FILTERS: Array<{ label: string; value: ChatFilter }> = [
  { label: 'Все', value: 'all' },
  { label: 'Мои', value: 'mine' },
  { label: 'Без ответа', value: 'unanswered' },
  { label: 'Горят', value: 'red' },
]

function formatDateTime(value: string | null) {
  if (!value) {
    return 'Нет активности'
  }

  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
  }).format(new Date(value))
}

function getChatTitle(chat: Chat) {
  return chat.contact_name || `Telegram ${chat.external_chat_id}`
}

function getInitials(label: string) {
  return label
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

function getLifecycleLabel(chat: Chat) {
  if (chat.lifecycle_status === 'waiting_for_answer') {
    return 'Ждёт ответ'
  }
  if (chat.lifecycle_status === 'in_progress') {
    return 'В воронке'
  }
  if (chat.lifecycle_status === 'completed') {
    return 'Завершил воронку'
  }
  return 'Ручная обработка'
}

export default function ChatList({
  activeFilter,
  chats,
  currentUserId,
  isLoading,
  scopeLabel,
  selectedChatId,
  total,
  getBotLabel,
  advancedFilters,
  trackingOptions,
  tagOptions,
  statusOptions,
  onFilterChange,
  onAdvancedFiltersChange,
  onResetAdvancedFilters,
  onRefresh,
  onSelectChat,
}: ChatListProps) {
  const advancedCount = [
    advancedFilters.trackingLinkId,
    advancedFilters.dateFrom,
    advancedFilters.dateTo,
    ...advancedFilters.tagIds,
    ...advancedFilters.leadStatuses,
  ].filter(Boolean).length

  return (
    <aside className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card">
      <div className="shrink-0 border-b border-white/5 p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-white">Чаты</h1>
            <p className="text-sm text-gray-500">{total} всего</p>
          </div>
          <button
            type="button"
            title="Обновить чаты"
            onClick={onRefresh}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-accent-200 hover:shadow-glow-accent disabled:opacity-60"
            disabled={isLoading}
          >
            {isLoading ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}
          </button>
        </div>

        <div className="mb-4 rounded-xl border border-white/5 bg-white/[0.03] px-3 py-2">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
            Боты
          </span>
          <p className="truncate text-sm font-medium text-gray-200">{scopeLabel}</p>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {FILTERS.map((filter) => {
            const isActive = activeFilter === filter.value
            const isMineDisabled = filter.value === 'mine' && !currentUserId

            return (
              <button
                key={filter.value}
                type="button"
                onClick={() => onFilterChange(filter.value)}
                disabled={isMineDisabled}
                className={`min-h-10 rounded-lg border px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  isActive
                    ? 'border-primary-300/40 bg-gradient-to-r from-primary-500 to-accent-500 text-white shadow-glow-primary'
                    : 'border-white/10 bg-white/[0.02] text-gray-400 hover:border-accent-300/35 hover:text-gray-100'
                }`}
              >
                {filter.label}
              </button>
            )
          })}
        </div>

        <div className="mt-4 rounded-xl border border-white/5 bg-white/[0.03] p-3">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-200">
              <Filter size={15} />
              Фильтры
            </div>
            <button
              type="button"
              onClick={onResetAdvancedFilters}
              disabled={advancedCount === 0}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 px-2 text-xs text-gray-400 transition hover:border-accent-300/40 hover:text-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCcw size={13} />
              Сбросить
            </button>
          </div>

          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Ссылка</span>
              <select
                value={advancedFilters.trackingLinkId}
                onChange={(event) =>
                  onAdvancedFiltersChange({
                    ...advancedFilters,
                    trackingLinkId: event.target.value,
                  })
                }
                className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none transition focus:border-accent-300/50"
              >
                <option value="">Все ссылки</option>
                {trackingOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Дата с</span>
                <input
                  type="date"
                  value={advancedFilters.dateFrom}
                  onChange={(event) =>
                    onAdvancedFiltersChange({
                      ...advancedFilters,
                      dateFrom: event.target.value,
                    })
                  }
                  className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none transition focus:border-accent-300/50"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Дата до</span>
                <input
                  type="date"
                  value={advancedFilters.dateTo}
                  onChange={(event) =>
                    onAdvancedFiltersChange({
                      ...advancedFilters,
                      dateTo: event.target.value,
                    })
                  }
                  className="h-9 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-200 outline-none transition focus:border-accent-300/50"
                />
              </label>
            </div>

            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Теги</span>
              <select
                multiple
                value={advancedFilters.tagIds}
                onChange={(event) =>
                  onAdvancedFiltersChange({
                    ...advancedFilters,
                    tagIds: Array.from(event.target.selectedOptions, (option) => option.value),
                  })
                }
                className="min-h-16 w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1 text-sm text-gray-200 outline-none transition focus:border-accent-300/50"
              >
                {tagOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Статусы</span>
              <select
                multiple
                value={advancedFilters.leadStatuses}
                onChange={(event) =>
                  onAdvancedFiltersChange({
                    ...advancedFilters,
                    leadStatuses: Array.from(
                      event.target.selectedOptions,
                      (option) => option.value,
                    ),
                  })
                }
                className="min-h-16 w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1 text-sm text-gray-200 outline-none transition focus:border-accent-300/50"
              >
                {statusOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {advancedCount > 0 ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {advancedFilters.trackingLinkId ? (
                <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs text-gray-300">
                  Ссылка
                </span>
              ) : null}
              {advancedFilters.dateFrom || advancedFilters.dateTo ? (
                <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs text-gray-300">
                  Дата
                </span>
              ) : null}
              {advancedFilters.tagIds.length > 0 ? (
                <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs text-gray-300">
                  Теги: {advancedFilters.tagIds.length}
                </span>
              ) : null}
              {advancedFilters.leadStatuses.length > 0 ? (
                <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs text-gray-300">
                  Статусы: {advancedFilters.leadStatuses.length}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {chats.length === 0 && !isLoading ? (
          <div className="p-6 text-sm text-gray-500">Чатов пока нет.</div>
        ) : null}

        {chats.map((chat) => {
          const title = getChatTitle(chat)
          const isSelected = chat.id === selectedChatId

          return (
            <button
              key={chat.id}
              type="button"
              onClick={() => onSelectChat(chat.id)}
              className={`flex w-full gap-3 border-b border-white/5 p-4 text-left transition ${
                isSelected
                  ? 'bg-gradient-to-r from-primary-500/18 to-transparent shadow-[inset_2px_0_0_rgba(34,211,238,0.9)]'
                  : 'hover:bg-white/[0.035]'
              }`}
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-accent-300/20 bg-accent-400/10 text-sm font-semibold text-accent-200 shadow-glow-accent">
                {getInitials(title) || <UserRound size={18} />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 truncate text-sm font-semibold text-white">
                    {title}
                  </p>
                  <span className="shrink-0 text-xs text-gray-500">
                    {formatDateTime(chat.last_message_at)}
                  </span>
                </div>
                {getBotLabel ? (
                  <p className="mt-1 truncate text-xs text-gray-500">
                    {getBotLabel(chat)}
                  </p>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {chat.unread ? (
                    <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-300">
                      Новое
                    </span>
                  ) : null}
                  {chat.has_unanswered_incoming ? (
                    <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-300">
                      Не отвечено
                    </span>
                  ) : null}
                  {chat.is_red ? (
                    <span className="rounded-full bg-red-400/10 px-2 py-0.5 text-xs font-medium text-red-300">
                      SLA
                    </span>
                  ) : null}
                  <span className="rounded-full bg-sky-400/10 px-2 py-0.5 text-xs font-medium text-sky-200">
                    {getLifecycleLabel(chat)}
                  </span>
                  {!chat.unread && !chat.has_unanswered_incoming && !chat.is_red ? (
                    <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs font-medium text-gray-500">
                      Готово
                    </span>
                  ) : null}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

import { ArrowDownWideNarrow, Ban, Database, LoaderCircle, RefreshCw, RotateCcw, Star, UserRound } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import ChatFilterButton from '../features/chats/components/ChatFilterButton'
import ChatFilterChips from '../features/chats/components/ChatFilterChips'
import ChatFiltersPopover from '../features/chats/components/ChatFiltersPopover'
import ChatQuickFilters from '../features/chats/components/ChatQuickFilters'
import ChatSearchBar from '../features/chats/components/ChatSearchBar'
import type { ChatFilterPreset, ChatFiltersState, FilterOption } from '../features/chats/types'
import { countActiveChatFilters } from '../features/chats/types'

export type Chat = {
  id: string
  project_id: string
  bot_id: string | null
  external_chat_id: string
  external_user_id: string
  contact_name: string | null
  client_lang: string | null
  last_message_at: string | null
  last_user_message_at: string | null
  last_manager_reply_at: string | null
  last_client_message_at: string | null
  last_operator_message_at: string | null
  is_read: boolean
  is_blocked: boolean
  is_blocked_by_user: boolean
  assignment_expires_at: string | null
  is_favorite: boolean
  has_restarted_bot: boolean
  is_imported: boolean
  imported_at: string | null
  import_identity_pending: boolean
  unanswered_minutes: number
  last_incoming_at: string | null
  last_outgoing_at: string | null
  last_read_at: string | null
  unread: boolean
  unanswered: boolean
  has_unanswered_incoming: boolean
  is_red: boolean
  is_hot_lead: boolean
  last_message_text: string | null
  last_message_type: string | null
  last_message_caption: string | null
  last_message_sender_type: 'user' | 'manager' | 'bot' | 'system' | null
  last_message_created_at: string | null
  last_message_file_name: string | null
  search_hit_message_id: string | null
  search_hit_text: string | null
  search_hit_created_at: string | null
  search_hit_sender_type: 'user' | 'manager' | 'bot' | 'system' | null
  tags: Array<{ id: string; name: string; color?: string | null }>
  lead_status: { id: string; code: string; name: string } | null
  active_funnel_id: string | null
  active_funnel_name: string | null
  active_funnel_version_id: string | null
  active_funnel_version_number: number | null
  active_funnel_version_status: string | null
  current_step_id: string | null
  current_step_title: string | null
  waiting_for_answer: boolean
  is_paused: boolean
  completed_at: string | null
  lifecycle_status: 'in_progress' | 'waiting_for_answer' | 'completed' | 'paused' | 'manual'
  updated_at: string
  created_at: string
  is_deleted: boolean
}

type ChatListProps = {
  chats: Chat[]
  canManageSharedPresets: boolean
  currentUserId: string | null
  filters: ChatFiltersState
  filterPresets: ChatFilterPreset[]
  getBotLabel?: (chat: Chat) => string
  isSelectedPresetDirty: boolean
  isLoading: boolean
  isLoadingMore: boolean
  hasMore: boolean
  scopeLabel: string
  selectedChatId: string | null
  statusOptions: FilterOption[]
  stepOptions: FilterOption[]
  tagOptions: FilterOption[]
  total: number
  workspaceCounts: Record<'unread' | 'mine' | 'all' | 'favorites', number> & {
    unanswered?: number
  }
  trackingOptions: FilterOption[]
  userOptions: FilterOption[]
  onApplyPreset: (preset: ChatFilterPreset) => void
  onDeletePreset: (presetId: string) => void
  onFiltersChange: (filters: ChatFiltersState) => void
  onLoadMore: () => void
  onRefresh: () => void
  onResetFilters: () => void
  onSavePreset: (name: string, isShared: boolean, filters: ChatFiltersState) => void
  onSelectChat: (chatId: string) => void
  onToggleFavorite: (chatId: string, isFavorite: boolean) => void
  onUpdatePreset: (presetId: string) => void
  selectedPresetId: string
}

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
  if (chat.lifecycle_status === 'paused') {
    return 'На паузе у менеджера'
  }
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

function senderPrefix(senderType: Chat['last_message_sender_type']) {
  if (senderType === 'manager') {
    return 'Вы: '
  }
  if (senderType === 'bot') {
    return 'Бот: '
  }
  if (senderType === 'user') {
    return 'Клиент: '
  }
  return ''
}

function mediaPreviewLabel(chat: Chat) {
  const type = chat.last_message_type
  const caption = chat.last_message_caption?.trim()
  if (type === 'photo' || type === 'image') {
    return `Фото${caption ? `: ${caption}` : ''}`
  }
  if (type === 'video') {
    return `Видео${caption ? `: ${caption}` : ''}`
  }
  if (type === 'document' || type === 'file') {
    return chat.last_message_file_name ? `Файл: ${chat.last_message_file_name}` : 'Файл'
  }
  if (type === 'voice') {
    return 'Голосовое'
  }
  if (type === 'video_note') {
    return 'Кружок'
  }
  if (type === 'sticker') {
    return 'Стикер'
  }
  if (type === 'animation') {
    return 'Анимация'
  }
  return chat.last_message_text || chat.last_message_caption || 'Сообщений пока нет'
}

function waitingMinutes(chat: Chat) {
  if (!chat.has_unanswered_incoming || !chat.last_client_message_at) {
    return null
  }

  const dynamicMinutes = Math.max(
    0,
    Math.floor((Date.now() - new Date(chat.last_client_message_at).getTime()) / 60000),
  )
  return Math.max(chat.unanswered_minutes || 0, dynamicMinutes)
}

function formatWaitingMinutes(minutes: number) {
  if (minutes < 60) {
    return `${minutes} мин`
  }
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest > 0 ? `${hours} ч ${rest} мин` : `${hours} ч`
}

function withAlpha(hex: string | null | undefined, alpha: number) {
  const value = hex?.trim()
  if (!value || !/^#[0-9A-Fa-f]{6}$/.test(value)) {
    return `rgba(255,255,255,${alpha})`
  }
  const red = Number.parseInt(value.slice(1, 3), 16)
  const green = Number.parseInt(value.slice(3, 5), 16)
  const blue = Number.parseInt(value.slice(5, 7), 16)
  return `rgba(${red},${green},${blue},${alpha})`
}

function highlightSnippet(snippet: string, query: string) {
  const normalizedQuery = query.trim()
  if (!normalizedQuery) {
    return snippet
  }
  const index = snippet.toLowerCase().indexOf(normalizedQuery.toLowerCase())
  if (index < 0) {
    return snippet
  }
  return (
    <>
      {snippet.slice(0, index)}
      <mark className="rounded bg-amber-300/25 px-0.5 text-amber-100">
        {snippet.slice(index, index + normalizedQuery.length)}
      </mark>
      {snippet.slice(index + normalizedQuery.length)}
    </>
  )
}

export default function ChatList({
  chats,
  canManageSharedPresets,
  currentUserId,
  filters,
  filterPresets,
  getBotLabel,
  isSelectedPresetDirty,
  isLoading,
  isLoadingMore,
  hasMore,
  scopeLabel,
  selectedChatId,
  statusOptions,
  stepOptions,
  tagOptions,
  total,
  workspaceCounts,
  trackingOptions,
  userOptions,
  onApplyPreset,
  onDeletePreset,
  onFiltersChange,
  onLoadMore,
  onRefresh,
  onResetFilters,
  onSavePreset,
  onSelectChat,
  onToggleFavorite,
  onUpdatePreset,
  selectedPresetId,
}: ChatListProps) {
  const [isFiltersOpen, setIsFiltersOpen] = useState(false)
  const [isMobileControlsOpen, setIsMobileControlsOpen] = useState(false)
  const scrollContainerRef = useRef<HTMLDivElement | null>(null)
  const loadMoreRef = useRef<HTMLDivElement | null>(null)
  const scrollAnchorRef = useRef<{ chatId: string; offset: number; scrollTop: number } | null>(null)
  const lastScrollTopRef = useRef(0)
  const selectedChatIdRef = useRef(selectedChatId)
  const previousFilterIdentityRef = useRef('')
  const activeFilterCount = countActiveChatFilters(filters)
  const filterIdentity = useMemo(
    () => JSON.stringify({ ...filters, q: filters.q.trim() }),
    [filters],
  )

  const rememberScrollAnchor = useCallback(() => {
    const root = scrollContainerRef.current
    if (!root || root.clientHeight === 0) {
      return
    }
    lastScrollTopRef.current = root.scrollTop
    const rootTop = root.getBoundingClientRect().top
    const items = Array.from(root.querySelectorAll<HTMLElement>('[data-chat-list-id]'))
    const visibleItems = items.filter((item) => item.getBoundingClientRect().bottom > rootTop + 1)
    const firstVisible = visibleItems.find(
      (item) => item.dataset.chatListId !== selectedChatIdRef.current,
    ) ?? visibleItems[0]
    if (!firstVisible) {
      scrollAnchorRef.current = null
      return
    }
    scrollAnchorRef.current = {
      chatId: firstVisible.dataset.chatListId ?? '',
      offset: firstVisible.getBoundingClientRect().top - rootTop,
      scrollTop: root.scrollTop,
    }
  }, [])

  useLayoutEffect(() => {
    selectedChatIdRef.current = selectedChatId
    rememberScrollAnchor()
  }, [rememberScrollAnchor, selectedChatId])

  useLayoutEffect(() => {
    const root = scrollContainerRef.current
    if (!root) {
      return
    }
    if (previousFilterIdentityRef.current !== filterIdentity) {
      previousFilterIdentityRef.current = filterIdentity
      scrollAnchorRef.current = null
      lastScrollTopRef.current = 0
      root.scrollTop = 0
      return
    }
    const anchor = scrollAnchorRef.current
    if (!anchor?.chatId) {
      root.scrollTop = Math.min(
        lastScrollTopRef.current,
        Math.max(0, root.scrollHeight - root.clientHeight),
      )
      rememberScrollAnchor()
      return
    }
    const target = root.querySelector<HTMLElement>(
      `[data-chat-list-id="${CSS.escape(anchor.chatId)}"]`,
    )
    if (target) {
      const nextOffset = target.getBoundingClientRect().top - root.getBoundingClientRect().top
      root.scrollTop += nextOffset - anchor.offset
    } else {
      root.scrollTop = Math.min(
        Math.max(anchor.scrollTop, lastScrollTopRef.current),
        Math.max(0, root.scrollHeight - root.clientHeight),
      )
    }
    rememberScrollAnchor()
  }, [chats, filterIdentity, rememberScrollAnchor])

  useEffect(() => {
    const root = scrollContainerRef.current
    const target = loadMoreRef.current
    if (!root || !target || !hasMore || isLoading || isLoadingMore) {
      return undefined
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          onLoadMore()
        }
      },
      { root, rootMargin: '240px 0px' },
    )
    observer.observe(target)
    return () => observer.disconnect()
  }, [hasMore, isLoading, isLoadingMore, onLoadMore])

  return (
    <aside className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-surface/90 shadow-card md:rounded-xl md:border md:border-white/5">
      <div className="shrink-0 border-b border-white/5 p-3 md:p-4">
        <div className="flex items-center justify-between gap-3 md:mb-4">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-white">Чаты</h1>
            <p className="truncate text-sm text-gray-500">
              {total} всего · {scopeLabel}
            </p>
            {(workspaceCounts.unanswered ?? 0) > 0 ? (
              <p className="mt-1 text-xs font-medium text-orange-200">
                Неотвеченных: {workspaceCounts.unanswered}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            title="Обновить чаты"
            onClick={onRefresh}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-accent-200 hover:shadow-glow-accent disabled:opacity-60"
            disabled={isLoading}
          >
            {isLoading ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}
          </button>
        </div>

        <button
          type="button"
          onClick={() => setIsMobileControlsOpen((value) => !value)}
          className="mt-3 flex h-10 w-full items-center justify-between rounded-xl border border-white/10 bg-white/[0.035] px-3 text-sm font-medium text-gray-200 md:hidden"
          aria-expanded={isMobileControlsOpen}
        >
          <span>Поиск и фильтры</span>
          <span className="rounded-full bg-accent-300/10 px-2 py-0.5 text-xs text-accent-100">
            {activeFilterCount > 0 ? activeFilterCount : 'Все'}
          </span>
        </button>

        <div className={`${isMobileControlsOpen ? 'mt-3 flex' : 'hidden'} gap-2 md:flex`}>
          <div className="min-w-0 flex-1">
            <ChatSearchBar
              value={filters.q}
              onChange={(q) => onFiltersChange({ ...filters, q })}
              onClear={() => onFiltersChange({ ...filters, q: '' })}
            />
          </div>
          <ChatFilterButton
            activeCount={activeFilterCount}
            isOpen={isFiltersOpen}
            onClick={() => setIsFiltersOpen((value) => !value)}
          />
        </div>

        <div className={`${isMobileControlsOpen ? 'mt-3 block' : 'hidden'} md:mt-3 md:block`}>
          <ChatQuickFilters
            currentUserId={currentUserId}
            counts={workspaceCounts}
            filters={filters}
            onChange={onFiltersChange}
          />
        </div>

        <label className={`${isMobileControlsOpen ? 'mt-2 flex' : 'hidden'} items-center gap-2 md:mt-2 md:flex`}>
          <ArrowDownWideNarrow size={14} className="shrink-0 text-gray-500" />
          <span className="sr-only">Сортировка чатов</span>
          <select
            value={filters.sortBy}
            onChange={(event) =>
              onFiltersChange({
                ...filters,
                sortBy: event.target.value as ChatFiltersState['sortBy'],
              })
            }
            className="h-8 min-w-0 flex-1 rounded-lg border border-white/8 bg-background/45 px-2 text-xs text-gray-300 outline-none transition focus:border-accent-300/45"
          >
            <option value="latest">Сначала свежие</option>
            <option value="priority">Сначала срочные</option>
          </select>
        </label>

        {activeFilterCount > 0 ? (
          <div className={`${isMobileControlsOpen ? 'mt-2 block' : 'hidden'} md:mt-2 md:block`}>
            <ChatFilterChips
              filters={filters}
              statusOptions={statusOptions}
              tagOptions={tagOptions}
              trackingOptions={trackingOptions}
              stepOptions={stepOptions}
              userOptions={userOptions}
              onChange={onFiltersChange}
              onReset={onResetFilters}
            />
          </div>
        ) : null}

        <ChatFiltersPopover
          canManageSharedPresets={canManageSharedPresets}
          currentUserId={currentUserId}
          filters={filters}
          filterPresets={filterPresets}
          isOpen={isFiltersOpen}
          isSelectedPresetDirty={isSelectedPresetDirty}
          statusOptions={statusOptions}
          tagOptions={tagOptions}
          trackingOptions={trackingOptions}
          stepOptions={stepOptions}
          userOptions={userOptions}
          selectedPresetId={selectedPresetId}
          onApplyPreset={onApplyPreset}
          onDeletePreset={onDeletePreset}
          onApply={onFiltersChange}
          onClose={() => setIsFiltersOpen(false)}
          onReset={onResetFilters}
          onSavePreset={onSavePreset}
          onUpdatePreset={onUpdatePreset}
        />
      </div>

      <div
        ref={scrollContainerRef}
        onScroll={rememberScrollAnchor}
        className="touch-scroll min-h-0 flex-1 overflow-y-auto"
      >
        {chats.length === 0 && !isLoading ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="text-sm text-gray-400">
              {activeFilterCount > 0
                ? 'По выбранным фильтрам чатов нет'
                : 'Чатов пока нет.'}
            </p>
            {activeFilterCount > 0 ? (
              <button
                type="button"
                onClick={onResetFilters}
                className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-200 transition hover:border-accent-300/40"
              >
                Сбросить фильтры
              </button>
            ) : null}
          </div>
        ) : null}

        {chats.map((chat) => {
          const title = getChatTitle(chat)
          const isSelected = chat.id === selectedChatId
          const hasSearchHit = Boolean(filters.q.trim() && chat.search_hit_text)
          const preview = hasSearchHit
            ? chat.search_hit_text || ''
            : `${senderPrefix(chat.last_message_sender_type)}${mediaPreviewLabel(chat)}`
          const visibleTags = chat.tags.slice(0, 3)
          const hiddenTags = chat.tags.slice(3)
          const isUnread = chat.is_read === false || chat.unread
          const waitingForReplyMinutes = waitingMinutes(chat)

          return (
            <div
              key={chat.id}
              data-chat-list-id={chat.id}
              className={`flex w-full border-b border-white/5 text-left transition ${
                isSelected
                  ? 'bg-gradient-to-r from-primary-500/18 to-transparent shadow-[inset_2px_0_0_rgba(34,211,238,0.9)]'
                  : 'hover:bg-white/[0.035]'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectChat(chat.id)}
                className="flex min-w-0 flex-1 gap-3 p-4 pr-1 text-left"
              >
              <div className="relative shrink-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-accent-300/20 bg-accent-400/10 text-sm font-semibold text-accent-200 shadow-glow-accent">
                  {getInitials(title) || <UserRound size={18} />}
                </div>
                {isUnread ? (
                  <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full border-2 border-surface bg-sky-300 shadow-[0_0_12px_rgba(125,211,252,0.9)]" />
                ) : null}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-1.5">
                    {chat.is_blocked_by_user ? (
                      <Ban
                        size={14}
                        className="shrink-0 text-red-300"
                        aria-label="Пользователь заблокировал бота"
                      />
                    ) : null}
                    {chat.has_restarted_bot ? (
                      <RotateCcw
                        size={14}
                        className="shrink-0 text-amber-200"
                        aria-label="Пользователь повторно запустил бота"
                      />
                    ) : null}
                    <p className={`min-w-0 truncate text-sm text-white ${isUnread ? 'font-bold' : 'font-semibold'}`}>
                      {title}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-gray-500">
                    {formatDateTime(chat.last_message_at)}
                  </span>
                </div>
                {getBotLabel ? (
                  <p className="mt-1 truncate text-xs text-gray-500">
                    {getBotLabel(chat)}
                  </p>
                ) : null}
                <p className={`mt-2 line-clamp-2 text-xs leading-5 ${
                  hasSearchHit ? 'text-amber-100' : isUnread ? 'font-semibold text-gray-200' : 'text-gray-400'
                }`}>
                  {hasSearchHit ? (
                    <>
                      <span className="text-amber-300">Найдено: </span>
                      {highlightSnippet(preview, filters.q)}
                    </>
                  ) : (
                    preview
                  )}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {isUnread ? (
                    <span className="rounded-full bg-sky-400/10 px-2 py-0.5 text-xs font-medium text-sky-200">
                      Не прочитано лидом
                    </span>
                  ) : null}
                  {waitingForReplyMinutes !== null ? (
                    <span className="rounded-full bg-orange-400/10 px-2 py-0.5 text-xs font-semibold text-orange-200">
                      Ждет ответа {formatWaitingMinutes(waitingForReplyMinutes)}
                    </span>
                  ) : null}
                  {chat.is_hot_lead ? (
                    <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-xs font-semibold text-amber-200">
                      Горячий
                    </span>
                  ) : null}
                  {chat.is_red ? (
                    <span className="rounded-full bg-red-400/10 px-2 py-0.5 text-xs font-medium text-red-300">
                      SLA
                    </span>
                  ) : null}
                  {chat.is_blocked_by_user ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-red-500/10 px-2 py-0.5 text-xs font-medium text-red-200">
                      <Ban size={11} />
                      Бот заблокирован
                    </span>
                  ) : null}
                  {chat.is_imported ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-violet-400/10 px-2 py-0.5 text-xs font-medium text-violet-200">
                      <Database size={11} />
                      Импорт
                    </span>
                  ) : null}
                  <span className="rounded-full bg-sky-400/10 px-2 py-0.5 text-xs font-medium text-sky-200">
                    {getLifecycleLabel(chat)}
                  </span>
                  {chat.lead_status ? (
                    <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs font-medium text-gray-200">
                      {chat.lead_status.name}
                    </span>
                  ) : null}
                </div>
                {chat.tags.length > 0 ? (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {visibleTags.map((tag) => (
                      <span
                        key={tag.id}
                        className="max-w-[96px] truncate rounded-full border px-2 py-0.5 text-xs text-gray-100"
                        style={{
                          backgroundColor: withAlpha(tag.color, 0.13),
                          borderColor: withAlpha(tag.color, 0.55),
                        }}
                        title={tag.name}
                      >
                        {tag.name}
                      </span>
                    ))}
                    {hiddenTags.length > 0 ? (
                      <span
                        className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs text-gray-400"
                        title={hiddenTags.map((tag) => tag.name).join(', ')}
                      >
                        +{hiddenTags.length}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
              </button>
              <button
                type="button"
                onClick={() => onToggleFavorite(chat.id, !chat.is_favorite)}
                className={`m-2 ml-0 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition ${
                  chat.is_favorite
                    ? 'border-amber-300/30 bg-amber-300/10 text-amber-200'
                    : 'border-transparent text-gray-600 hover:border-white/10 hover:bg-white/[0.04] hover:text-gray-300'
                }`}
                title={chat.is_favorite ? 'Убрать из избранного' : 'Добавить в избранное'}
                aria-label={chat.is_favorite ? 'Убрать из избранного' : 'Добавить в избранное'}
              >
                <Star size={16} className={chat.is_favorite ? 'fill-current' : ''} />
              </button>
            </div>
          )
        })}
        <div ref={loadMoreRef} className="flex min-h-16 items-center justify-center px-4 py-3">
          {hasMore ? (
            <button
              type="button"
              onClick={onLoadMore}
              disabled={isLoading || isLoadingMore}
              className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-4 text-sm font-medium text-gray-300 transition hover:border-accent-300/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isLoadingMore ? <LoaderCircle size={15} className="animate-spin" /> : null}
              {isLoadingMore ? 'Загружаем чаты' : `Показать ещё · ${chats.length} из ${total}`}
            </button>
          ) : chats.length > 0 ? (
            <span className="text-xs text-gray-600">Показаны все чаты: {total}</span>
          ) : null}
        </div>
      </div>
    </aside>
  )
}

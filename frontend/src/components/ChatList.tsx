import { LoaderCircle, RefreshCw, UserRound } from 'lucide-react'
import { useState } from 'react'

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
  unanswered_minutes: number
  last_incoming_at: string | null
  last_outgoing_at: string | null
  last_read_at: string | null
  unread: boolean
  unanswered: boolean
  has_unanswered_incoming: boolean
  is_red: boolean
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
  completed_at: string | null
  lifecycle_status: 'in_progress' | 'waiting_for_answer' | 'completed' | 'manual'
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
  scopeLabel: string
  selectedChatId: string | null
  statusOptions: FilterOption[]
  tagOptions: FilterOption[]
  total: number
  trackingOptions: FilterOption[]
  userOptions: FilterOption[]
  onApplyPreset: (preset: ChatFilterPreset) => void
  onDeletePreset: (presetId: string) => void
  onFiltersChange: (filters: ChatFiltersState) => void
  onRefresh: () => void
  onResetFilters: () => void
  onSavePreset: (name: string, isShared: boolean, filters: ChatFiltersState) => void
  onSelectChat: (chatId: string) => void
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
  if (!chat.last_client_message_at) {
    return null
  }
  if (
    chat.last_operator_message_at &&
    new Date(chat.last_operator_message_at).getTime() >= new Date(chat.last_client_message_at).getTime()
  ) {
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
  scopeLabel,
  selectedChatId,
  statusOptions,
  tagOptions,
  total,
  trackingOptions,
  userOptions,
  onApplyPreset,
  onDeletePreset,
  onFiltersChange,
  onRefresh,
  onResetFilters,
  onSavePreset,
  onSelectChat,
  onUpdatePreset,
  selectedPresetId,
}: ChatListProps) {
  const [isFiltersOpen, setIsFiltersOpen] = useState(false)
  const activeFilterCount = countActiveChatFilters(filters)

  return (
    <aside className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card">
      <div className="shrink-0 border-b border-white/5 p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold text-white">Чаты</h1>
            <p className="truncate text-sm text-gray-500">
              {total} всего · {scopeLabel}
            </p>
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

        <div className="flex gap-2">
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

        <div className="mt-3">
          <ChatQuickFilters
            currentUserId={currentUserId}
            filters={filters}
            onChange={onFiltersChange}
          />
        </div>

        {activeFilterCount > 0 ? (
          <div className="mt-2">
            <ChatFilterChips
              filters={filters}
              statusOptions={statusOptions}
              tagOptions={tagOptions}
              trackingOptions={trackingOptions}
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

      <div className="min-h-0 flex-1 overflow-y-auto">
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
                  <p className={`min-w-0 truncate text-sm text-white ${isUnread ? 'font-bold' : 'font-semibold'}`}>
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
                      Непрочитано
                    </span>
                  ) : null}
                  {waitingForReplyMinutes !== null ? (
                    <span className="rounded-full bg-orange-400/10 px-2 py-0.5 text-xs font-semibold text-orange-200">
                      Ждет ответа {formatWaitingMinutes(waitingForReplyMinutes)}
                    </span>
                  ) : null}
                  {chat.is_red ? (
                    <span className="rounded-full bg-red-400/10 px-2 py-0.5 text-xs font-medium text-red-300">
                      Горячий
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
          )
        })}
      </div>
    </aside>
  )
}

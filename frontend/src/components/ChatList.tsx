import { LoaderCircle, RefreshCw, UserRound } from 'lucide-react'

export type Chat = {
  id: string
  project_id: string
  external_chat_id: string
  external_user_id: string
  contact_name: string | null
  last_message_at: string | null
  last_user_message_at: string | null
  last_manager_reply_at: string | null
  last_read_at: string | null
  unread: boolean
  unanswered: boolean
  is_red: boolean
  updated_at: string
  created_at: string
  is_deleted: boolean
}

export type ChatFilter = 'all' | 'mine' | 'unanswered' | 'red'

type ChatListProps = {
  activeFilter: ChatFilter
  chats: Chat[]
  currentUserId: string | null
  isLoading: boolean
  selectedChatId: string | null
  total: number
  onFilterChange: (filter: ChatFilter) => void
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
    return 'No activity'
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

export default function ChatList({
  activeFilter,
  chats,
  currentUserId,
  isLoading,
  selectedChatId,
  total,
  onFilterChange,
  onRefresh,
  onSelectChat,
}: ChatListProps) {
  return (
    <aside className="flex min-w-0 flex-col border-r border-zinc-800 bg-zinc-950">
      <div className="border-b border-zinc-800 p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Chats</h1>
            <p className="text-sm text-zinc-500">{total} total</p>
          </div>
          <button
            type="button"
            title="Refresh chats"
            onClick={onRefresh}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 text-zinc-300 transition hover:bg-zinc-900 disabled:opacity-60"
            disabled={isLoading}
          >
            {isLoading ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}
          </button>
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
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  isActive
                    ? 'border-emerald-500 bg-emerald-500 text-zinc-950'
                    : 'border-zinc-800 text-zinc-300 hover:bg-zinc-900'
                }`}
              >
                {filter.label}
              </button>
            )
          })}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {chats.length === 0 && !isLoading ? (
          <div className="p-6 text-sm text-zinc-500">No chats yet.</div>
        ) : null}

        {chats.map((chat) => {
          const title = getChatTitle(chat)
          const isSelected = chat.id === selectedChatId

          return (
            <button
              key={chat.id}
              type="button"
              onClick={() => onSelectChat(chat.id)}
              className={`flex w-full gap-3 border-b border-zinc-900 p-4 text-left transition ${
                isSelected ? 'bg-zinc-900' : 'hover:bg-zinc-900/70'
              }`}
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-sm font-semibold text-emerald-300">
                {getInitials(title) || <UserRound size={18} />}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <p className="truncate text-sm font-semibold text-zinc-100">{title}</p>
                  <span className="shrink-0 text-xs text-zinc-500">
                    {formatDateTime(chat.last_message_at)}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {chat.unread ? (
                    <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-300">
                      New
                    </span>
                  ) : null}
                  {chat.unanswered ? (
                    <span className="rounded bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-300">
                      Open
                    </span>
                  ) : null}
                  {chat.is_red ? (
                    <span className="rounded bg-red-500/15 px-2 py-0.5 text-xs font-medium text-red-300">
                      SLA
                    </span>
                  ) : null}
                  {!chat.unread && !chat.unanswered && !chat.is_red ? (
                    <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs font-medium text-zinc-400">
                      Done
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

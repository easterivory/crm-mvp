import { LoaderCircle, RefreshCw, UserRound } from 'lucide-react'

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
  bots: Array<{ id: string; name: string; bot_username: string | null }>
  chats: Chat[]
  currentUserId: string | null
  isBotsLoading: boolean
  isLoading: boolean
  selectedBotId: string
  selectedChatId: string | null
  total: number
  onBotChange: (botId: string) => void
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
  bots,
  chats,
  currentUserId,
  isBotsLoading,
  isLoading,
  selectedBotId,
  selectedChatId,
  total,
  onBotChange,
  onFilterChange,
  onRefresh,
  onSelectChat,
}: ChatListProps) {
  return (
    <aside className="flex min-h-[360px] min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card xl:min-h-0">
      <div className="shrink-0 border-b border-white/5 p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-white">Chats</h1>
            <p className="text-sm text-gray-500">{total} total</p>
          </div>
          <button
            type="button"
            title="Refresh chats"
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

        <label className="mb-4 block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
            Выберите бота
          </span>
          <select
            value={selectedBotId}
            onChange={(event) => onBotChange(event.target.value)}
            disabled={isBotsLoading || bots.length === 0}
            className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="" disabled>
              {isBotsLoading ? 'Loading bots...' : 'Select bot'}
            </option>
            {bots.map((bot) => (
              <option key={bot.id} value={bot.id}>
                {bot.name}
                {bot.bot_username ? ` (@${bot.bot_username})` : ''}
              </option>
            ))}
          </select>
        </label>

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
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {chats.length === 0 && !isLoading ? (
          <div className="p-6 text-sm text-gray-500">No chats yet.</div>
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
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  {chat.unread ? (
                    <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-300">
                      New
                    </span>
                  ) : null}
                  {chat.unanswered ? (
                    <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-300">
                      Open
                    </span>
                  ) : null}
                  {chat.is_red ? (
                    <span className="rounded-full bg-red-400/10 px-2 py-0.5 text-xs font-medium text-red-300">
                      SLA
                    </span>
                  ) : null}
                  {!chat.unread && !chat.unanswered && !chat.is_red ? (
                    <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-xs font-medium text-gray-500">
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

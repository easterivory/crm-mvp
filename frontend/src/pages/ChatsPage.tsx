import {
  AlertCircle,
  Bot,
  CheckCheck,
  LoaderCircle,
  MessageSquareText,
  Send,
} from 'lucide-react'
import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import axios from 'axios'

import api from '../api/client'
import ChatList, { Chat, ChatFilter } from '../components/ChatList'
import LeadSidebar from '../components/LeadSidebar'
import { useAuthStore } from '../store/authStore'

type PaginatedResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type Message = {
  id: string
  chat_id: string
  external_message_id: string | null
  message_type: string
  sender_type: 'user' | 'manager' | 'bot' | 'system'
  sender_id: string | null
  body: string | null
  created_at: string
}

type BotRecord = {
  id: string
  project_id: string
  name: string
  has_telegram_token: boolean
  bot_username: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
}

const CHAT_LIMIT = 50
const MESSAGE_LIMIT = 100

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

function getErrorMessage(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Cannot reach API. Check backend/container status.'
    }
  }

  return 'Request failed. Please try again.'
}

export default function ChatsPage() {
  const user = useAuthStore((state) => state.user)

  const [chats, setChats] = useState<Chat[]>([])
  const [bots, setBots] = useState<BotRecord[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [total, setTotal] = useState(0)
  const [selectedBotId, setSelectedBotId] = useState('')
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null)
  const [activeFilter, setActiveFilter] = useState<ChatFilter>('all')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [isChatsLoading, setIsChatsLoading] = useState(true)
  const [isBotsLoading, setIsBotsLoading] = useState(true)
  const [isMessagesLoading, setIsMessagesLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  )

  const selectedBot = useMemo(
    () => bots.find((bot) => bot.id === selectedBotId) ?? null,
    [bots, selectedBotId],
  )

  const loadBots = useCallback(async () => {
    setIsBotsLoading(true)
    setError('')

    try {
      const { data } = await api.get<PaginatedResponse<BotRecord>>('/bots', {
        params: { limit: 100, offset: 0 },
      })
      setBots(data.items)
      setSelectedBotId((current) => {
        if (current && data.items.some((bot) => bot.id === current)) {
          return current
        }
        return data.items[0]?.id ?? ''
      })
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsBotsLoading(false)
    }
  }, [])

  const loadChats = useCallback(async () => {
    if (!selectedBotId) {
      setChats([])
      setTotal(0)
      setSelectedChatId(null)
      setIsChatsLoading(false)
      return
    }

    setIsChatsLoading(true)
    setError('')

    try {
      const params: Record<string, boolean | number | string> = {
        limit: CHAT_LIMIT,
        offset: 0,
        bot_id: selectedBotId,
      }

      if (activeFilter === 'mine' && user?.id) {
        params.manager_id = user.id
      }
      if (activeFilter === 'unanswered') {
        params.unanswered = true
      }
      if (activeFilter === 'red') {
        params.is_red = true
      }

      const { data } = await api.get<PaginatedResponse<Chat>>('/chats', { params })
      setChats(data.items)
      setTotal(data.total)
      setSelectedChatId((current) => {
        if (current && data.items.some((chat) => chat.id === current)) {
          return current
        }
        return data.items[0]?.id ?? null
      })
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsChatsLoading(false)
    }
  }, [activeFilter, selectedBotId, user?.id])

  const loadMessages = useCallback(async (chatId: string, showLoader = false) => {
    if (showLoader) {
      setIsMessagesLoading(true)
    }
    setError('')

    try {
      const { data } = await api.get<PaginatedResponse<Message>>(
        `/chats/${chatId}/messages`,
        { params: { limit: MESSAGE_LIMIT, offset: 0 } },
      )
      setMessages(data.items)
      await api.post(`/chats/${chatId}/read`)
      setChats((current) =>
        current.map((chat) =>
          chat.id === chatId ? { ...chat, unread: false } : chat,
        ),
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      if (showLoader) {
        setIsMessagesLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    void loadBots()
  }, [loadBots])

  useEffect(() => {
    void loadChats()
    const timer = window.setInterval(() => {
      void loadChats()
    }, 15000)

    return () => window.clearInterval(timer)
  }, [loadChats])

  useEffect(() => {
    if (!selectedChatId) {
      setMessages([])
      return undefined
    }

    setMessages([])
    void loadMessages(selectedChatId, true)
    const timer = window.setInterval(() => {
      void loadMessages(selectedChatId)
    }, 7000)

    return () => window.clearInterval(timer)
  }, [loadMessages, selectedChatId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const sendMessage = async () => {
    const text = draft.trim()
    if (!selectedChatId || !text || isSending) {
      return
    }

    setIsSending(true)
    setError('')

    try {
      const { data } = await api.post<Message>(`/chats/${selectedChatId}/messages`, {
        body: text,
        message_type: 'text',
        sender_id: user?.id ?? null,
        sender_type: 'manager',
      })
      setMessages((current) => [...current, data])
      setDraft('')
      await loadChats()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsSending(false)
    }
  }

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await sendMessage()
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }

    event.preventDefault()
    void sendMessage()
  }

  return (
    <section className="grid h-full min-h-0 grid-cols-1 gap-4 overflow-y-auto text-gray-200 xl:grid-cols-[minmax(280px,25%)_minmax(0,50%)_minmax(280px,25%)] xl:overflow-hidden">
      <ChatList
        activeFilter={activeFilter}
        bots={bots}
        chats={chats}
        currentUserId={user?.id ?? null}
        isBotsLoading={isBotsLoading}
        isLoading={isChatsLoading}
        selectedBotId={selectedBotId}
        selectedChatId={selectedChatId}
        total={total}
        onBotChange={setSelectedBotId}
        onFilterChange={setActiveFilter}
        onRefresh={() => void loadChats()}
        onSelectChat={setSelectedChatId}
      />

      <div className="flex min-h-[520px] min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card xl:min-h-0">
        <header className="flex min-h-[73px] shrink-0 items-center justify-between gap-4 border-b border-white/5 px-5">
          {selectedChat ? (
            <>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-base font-semibold text-white">
                    {getChatTitle(selectedChat)}
                  </h2>
                  {selectedChat.is_red ? <AlertCircle size={16} className="text-red-300 drop-shadow-[0_0_10px_rgba(248,113,113,0.6)]" /> : null}
                </div>
                <p className="truncate text-sm text-gray-500">
                  Telegram ID {selectedChat.external_chat_id}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-sm text-gray-500">
                <CheckCheck size={16} />
                <span>{selectedChat.last_read_at ? 'Read' : 'Unread'}</span>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <MessageSquareText size={18} />
              Select a chat
            </div>
          )}
        </header>

        {error ? (
          <div className="border-b border-red-400/20 bg-red-500/10 px-5 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto bg-background/45 px-5 py-4">
          {isMessagesLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Loading messages
            </div>
          ) : null}

          {!selectedChat && !isMessagesLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              No chat selected.
            </div>
          ) : null}

          {selectedChat && !isMessagesLoading && messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              No messages yet.
            </div>
          ) : null}

          {selectedChat && !isMessagesLoading && messages.length > 0 ? (
            <div className="space-y-3">
              {messages.map((message) => {
                const isOutgoing =
                  message.sender_type === 'manager' || message.sender_type === 'bot'
                const isBot = message.sender_type === 'bot'

                return (
                  <div
                    key={message.id}
                    className={`flex ${isOutgoing ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[72%] rounded-2xl border px-3 py-2 shadow-sm ${
                        isOutgoing
                          ? isBot
                            ? 'border-accent-300/25 bg-accent-400/10 text-accent-50 shadow-glow-accent'
                            : 'border-primary-300/25 bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary'
                          : 'border-white/10 bg-white/[0.055] text-gray-100'
                      }`}
                    >
                      <div className="mb-1 flex items-center gap-1.5 text-xs opacity-75">
                        {isBot ? <Bot size={13} /> : null}
                        <span>{message.sender_type}</span>
                        <span>{formatDateTime(message.created_at)}</span>
                      </div>
                      <p className="whitespace-pre-wrap break-words text-sm leading-6">
                        {message.body || `[${message.message_type}]`}
                      </p>
                    </div>
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>
          ) : null}
        </div>

        <form className="shrink-0 border-t border-white/5 bg-surface/80 p-4" onSubmit={handleSend}>
          <div className="flex items-end gap-3">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              className="max-h-32 min-h-[44px] flex-1 resize-none overflow-y-auto rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 disabled:bg-background/40"
              placeholder="Reply in Telegram"
              disabled={!selectedChat || isSending}
              rows={2}
            />
            <button
              type="submit"
              title="Send message"
              disabled={!selectedChat || !draft.trim() || isSending}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSending ? <LoaderCircle size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
        </form>
      </div>

      <LeadSidebar
        activeBotId={selectedBotId || null}
        activeBotName={selectedBot?.name ?? null}
        activeChatId={selectedChatId}
        currentUserId={user?.id ?? null}
      />
    </section>
  )
}

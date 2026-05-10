import {
  AlertCircle,
  Bot,
  CheckCheck,
  LoaderCircle,
  MessageSquareText,
  Send,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  const [messages, setMessages] = useState<Message[]>([])
  const [total, setTotal] = useState(0)
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null)
  const [activeFilter, setActiveFilter] = useState<ChatFilter>('all')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [isChatsLoading, setIsChatsLoading] = useState(true)
  const [isMessagesLoading, setIsMessagesLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  )

  const loadChats = useCallback(async () => {
    setIsChatsLoading(true)
    setError('')

    try {
      const params: Record<string, boolean | number | string> = {
        limit: CHAT_LIMIT,
        offset: 0,
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
  }, [activeFilter, user?.id])

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

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

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

  return (
    <section className="grid h-[calc(100vh-112px)] min-h-[560px] grid-cols-[minmax(280px,25%)_minmax(0,50%)_minmax(280px,25%)] overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl">
      <ChatList
        activeFilter={activeFilter}
        chats={chats}
        currentUserId={user?.id ?? null}
        isLoading={isChatsLoading}
        selectedChatId={selectedChatId}
        total={total}
        onFilterChange={setActiveFilter}
        onRefresh={() => void loadChats()}
        onSelectChat={setSelectedChatId}
      />

      <div className="flex min-w-0 flex-col bg-zinc-950">
        <header className="flex min-h-[73px] items-center justify-between gap-4 border-b border-zinc-800 px-5">
          {selectedChat ? (
            <>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-base font-semibold text-zinc-100">
                    {getChatTitle(selectedChat)}
                  </h2>
                  {selectedChat.is_red ? <AlertCircle size={16} className="text-red-400" /> : null}
                </div>
                <p className="truncate text-sm text-zinc-500">
                  Telegram ID {selectedChat.external_chat_id}
                </p>
              </div>
              <div className="flex items-center gap-2 text-sm text-zinc-500">
                <CheckCheck size={16} />
                {selectedChat.last_read_at ? 'Read' : 'Unread'}
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-zinc-500">
              <MessageSquareText size={18} />
              Select a chat
            </div>
          )}
        </header>

        {error ? (
          <div className="border-b border-red-900/70 bg-red-950/40 px-5 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto bg-neutral-950 px-5 py-4">
          {isMessagesLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-zinc-500">
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Loading messages
            </div>
          ) : null}

          {!selectedChat && !isMessagesLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-zinc-500">
              No chat selected.
            </div>
          ) : null}

          {selectedChat && !isMessagesLoading && messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-zinc-500">
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
                      className={`max-w-[72%] rounded-lg border px-3 py-2 shadow-sm ${
                        isOutgoing
                          ? isBot
                            ? 'border-indigo-500/30 bg-indigo-500/15 text-indigo-100'
                            : 'border-emerald-500 bg-emerald-500 text-zinc-950'
                          : 'border-zinc-800 bg-zinc-900 text-zinc-100'
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

        <form className="border-t border-zinc-800 bg-zinc-950 p-4" onSubmit={handleSend}>
          <div className="flex gap-3">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="min-h-[44px] flex-1 resize-none rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-500 focus:ring-2 disabled:bg-zinc-900/60"
              placeholder="Reply in Telegram"
              disabled={!selectedChat || isSending}
              rows={2}
            />
            <button
              type="submit"
              title="Send message"
              disabled={!selectedChat || !draft.trim() || isSending}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-emerald-500 text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSending ? <LoaderCircle size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
        </form>
      </div>

      <LeadSidebar activeChatId={selectedChatId} currentUserId={user?.id ?? null} />
    </section>
  )
}

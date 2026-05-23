import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CheckCheck,
  Download,
  FileText,
  Film,
  Image as ImageIcon,
  LoaderCircle,
  Mic,
  MessageSquareText,
  Music,
  Send,
  UserRound,
  Video,
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
import { fetchBots, type Bot as BotRecord } from '../features/bots'
import { useNotificationStore, useProjectBotSelection } from '../shared/lib'
import { ConfirmDialog, Modal } from '../shared/ui'
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
  caption: string | null
  telegram_file_id: string | null
  file_unique_id: string | null
  file_name: string | null
  mime_type: string | null
  file_size: number | null
  media_group_id: string | null
  created_at: string
}

const CHAT_LIMIT = 50
const MESSAGE_LIMIT = 100

const mediaLabels: Record<string, string> = {
  animation: 'Анимация',
  audio: 'Аудио',
  document: 'Файл',
  file: 'Файл',
  image: 'Фото',
  photo: 'Фото',
  sticker: 'Стикер',
  unknown: 'Вложение',
  video: 'Видео',
  video_note: 'Кружок',
  voice: 'Голосовое',
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

function getErrorMessage(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен. Проверьте backend или контейнер.'
    }
  }

  return 'Запрос не выполнен. Попробуйте снова.'
}

function getMediaLabel(message: Message) {
  return mediaLabels[message.message_type] ?? message.message_type
}

function getMediaIcon(messageType: string) {
  if (messageType === 'photo' || messageType === 'image') {
    return ImageIcon
  }
  if (messageType === 'video' || messageType === 'video_note') {
    return Video
  }
  if (messageType === 'voice') {
    return Mic
  }
  if (messageType === 'audio') {
    return Music
  }
  if (messageType === 'animation' || messageType === 'sticker') {
    return Film
  }
  return FileText
}

function formatFileSize(value: number | null) {
  if (!value || value <= 0) {
    return null
  }
  if (value < 1024 * 1024) {
    return `${Math.ceil(value / 1024)} КБ`
  }
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

export default function ChatsPage() {
  const user = useAuthStore((state) => state.user)
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const notify = useNotificationStore((state) => state.notify)

  const [chats, setChats] = useState<Chat[]>([])
  const [bots, setBots] = useState<BotRecord[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [total, setTotal] = useState(0)
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null)
  const [activeFilter, setActiveFilter] = useState<ChatFilter>('all')
  const [draft, setDraft] = useState('')
  const [isChatsLoading, setIsChatsLoading] = useState(true)
  const [isMessagesLoading, setIsMessagesLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [openingMediaId, setOpeningMediaId] = useState<string | null>(null)
  const [isResetConfirmOpen, setIsResetConfirmOpen] = useState(false)
  const [isResettingChat, setIsResettingChat] = useState(false)
  const [isLeadOpen, setIsLeadOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  )

  const botScopeLabel = useMemo(() => {
    if (!selectedProjectId) {
      return 'Выберите проект в шапке'
    }
    if (selectedBotIds.length === 0) {
      return 'Все боты выбранного проекта'
    }
    if (selectedBotIds.length === 1) {
      return '1 выбранный бот'
    }
    return `${selectedBotIds.length} выбранных бота`
  }, [selectedBotIds.length, selectedProjectId])

  const botById = useMemo(() => new Map(bots.map((bot) => [bot.id, bot])), [bots])

  const getBotLabel = useCallback(
    (chat: Chat) => {
      if (!chat.bot_id) {
        return 'Бот не указан'
      }
      const bot = botById.get(chat.bot_id)
      if (!bot) {
        return `Бот ${chat.bot_id.slice(0, 8)}`
      }
      return [bot.name, bot.bot_username ? `@${bot.bot_username}` : null]
        .filter(Boolean)
        .join(' · ')
    },
    [botById],
  )

  const loadChats = useCallback(async () => {
    if (!selectedProjectId) {
      setChats([])
      setTotal(0)
      setSelectedChatId(null)
      setIsChatsLoading(false)
      return
    }

    setIsChatsLoading(true)

    try {
      const params: Record<string, boolean | number | string> = {
        limit: CHAT_LIMIT,
        offset: 0,
        project_id: selectedProjectId,
      }

      if (selectedBotIds.length === 1) {
        params.bot_id = selectedBotIds[0]
      } else if (selectedBotIds.length > 1) {
        params.bot_ids = selectedBotIds.join(',')
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
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsChatsLoading(false)
    }
  }, [activeFilter, selectedBotIds, selectedProjectId, user?.id])

  const loadBots = useCallback(async () => {
    if (!selectedProjectId) {
      setBots([])
      return
    }
    try {
      setBots(await fetchBots(selectedProjectId))
    } catch {
      setBots([])
    }
  }, [selectedProjectId])

  const loadMessages = useCallback(async (chatId: string, showLoader = false) => {
    if (showLoader) {
      setIsMessagesLoading(true)
    }

    try {
      const { data } = await api.get<PaginatedResponse<Message>>(
        `/chats/${chatId}/messages`,
        {
          params: {
            limit: MESSAGE_LIMIT,
            offset: 0,
            ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
          },
        },
      )
      setMessages(data.items)
      await api.post(`/chats/${chatId}/read`, null, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setChats((current) =>
        current.map((chat) =>
          chat.id === chatId ? { ...chat, unread: false } : chat,
        ),
      )
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      if (showLoader) {
        setIsMessagesLoading(false)
      }
    }
  }, [selectedProjectId])

  useEffect(() => {
    void loadChats()
    void loadBots()
    const timer = window.setInterval(() => {
      void loadChats()
    }, 15000)

    return () => window.clearInterval(timer)
  }, [loadBots, loadChats])

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

    try {
      const { data } = await api.post<Message>(`/chats/${selectedChatId}/messages`, {
        body: text,
        message_type: 'text',
        sender_id: user?.id ?? null,
        sender_type: 'manager',
      }, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setMessages((current) => [...current, data])
      setDraft('')
      await loadChats()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsSending(false)
    }
  }

  const handleResetChat = async () => {
    if (!selectedChatId || isResettingChat) {
      return
    }

    setIsResettingChat(true)

    try {
      await api.post(`/chats/${selectedChatId}/reset`, null, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setChats((current) => current.filter((chat) => chat.id !== selectedChatId))
      setSelectedChatId(null)
      setMessages([])
      setIsResetConfirmOpen(false)
      setIsLeadOpen(false)
      notify({
        tone: 'success',
        message: 'Диалог сброшен. Если пользователь напишет снова, он начнёт путь заново.',
      })
      await loadChats()
      setSelectedChatId(null)
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsResettingChat(false)
    }
  }

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await sendMessage()
  }

  const openMedia = async (message: Message) => {
    if (!message.telegram_file_id || openingMediaId) {
      return
    }

    setOpeningMediaId(message.id)
    try {
      const { data } = await api.get<Blob>(`/messages/${message.id}/media`, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
        responseType: 'blob',
      })
      const blobUrl = window.URL.createObjectURL(data)
      const isDocument = message.message_type === 'document' || message.message_type === 'file'
      if (isDocument) {
        const link = document.createElement('a')
        link.href = blobUrl
        link.download = message.file_name || 'telegram-file'
        document.body.appendChild(link)
        link.click()
        link.remove()
        window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000)
      } else {
        window.open(blobUrl, '_blank', 'noopener,noreferrer')
        window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 15000)
      }
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) || 'Не удалось открыть медиа.' })
    } finally {
      setOpeningMediaId(null)
    }
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }

    event.preventDefault()
    void sendMessage()
  }

  return (
    <section className="relative grid h-full min-h-0 grid-cols-1 gap-4 overflow-hidden text-gray-200 xl:grid-cols-[minmax(280px,25%)_minmax(0,50%)_minmax(280px,25%)]">
      <div
        className={`h-full min-h-0 overflow-hidden ${
          selectedChat ? 'hidden xl:block' : ''
        }`}
      >
        <ChatList
          activeFilter={activeFilter}
          chats={chats}
          currentUserId={user?.id ?? null}
          getBotLabel={getBotLabel}
          isLoading={isChatsLoading}
          scopeLabel={botScopeLabel}
          selectedChatId={selectedChatId}
          total={total}
          onFilterChange={setActiveFilter}
          onRefresh={() => void loadChats()}
          onSelectChat={setSelectedChatId}
        />
      </div>

      <div className={`${selectedChat ? 'flex' : 'hidden xl:flex'} h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card`}>
        <header className="flex min-h-[73px] shrink-0 items-center justify-between gap-4 border-b border-white/5 px-4 sm:px-5">
          {selectedChat ? (
            <>
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() => setSelectedChatId(null)}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 xl:hidden"
                  title="К списку чатов"
                >
                  <ArrowLeft size={16} />
                </button>
                <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h2 className="truncate text-base font-semibold text-white">
                    {getChatTitle(selectedChat)}
                  </h2>
                  {selectedChat.is_red ? <AlertCircle size={16} className="text-red-300 drop-shadow-[0_0_10px_rgba(248,113,113,0.6)]" /> : null}
                </div>
                <p className="truncate text-sm text-gray-500">
                  {getBotLabel(selectedChat)} · Telegram ID {selectedChat.external_chat_id}
                </p>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  onClick={() => setIsLeadOpen(true)}
                  className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 xl:hidden"
                >
                  <UserRound size={15} />
                  Лид
                </button>
                <div className="hidden items-center gap-2 text-sm text-gray-500 sm:flex">
                  <CheckCheck size={16} />
                  <span>{selectedChat.last_read_at ? 'Прочитано' : 'Не прочитано'}</span>
                </div>
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <MessageSquareText size={18} />
              Выберите чат
            </div>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto bg-background/45 px-5 py-4">
          {isMessagesLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Загрузка сообщений
            </div>
          ) : null}

          {!selectedChat && !isMessagesLoading ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              Чат не выбран.
            </div>
          ) : null}

          {selectedChat && !isMessagesLoading && messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              Сообщений пока нет.
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
                        <span>{message.sender_type === 'manager' ? 'менеджер' : message.sender_type === 'bot' ? 'бот' : 'клиент'}</span>
                        <span>{formatDateTime(message.created_at)}</span>
                      </div>
                      {message.message_type === 'text' || message.message_type === 'system' ? (
                        <p className="whitespace-pre-wrap break-words text-sm leading-6">
                          {message.body || ''}
                        </p>
                      ) : (
                        <div className="space-y-2">
                          <div className="flex items-start gap-2 rounded-xl border border-white/10 bg-black/10 p-2">
                            {(() => {
                              const Icon = getMediaIcon(message.message_type)
                              const size = formatFileSize(message.file_size)
                              return (
                                <>
                                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.06]">
                                    <Icon size={16} />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <p className="truncate text-sm font-semibold">
                                      {message.file_name || getMediaLabel(message)}
                                    </p>
                                    <p className="truncate text-xs opacity-70">
                                      {[getMediaLabel(message), size].filter(Boolean).join(' · ')}
                                    </p>
                                  </div>
                                  {message.telegram_file_id ? (
                                    <button
                                      type="button"
                                      onClick={() => void openMedia(message)}
                                      disabled={openingMediaId === message.id}
                                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-60"
                                      title="Открыть медиа"
                                    >
                                      {openingMediaId === message.id ? (
                                        <LoaderCircle size={15} className="animate-spin" />
                                      ) : (
                                        <Download size={15} />
                                      )}
                                    </button>
                                  ) : null}
                                </>
                              )
                            })()}
                          </div>
                          {message.caption ? (
                            <p className="whitespace-pre-wrap break-words text-sm leading-6">
                              {message.caption}
                            </p>
                          ) : null}
                        </div>
                      )}
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
              placeholder="Ответить в Telegram"
              disabled={!selectedChat || isSending}
              rows={2}
            />
            <button
              type="submit"
              title="Отправить сообщение"
              disabled={!selectedChat || !draft.trim() || isSending}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSending ? <LoaderCircle size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
        </form>
      </div>

      <div className="hidden h-full min-h-0 xl:block">
        <LeadSidebar
          activeBotId={selectedBotIds.length === 1 ? selectedBotIds[0] : null}
          activeBotName={botScopeLabel}
          activeChatId={selectedChatId}
          hasActiveScope={Boolean(selectedProjectId)}
          currentUserId={user?.id ?? null}
          onResetRequest={() => setIsResetConfirmOpen(true)}
        />
      </div>

      {isLeadOpen ? (
        <Modal title="Карточка лида" onClose={() => setIsLeadOpen(false)} maxWidthClassName="max-w-lg">
          <div className="h-[calc(100dvh-8rem)] min-h-[360px] min-w-0">
            <LeadSidebar
              activeBotId={selectedBotIds.length === 1 ? selectedBotIds[0] : null}
              activeBotName={botScopeLabel}
              activeChatId={selectedChatId}
              hasActiveScope={Boolean(selectedProjectId)}
              currentUserId={user?.id ?? null}
              onResetRequest={() => setIsResetConfirmOpen(true)}
            />
          </div>
        </Modal>
      ) : null}

      {isResetConfirmOpen ? (
        <ConfirmDialog
          title="Сбросить диалог?"
          description="Сообщения, теги и состояние воронки будут очищены. Если пользователь напишет снова, он начнёт путь заново."
          confirmLabel="Сбросить"
          tone="danger"
          isLoading={isResettingChat}
          onCancel={() => setIsResetConfirmOpen(false)}
          onConfirm={() => void handleResetChat()}
        />
      ) : null}
    </section>
  )
}

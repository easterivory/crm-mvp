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
  Paperclip,
  Search,
  Send,
  UserRound,
  Video,
  X,
  Zap,
} from 'lucide-react'
import {
  FormEvent,
  ClipboardEvent,
  DragEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import axios from 'axios'
import { useSearchParams } from 'react-router-dom'

import api from '../api/client'
import ChatList, { Chat } from '../components/ChatList'
import LeadSidebar from '../components/LeadSidebar'
import { fetchBots, type Bot as BotRecord } from '../features/bots'
import {
  createChatFilterPreset,
  deleteChatFilterPreset,
  fetchChatFilterPresets,
  updateChatFilterPreset,
} from '../features/chats/api'
import {
  type ChatFilterPreset,
  EMPTY_CHAT_FILTERS,
  type ChatDatePreset,
  type ChatFiltersState,
  type ChatTagMode,
  type FilterOption,
} from '../features/chats/types'
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
  operator_id: string | null
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

type OutgoingMediaType = 'document' | 'photo' | 'video' | 'voice' | 'video_note'

type ChatAttachmentDraft = {
  file: File
  file_name: string
  mime_type: string
  file_size: number
  media_type: OutgoingMediaType
}

type ProjectSnippet = {
  id: string
  project_id: string
  channel: string
  name: string
  type: 'text' | OutgoingMediaType
  content: string | null
  file_id: string | null
  created_at: string
}

type ChatAuditLog = {
  id: string
  chat_id: string
  user_id: string | null
  user_name: string | null
  user_email: string | null
  event_type: string
  old_value: string | null
  new_value: string | null
  created_at: string
}

type TrackingLinkOption = {
  id: string
  code: string
  title: string
}

type ProjectTag = {
  id: string
  name: string
}

type LeadStatus = {
  id: string
  code: string
  name: string
}

type UserOptionRecord = {
  id: string
  name: string
  email: string
}

type TimelineItem =
  | { kind: 'message'; id: string; created_at: string; sequence: number; message: Message }
  | { kind: 'audit'; id: string; created_at: string; sequence: number; event: ChatAuditLog }

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

const attachmentModes: Array<{
  type: OutgoingMediaType
  label: string
  description: string
  accept: string
}> = [
  {
    type: 'document',
    label: 'Файл',
    description: 'Отправить как документ',
    accept: '*/*',
  },
  {
    type: 'photo',
    label: 'Фото',
    description: 'Нативное фото Telegram',
    accept: 'image/*',
  },
  {
    type: 'video',
    label: 'Видео',
    description: 'Нативное видео Telegram',
    accept: 'video/*',
  },
  {
    type: 'voice',
    label: 'Голосовое',
    description: 'Отправить через sendVoice',
    accept: 'audio/ogg,audio/mpeg,audio/mp4,audio/webm,audio/wav',
  },
  {
    type: 'video_note',
    label: 'Кружок',
    description: 'Отправить через sendVideoNote',
    accept: 'video/mp4,video/quicktime,video/webm',
  },
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

function isRequestCanceled(err: unknown) {
  return axios.isCancel(err) || (axios.isAxiosError(err) && err.code === 'ERR_CANCELED')
}

function externalMessageOrder(value: string | null) {
  const normalized = value?.trim() ?? ''
  if (/^\d+$/.test(normalized)) {
    return Number.parseInt(normalized, 10)
  }
  return Number.MAX_SAFE_INTEGER
}

function compareTimelineDate(
  leftCreatedAt: string,
  rightCreatedAt: string,
  leftFallback: string,
  rightFallback: string,
) {
  const dateDiff = new Date(leftCreatedAt).getTime() - new Date(rightCreatedAt).getTime()
  return dateDiff || leftFallback.localeCompare(rightFallback)
}

function sortMessagesByDate(items: Message[]) {
  return [...items].sort((left, right) => {
    const dateDiff = new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
    const externalDiff =
      externalMessageOrder(left.external_message_id) - externalMessageOrder(right.external_message_id)
    return dateDiff || externalDiff || left.id.localeCompare(right.id)
  })
}

function paramsEqual(left: URLSearchParams, right: URLSearchParams) {
  return left.toString() === right.toString()
}

function filtersEqual(left: ChatFiltersState, right: ChatFiltersState) {
  return JSON.stringify(left) === JSON.stringify(right)
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

function inferAttachmentMediaType(file: File): OutgoingMediaType {
  if (file.type.startsWith('image/')) {
    return 'photo'
  }
  if (file.type.startsWith('video/')) {
    return 'video'
  }
  if (file.type.startsWith('audio/')) {
    return 'voice'
  }
  return 'document'
}

function userLabel(user: UserOptionRecord | undefined, fallback: string) {
  if (!user) {
    return fallback
  }
  return user.name || user.email || fallback
}

function auditActor(event: ChatAuditLog) {
  return event.user_name || event.user_email || 'Система'
}

function auditEventText(event: ChatAuditLog) {
  const actor = auditActor(event)
  const oldValue = event.old_value || '—'
  const newValue = event.new_value || '—'

  if (event.event_type === 'status_change') {
    return `${actor} изменил статус: ${oldValue} → ${newValue}`
  }
  if (event.event_type === 'tag_added') {
    return `${actor} повесил тег ${newValue}`
  }
  if (event.event_type === 'manager_assigned') {
    return `${actor} назначил менеджера: ${newValue}`
  }
  if (event.event_type === 'SLA_breached') {
    return `${actor}: нарушен SLA ответа`
  }
  if (event.event_type === 'note_added') {
    return `${actor} добавил заметку: ${newValue}`
  }
  if (event.event_type === 'lead_updated') {
    return `${actor} ${newValue}`
  }
  if (event.new_value || event.old_value) {
    return `${actor}: ${event.new_value || event.old_value}`
  }
  return `${actor}: ${event.event_type}`
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

function formatFileSize(value: number | null) {
  if (!value || value <= 0) {
    return null
  }
  if (value < 1024 * 1024) {
    return `${Math.ceil(value / 1024)} КБ`
  }
  return `${(value / (1024 * 1024)).toFixed(1)} МБ`
}

function csvOrAll(params: URLSearchParams, key: string) {
  const values = params.getAll(key).filter(Boolean)
  if (values.length > 0) {
    return values
  }
  const csv = params.get(key)
  return csv ? csv.split(',').map((item) => item.trim()).filter(Boolean) : []
}

function isDatePreset(value: string | null): value is ChatDatePreset {
  return value === '' || value === 'today' || value === 'yesterday' || value === '7d'
    || value === '30d' || value === 'custom'
}

function isFunnelState(value: string | null): value is ChatFiltersState['funnelState'] {
  return value === '' || value === 'in_funnel' || value === 'waiting_for_answer'
    || value === 'completed' || value === 'manual'
}

function isTagMode(value: string | null): value is ChatTagMode {
  return value === 'any' || value === 'all'
}

function isQuickFilter(value: string | null): value is ChatFiltersState['quickFilter'] {
  return value === '' || value === 'all' || value === 'mine'
    || value === 'unanswered' || value === 'hot'
}

function normalizeChatFilters(value: Partial<ChatFiltersState> | null | undefined) {
  return {
    ...EMPTY_CHAT_FILTERS,
    ...(value ?? {}),
    q: typeof value?.q === 'string' ? value.q : '',
    datePreset: isDatePreset(value?.datePreset ?? null) ? value?.datePreset ?? '' : '',
    tagIds: Array.isArray(value?.tagIds) ? value.tagIds.filter(Boolean) : [],
    tagMode: isTagMode(value?.tagMode ?? null) ? value?.tagMode ?? 'any' : 'any',
    leadStatuses: Array.isArray(value?.leadStatuses)
      ? value.leadStatuses.filter(Boolean)
      : [],
    quickFilter: isQuickFilter(value?.quickFilter ?? null) ? value?.quickFilter ?? '' : '',
  }
}

function readChatFilters(params: URLSearchParams): ChatFiltersState {
  const datePreset = params.get('date_preset')
  const funnelState = params.get('funnel_state')
  const tagMode = params.get('tag_mode')
  const quickFilter = params.get('quick_filter')
  return {
    ...EMPTY_CHAT_FILTERS,
    q: params.get('q') ?? '',
    datePreset: isDatePreset(datePreset) ? datePreset : '',
    dateFrom: params.get('date_from') ?? '',
    dateTo: params.get('date_to') ?? '',
    tagIds: csvOrAll(params, 'tag_ids'),
    tagMode: isTagMode(tagMode) ? tagMode : 'any',
    leadStatuses: csvOrAll(params, 'lead_statuses'),
    trackingLinkId: params.get('tracking_link_id') ?? '',
    funnelState: isFunnelState(funnelState) ? funnelState : '',
    hasUnansweredIncoming: params.get('has_unanswered_incoming') === 'true',
    isRed: params.get('is_red') === 'true',
    assignedUserId: params.get('assigned_user_id') ?? '',
    unassigned: params.get('unassigned') === 'true',
    quickFilter: isQuickFilter(quickFilter) ? quickFilter : '',
  }
}

function writeChatFilters(filters: ChatFiltersState) {
  const params = new URLSearchParams()
  const q = filters.q.trim()
  if (q) params.set('q', q)
  if (filters.datePreset) params.set('date_preset', filters.datePreset)
  if (filters.dateFrom) params.set('date_from', filters.dateFrom)
  if (filters.dateTo) params.set('date_to', filters.dateTo)
  for (const tagId of filters.tagIds) params.append('tag_ids', tagId)
  if (filters.tagIds.length > 0 && filters.tagMode !== 'any') {
    params.set('tag_mode', filters.tagMode)
  }
  for (const status of filters.leadStatuses) params.append('lead_statuses', status)
  if (filters.trackingLinkId) params.set('tracking_link_id', filters.trackingLinkId)
  if (filters.funnelState) params.set('funnel_state', filters.funnelState)
  if (filters.hasUnansweredIncoming) params.set('has_unanswered_incoming', 'true')
  if (filters.isRed) params.set('is_red', 'true')
  if (filters.assignedUserId) params.set('assigned_user_id', filters.assignedUserId)
  if (filters.unassigned) params.set('unassigned', 'true')
  if (filters.quickFilter) params.set('quick_filter', filters.quickFilter)
  return params
}

function useDebouncedValue<T>(value: T, delayMs: number) {
  const [debouncedValue, setDebouncedValue] = useState(value)

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedValue(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [delayMs, value])

  return debouncedValue
}

export default function ChatsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const user = useAuthStore((state) => state.user)
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const notify = useNotificationStore((state) => state.notify)

  const [chats, setChats] = useState<Chat[]>([])
  const [bots, setBots] = useState<BotRecord[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [auditLogs, setAuditLogs] = useState<ChatAuditLog[]>([])
  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])
  const [trackingOptions, setTrackingOptions] = useState<FilterOption[]>([])
  const [tagOptions, setTagOptions] = useState<FilterOption[]>([])
  const [statusOptions, setStatusOptions] = useState<FilterOption[]>([])
  const [userOptions, setUserOptions] = useState<FilterOption[]>([])
  const [users, setUsers] = useState<UserOptionRecord[]>([])
  const [filterPresets, setFilterPresets] = useState<ChatFilterPreset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [total, setTotal] = useState(0)
  const [selectedChatId, setSelectedChatId] = useState<string | null>(() =>
    searchParams.get('chat_id'),
  )
  const [chatFilters, setChatFilters] = useState<ChatFiltersState>(() =>
    readChatFilters(searchParams),
  )
  const debouncedChatFilters = useDebouncedValue(chatFilters, 350)
  const [draft, setDraft] = useState('')
  const [isChatsLoading, setIsChatsLoading] = useState(true)
  const [isMessagesLoading, setIsMessagesLoading] = useState(false)
  const [isSnippetsLoading, setIsSnippetsLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [attachment, setAttachment] = useState<ChatAttachmentDraft | null>(null)
  const [attachmentMode, setAttachmentMode] = useState<OutgoingMediaType>('document')
  const [isAttachmentMenuOpen, setIsAttachmentMenuOpen] = useState(false)
  const [attachmentPreviewUrl, setAttachmentPreviewUrl] = useState<string | null>(null)
  const [isDraggingAttachment, setIsDraggingAttachment] = useState(false)
  const [isSnippetsOpen, setIsSnippetsOpen] = useState(false)
  const [snippetSearch, setSnippetSearch] = useState('')
  const [openingMediaId, setOpeningMediaId] = useState<string | null>(null)
  const [isResetConfirmOpen, setIsResetConfirmOpen] = useState(false)
  const [isResettingChat, setIsResettingChat] = useState(false)
  const [isLeadOpen, setIsLeadOpen] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  const attachmentInputRef = useRef<HTMLInputElement | null>(null)
  const previousProjectIdRef = useRef(selectedProjectId)
  const selectedChatIdRef = useRef<string | null>(selectedChatId)
  const searchParamsRef = useRef(searchParams)
  const setSearchParamsRef = useRef(setSearchParams)
  const chatsRef = useRef<Chat[]>([])
  const chatsAbortRef = useRef<AbortController | null>(null)
  const messagesAbortRef = useRef<AbortController | null>(null)
  const selectedChatAbortRef = useRef<AbortController | null>(null)

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  )
  const selectedPreset = useMemo(
    () => filterPresets.find((preset) => preset.id === selectedPresetId) ?? null,
    [filterPresets, selectedPresetId],
  )
  const isSelectedPresetDirty = useMemo(() => {
    if (!selectedPreset) {
      return false
    }
    return JSON.stringify(normalizeChatFilters(selectedPreset.filters_json)) !== JSON.stringify(chatFilters)
  }, [chatFilters, selectedPreset])
  const canManageSharedPresets = user?.role_name === 'admin' || user?.role_name === 'super_admin'
  const highlightedMessageId = selectedChat?.search_hit_message_id ?? null
  const userById = useMemo(() => new Map(users.map((item) => [item.id, item])), [users])
  const timelineItems = useMemo<TimelineItem[]>(
    () =>
      [
        ...messages.map((message, index) => ({
          kind: 'message' as const,
          id: message.id,
          created_at: message.created_at,
          sequence: index,
          message,
        })),
        ...auditLogs.map((event, index) => ({
          kind: 'audit' as const,
          id: event.id,
          created_at: event.created_at,
          sequence: messages.length + index,
          event,
        })),
      ].sort((left, right) => {
        return compareTimelineDate(
          left.created_at,
          right.created_at,
          `${left.sequence}:${left.id}`,
          `${right.sequence}:${right.id}`,
        )
      }),
    [auditLogs, messages],
  )
  const filteredSnippets = useMemo(() => {
    const needle = snippetSearch.trim().toLowerCase()
    if (!needle) {
      return snippets
    }
    return snippets.filter((snippet) =>
      [snippet.name, snippet.content ?? '', mediaLabels[snippet.type] ?? snippet.type]
        .join(' ')
        .toLowerCase()
        .includes(needle),
    )
  }, [snippetSearch, snippets])

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

  useEffect(() => {
    selectedChatIdRef.current = selectedChatId
  }, [selectedChatId])

  useEffect(() => {
    searchParamsRef.current = searchParams
  }, [searchParams])

  useEffect(() => {
    setSearchParamsRef.current = setSearchParams
  }, [setSearchParams])

  useEffect(() => {
    chatsRef.current = chats
  }, [chats])

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

  const syncChatSearchParams = useCallback(
    (filters: ChatFiltersState, chatId: string | null) => {
      const params = writeChatFilters(filters)
      if (chatId) {
        params.set('chat_id', chatId)
      }
      if (paramsEqual(params, searchParamsRef.current)) {
        return
      }
      searchParamsRef.current = params
      setSearchParamsRef.current(params, { replace: true })
    },
    [],
  )

  const handleSelectChat = useCallback(
    (chatId: string) => {
      selectedChatIdRef.current = chatId
      setSelectedChatId(chatId)
      syncChatSearchParams(chatFilters, chatId)
    },
    [chatFilters, syncChatSearchParams],
  )

  const handleClearSelectedChat = useCallback(() => {
    selectedChatIdRef.current = null
    setSelectedChatId(null)
    syncChatSearchParams(chatFilters, null)
  }, [chatFilters, syncChatSearchParams])

  useEffect(() => {
    const chatIdFromUrl = searchParams.get('chat_id')
    if (chatIdFromUrl !== selectedChatIdRef.current) {
      selectedChatIdRef.current = chatIdFromUrl
      setSelectedChatId(chatIdFromUrl)
    }

    const filtersFromUrl = readChatFilters(searchParams)
    setChatFilters((current) => (filtersEqual(current, filtersFromUrl) ? current : filtersFromUrl))
  }, [searchParams])

  useEffect(() => {
    syncChatSearchParams(chatFilters, selectedChatId)
  }, [chatFilters, selectedChatId, syncChatSearchParams])

  const loadChats = useCallback(async () => {
    if (!selectedProjectId) {
      setChats([])
      setTotal(0)
      selectedChatIdRef.current = null
      setSelectedChatId(null)
      setIsChatsLoading(false)
      return
    }

    chatsAbortRef.current?.abort()
    const controller = new AbortController()
    chatsAbortRef.current = controller
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

      if (debouncedChatFilters.q.trim()) {
        params.q = debouncedChatFilters.q.trim()
      }
      if (debouncedChatFilters.hasUnansweredIncoming) {
        params.has_unanswered_incoming = true
      }
      if (debouncedChatFilters.isRed) {
        params.is_red = true
      }
      if (debouncedChatFilters.assignedUserId) {
        params.assigned_user_id = debouncedChatFilters.assignedUserId
      }
      if (debouncedChatFilters.unassigned) {
        params.unassigned = true
      }
      if (debouncedChatFilters.trackingLinkId) {
        params.tracking_link_id = debouncedChatFilters.trackingLinkId
      }
      if (debouncedChatFilters.dateFrom) {
        params.date_from = debouncedChatFilters.dateFrom
      }
      if (debouncedChatFilters.dateTo) {
        params.date_to = debouncedChatFilters.dateTo
      }
      if (debouncedChatFilters.tagIds.length > 0) {
        params.tag_ids = debouncedChatFilters.tagIds.join(',')
        params.tag_mode = debouncedChatFilters.tagMode
      }
      if (debouncedChatFilters.leadStatuses.length > 0) {
        params.lead_statuses = debouncedChatFilters.leadStatuses.join(',')
      }
      if (debouncedChatFilters.funnelState) {
        params.funnel_state = debouncedChatFilters.funnelState
      }

      const { data } = await api.get<PaginatedResponse<Chat>>('/chats', {
        params,
        signal: controller.signal,
      })
      if (controller.signal.aborted) {
        return
      }
      setChats((current) => {
        const currentSelectedChatId = selectedChatIdRef.current
        const selected = currentSelectedChatId
          ? current.find((chat) => chat.id === currentSelectedChatId)
          : null
        if (selected && !data.items.some((chat) => chat.id === selected.id)) {
          return [selected, ...data.items]
        }
        return data.items
      })
      setTotal(data.total)
      if (!selectedChatIdRef.current) {
        const nextChatId = data.items[0]?.id ?? null
        selectedChatIdRef.current = nextChatId
        setSelectedChatId(nextChatId)
        syncChatSearchParams(debouncedChatFilters, nextChatId)
      } else if (!data.items.some((chat) => chat.id === selectedChatIdRef.current)) {
        const selected = chatsRef.current.find((chat) => chat.id === selectedChatIdRef.current)
        if (!selected) {
          selectedChatIdRef.current = null
          setSelectedChatId(null)
          setMessages([])
          setAuditLogs([])
          syncChatSearchParams(debouncedChatFilters, null)
        }
      }
    } catch (err) {
      if (isRequestCanceled(err)) {
        return
      }
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      if (chatsAbortRef.current === controller) {
        chatsAbortRef.current = null
        setIsChatsLoading(false)
      }
    }
  }, [
    debouncedChatFilters,
    notify,
    selectedBotIds,
    selectedProjectId,
    syncChatSearchParams,
  ])

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

  const loadFilterOptions = useCallback(async () => {
    if (!selectedProjectId) {
      setTrackingOptions([])
      setTagOptions([])
      setStatusOptions([])
      setUserOptions([])
      setUsers([])
      return
    }

    try {
      const [trackingResponse, tagsResponse, statusesResponse, usersResponse] = await Promise.all([
        api.get<PaginatedResponse<TrackingLinkOption>>('/tracking/links', {
          params: {
            project_id: selectedProjectId,
            limit: 100,
            offset: 0,
            ...(selectedBotIds.length === 1 ? { bot_id: selectedBotIds[0] } : {}),
          },
        }),
        api.get<PaginatedResponse<ProjectTag>>('/tags', {
          params: {
            project_id: selectedProjectId,
            limit: 100,
            offset: 0,
          },
        }),
        api.get<LeadStatus[]>('/leads/statuses'),
        api.get<PaginatedResponse<UserOptionRecord>>('/users', {
          params: {
            project_id: selectedProjectId,
            limit: 100,
            offset: 0,
          },
        }),
      ])
      setTrackingOptions(
        trackingResponse.data.items.map((link) => ({
          id: link.id,
          label: `${link.title} · ${link.code}`,
        })),
      )
      setTagOptions(tagsResponse.data.items.map((tag) => ({ id: tag.id, label: tag.name })))
      setStatusOptions(
        statusesResponse.data.map((status) => ({
          id: status.code,
          label: status.name,
        })),
      )
      setUserOptions(
        usersResponse.data.items.map((item) => ({
          id: item.id,
          label: item.name || item.email,
        })),
      )
      setUsers(usersResponse.data.items)
    } catch {
      setTrackingOptions([])
      setTagOptions([])
      setStatusOptions([])
      setUserOptions([])
      setUsers([])
    }
  }, [selectedBotIds, selectedProjectId])

  const loadFilterPresets = useCallback(async () => {
    if (!selectedProjectId) {
      setFilterPresets([])
      setSelectedPresetId('')
      return
    }
    try {
      const presets = await fetchChatFilterPresets(selectedProjectId)
      setFilterPresets(
        presets.map((preset) => ({
          ...preset,
          filters_json: normalizeChatFilters(preset.filters_json),
        })),
      )
    } catch {
      setFilterPresets([])
    }
  }, [selectedProjectId])

  const loadSnippets = useCallback(async () => {
    if (!selectedProjectId) {
      setSnippets([])
      return
    }

    setIsSnippetsLoading(true)
    try {
      const { data } = await api.get<ProjectSnippet[]>(
        `/projects/${selectedProjectId}/snippets`,
      )
      setSnippets(data)
    } catch (err) {
      setSnippets([])
      if (!axios.isAxiosError(err) || err.response?.status !== 403) {
        notify({ tone: 'error', message: getErrorMessage(err) })
      }
    } finally {
      setIsSnippetsLoading(false)
    }
  }, [notify, selectedProjectId])

  const loadSelectedChat = useCallback(async (chatId: string) => {
    if (!selectedProjectId) {
      return
    }

    selectedChatAbortRef.current?.abort()
    const controller = new AbortController()
    selectedChatAbortRef.current = controller
    try {
      const { data } = await api.get<Chat>(`/chats/${chatId}`, {
        params: { project_id: selectedProjectId },
        signal: controller.signal,
      })
      if (controller.signal.aborted || selectedChatIdRef.current !== chatId) {
        return
      }
      setChats((current) =>
        current.some((chat) => chat.id === data.id) ? current : [data, ...current],
      )
    } catch (err) {
      if (isRequestCanceled(err)) {
        return
      }
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      if (selectedChatAbortRef.current === controller) {
        selectedChatAbortRef.current = null
      }
    }
  }, [notify, selectedProjectId])

  const loadMessages = useCallback(async (chatId: string, showLoader = false) => {
    if (!showLoader && messagesAbortRef.current) {
      return
    }

    messagesAbortRef.current?.abort()
    const controller = new AbortController()
    messagesAbortRef.current = controller
    if (showLoader) {
      setIsMessagesLoading(true)
    }

    try {
      const params = {
        limit: MESSAGE_LIMIT,
        offset: 0,
        ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
      }
      const [messagesResponse, auditResponse] = await Promise.all([
        api.get<PaginatedResponse<Message>>(`/chats/${chatId}/messages`, {
          params,
          signal: controller.signal,
        }),
        api.get<ChatAuditLog[]>(`/chats/${chatId}/audit-logs`, {
          params: {
            limit: MESSAGE_LIMIT,
            offset: 0,
            ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
          },
          signal: controller.signal,
        }),
      ])
      if (controller.signal.aborted || selectedChatIdRef.current !== chatId) {
        return
      }
      setMessages(sortMessagesByDate(messagesResponse.data.items))
      setAuditLogs(auditResponse.data)
      await api.post(`/chats/${chatId}/read`, null, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
        signal: controller.signal,
      })
      if (controller.signal.aborted || selectedChatIdRef.current !== chatId) {
        return
      }
      setChats((current) =>
        current.some((chat) => chat.id === chatId && (chat.unread || !chat.is_read))
          ? current.map((chat) =>
              chat.id === chatId ? { ...chat, unread: false, is_read: true } : chat,
            )
          : current,
      )
    } catch (err) {
      if (isRequestCanceled(err)) {
        return
      }
      if (showLoader) {
        notify({ tone: 'error', message: getErrorMessage(err) })
      }
    } finally {
      const isCurrentRequest = messagesAbortRef.current === controller
      if (isCurrentRequest) {
        messagesAbortRef.current = null
      }
      if (showLoader && isCurrentRequest) {
        setIsMessagesLoading(false)
      }
    }
  }, [notify, selectedProjectId])

  useEffect(() => {
    void loadChats()
    void loadBots()
    void loadFilterOptions()
    void loadFilterPresets()
    void loadSnippets()
    const timer = window.setInterval(() => {
      void loadChats()
    }, 15000)

    return () => {
      window.clearInterval(timer)
      chatsAbortRef.current?.abort()
    }
  }, [loadBots, loadChats, loadFilterOptions, loadFilterPresets, loadSnippets])

  useEffect(() => {
    if (previousProjectIdRef.current === selectedProjectId) {
      return
    }
    previousProjectIdRef.current = selectedProjectId

    setChatFilters(EMPTY_CHAT_FILTERS)
    setSelectedPresetId('')
    selectedChatIdRef.current = null
    setSelectedChatId(null)
    setMessages([])
    setAuditLogs([])
    syncChatSearchParams(EMPTY_CHAT_FILTERS, null)
  }, [selectedProjectId, syncChatSearchParams])

  useEffect(() => {
    if (!selectedChatId) {
      messagesAbortRef.current?.abort()
      setMessages([])
      setAuditLogs([])
      setIsMessagesLoading(false)
      return undefined
    }
    if (selectedChat && selectedChat.project_id !== selectedProjectId) {
      return undefined
    }

    setMessages([])
    setAuditLogs([])
    void loadMessages(selectedChatId, true)
    const timer = window.setInterval(() => {
      void loadMessages(selectedChatId)
    }, 7000)

    return () => {
      window.clearInterval(timer)
      messagesAbortRef.current?.abort()
    }
  }, [loadMessages, selectedChat?.project_id, selectedChatId, selectedProjectId])

  useEffect(() => {
    if (selectedChatId && !selectedChat && selectedProjectId) {
      void loadSelectedChat(selectedChatId)
    }
  }, [loadSelectedChat, selectedChat, selectedChatId, selectedProjectId])

  useEffect(() => {
    setAttachment(null)
    setDraft('')
    setIsAttachmentMenuOpen(false)
    setIsSnippetsOpen(false)
    setSnippetSearch('')
    if (attachmentPreviewUrl) {
      window.URL.revokeObjectURL(attachmentPreviewUrl)
      setAttachmentPreviewUrl(null)
    }
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = ''
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChatId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ block: 'end' })
  }, [timelineItems])

  useEffect(() => {
    if (!highlightedMessageId) {
      return undefined
    }
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(`message-${highlightedMessageId}`)?.scrollIntoView({
        block: 'center',
        behavior: 'smooth',
      })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [highlightedMessageId, messages])

  const sendMessage = async () => {
    const text = draft.trim()
    if (!selectedChatId || (!text && !attachment) || isSending) {
      return
    }

    setIsSending(true)

    try {
      const params = selectedProjectId ? { project_id: selectedProjectId } : undefined
      const { data } = attachment
        ? await api.post<Message>(
            `/chats/${selectedChatId}/messages`,
            (() => {
              const formData = new FormData()
              formData.append('media_type', attachment.media_type)
              formData.append('file', attachment.file, attachment.file.name)
              if (text) {
                formData.append('text', text)
              }
              return formData
            })(),
            { params },
          )
        : await api.post<Message>(
            `/chats/${selectedChatId}/messages`,
            {
              media_type: 'text',
              text,
            },
            { params },
          )
      setMessages((current) => sortMessagesByDate([...current, data]))
      setDraft('')
      clearAttachment()
      await loadChats()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsSending(false)
    }
  }

  const sendSnippet = async (snippet: ProjectSnippet) => {
    if (!selectedChatId || isSending) {
      return
    }
    if (snippet.type === 'text') {
      setDraft(snippet.content ?? '')
      setIsSnippetsOpen(false)
      return
    }

    setIsSending(true)
    try {
      const { data } = await api.post<Message>(
        `/chats/${selectedChatId}/messages`,
        {
          snippet_id: snippet.id,
          ...(draft.trim() ? { text: draft.trim() } : {}),
        },
        {
          params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
        },
      )
      setMessages((current) => sortMessagesByDate([...current, data]))
      setDraft('')
      clearAttachment()
      setIsSnippetsOpen(false)
      await loadChats()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsSending(false)
    }
  }

  const clearAttachment = () => {
    setAttachment(null)
    setIsAttachmentMenuOpen(false)
    if (attachmentPreviewUrl) {
      window.URL.revokeObjectURL(attachmentPreviewUrl)
      setAttachmentPreviewUrl(null)
    }
    if (attachmentInputRef.current) {
      attachmentInputRef.current.value = ''
    }
  }

  const setAttachmentFromFile = (file: File, mediaType: OutgoingMediaType) => {
    clearAttachment()
    setAttachment({
      file,
      file_name: file.name || mediaLabels[mediaType] || 'attachment',
      mime_type: file.type || 'application/octet-stream',
      file_size: file.size,
      media_type: mediaType,
    })
    if (mediaType === 'photo' && file.type.startsWith('image/')) {
      setAttachmentPreviewUrl(window.URL.createObjectURL(file))
    }
  }

  const handleAttachmentSelected = (file: File | null | undefined) => {
    if (!file || !selectedChatId) {
      return
    }
    setAttachmentFromFile(file, attachmentMode)
  }

  const handleAttachmentDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDraggingAttachment(false)
    const file = event.dataTransfer.files?.[0]
    if (file) {
      setAttachmentFromFile(file, inferAttachmentMediaType(file))
    }
  }

  const handleComposerPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const file = Array.from(event.clipboardData.files).find((item) =>
      item.type.startsWith('image/'),
    )
    if (!file) {
      return
    }
    event.preventDefault()
    setAttachmentFromFile(file, 'photo')
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
      handleClearSelectedChat()
      setMessages([])
      setAuditLogs([])
      setIsResetConfirmOpen(false)
      setIsLeadOpen(false)
      notify({
        tone: 'success',
        message: 'Диалог сброшен. Если пользователь напишет снова, он начнёт путь заново.',
      })
      await loadChats()
      handleClearSelectedChat()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsResettingChat(false)
    }
  }

  const handleApplyPreset = (preset: ChatFilterPreset) => {
    setSelectedPresetId(preset.id)
    setChatFilters(normalizeChatFilters(preset.filters_json))
  }

  const handleSavePreset = async (
    name: string,
    isShared: boolean,
    filters: ChatFiltersState = chatFilters,
  ) => {
    if (!selectedProjectId) {
      return
    }
    try {
      const preset = await createChatFilterPreset({
        project_id: selectedProjectId,
        name,
        filters_json: normalizeChatFilters(filters),
        is_shared: isShared,
      })
      const normalizedPreset = {
        ...preset,
        filters_json: normalizeChatFilters(preset.filters_json),
      }
      setFilterPresets((current) => [
        normalizedPreset,
        ...current.filter((item) => item.id !== preset.id),
      ])
      setSelectedPresetId(preset.id)
      notify({ tone: 'success', message: 'Фильтр сохранён.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleUpdatePreset = async (presetId: string) => {
    try {
      const preset = await updateChatFilterPreset(presetId, {
        filters_json: normalizeChatFilters(chatFilters),
      })
      const normalizedPreset = {
        ...preset,
        filters_json: normalizeChatFilters(preset.filters_json),
      }
      setFilterPresets((current) =>
        current.map((item) => (item.id === preset.id ? normalizedPreset : item)),
      )
      setSelectedPresetId(preset.id)
      notify({ tone: 'success', message: 'Шаблон обновлён.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleDeletePreset = async (presetId: string) => {
    try {
      await deleteChatFilterPreset(presetId)
      setFilterPresets((current) => current.filter((preset) => preset.id !== presetId))
      if (selectedPresetId === presetId) {
        setSelectedPresetId('')
      }
      notify({ tone: 'success', message: 'Шаблон удалён.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
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

  const openAttachmentPicker = (mediaType: OutgoingMediaType) => {
    const mode = attachmentModes.find((item) => item.type === mediaType)
    setAttachmentMode(mediaType)
    setIsAttachmentMenuOpen(false)
    if (attachmentInputRef.current) {
      attachmentInputRef.current.accept = mode?.accept ?? '*/*'
      attachmentInputRef.current.click()
    }
  }

  return (
    <section className="relative grid h-full min-h-0 grid-cols-1 gap-4 overflow-hidden text-gray-200 xl:grid-cols-[minmax(280px,25%)_minmax(0,50%)_minmax(280px,25%)]">
      <div
        className={`h-full min-h-0 overflow-hidden ${
          selectedChat ? 'hidden xl:block' : ''
        }`}
      >
        <ChatList
          chats={chats}
          currentUserId={user?.id ?? null}
          canManageSharedPresets={canManageSharedPresets}
          filters={chatFilters}
          filterPresets={filterPresets}
          getBotLabel={getBotLabel}
          isSelectedPresetDirty={isSelectedPresetDirty}
          trackingOptions={trackingOptions}
          tagOptions={tagOptions}
          statusOptions={statusOptions}
          userOptions={userOptions}
          isLoading={isChatsLoading}
          scopeLabel={botScopeLabel}
          selectedChatId={selectedChatId}
          total={total}
          onFiltersChange={setChatFilters}
          onApplyPreset={handleApplyPreset}
          onDeletePreset={(presetId) => void handleDeletePreset(presetId)}
          onResetFilters={() => setChatFilters(EMPTY_CHAT_FILTERS)}
          onRefresh={() => void loadChats()}
          onSavePreset={(name, isShared) => void handleSavePreset(name, isShared)}
          onSelectChat={handleSelectChat}
          onUpdatePreset={(presetId) => void handleUpdatePreset(presetId)}
          selectedPresetId={selectedPresetId}
        />
      </div>

      <div
        className={`${selectedChat ? 'flex' : 'hidden xl:flex'} relative h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card`}
        onDragEnter={(event) => {
          if (event.dataTransfer.types.includes('Files')) {
            event.preventDefault()
            setIsDraggingAttachment(true)
          }
        }}
        onDragOver={(event) => {
          if (event.dataTransfer.types.includes('Files')) {
            event.preventDefault()
            setIsDraggingAttachment(true)
          }
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setIsDraggingAttachment(false)
          }
        }}
        onDrop={handleAttachmentDrop}
      >
        <header className="flex min-h-[96px] shrink-0 items-center justify-between gap-4 border-b border-white/5 px-4 sm:px-5">
          {selectedChat ? (
            <>
              <div className="flex min-w-0 items-center gap-3">
                <button
                  type="button"
                  onClick={handleClearSelectedChat}
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
                <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                  <span className="truncate">
                    Воронка:{' '}
                    {selectedChat.active_funnel_name
                      ? `${selectedChat.active_funnel_name} v${selectedChat.active_funnel_version_number ?? '—'}`
                      : 'не выбрана'}
                  </span>
                  <span className="rounded-full bg-sky-400/10 px-2 py-0.5 text-sky-200">
                    {getLifecycleLabel(selectedChat)}
                  </span>
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
                  <span>{selectedChat.is_read ? 'Прочитано' : 'Не прочитано'}</span>
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

          {selectedChat && !isMessagesLoading && timelineItems.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              Сообщений пока нет.
            </div>
          ) : null}

          {selectedChat && !isMessagesLoading && timelineItems.length > 0 ? (
            <div className="space-y-3">
              {timelineItems.map((item) => {
                if (item.kind === 'audit') {
                  return (
                    <div key={item.id} className="flex justify-center px-4">
                      <div className="max-w-[86%] rounded-full border border-white/8 bg-white/[0.045] px-3 py-1.5 text-center text-xs leading-5 text-gray-400">
                        <span className="text-gray-500">{formatDateTime(item.event.created_at)} · </span>
                        {auditEventText(item.event)}
                      </div>
                    </div>
                  )
                }
                const message = item.message
                const isOutgoing =
                  message.sender_type === 'manager' || message.sender_type === 'bot'
                const isBot = message.sender_type === 'bot'
                const operator = userById.get(message.operator_id ?? message.sender_id ?? '')
                const operatorName = userLabel(
                  operator,
                  message.operator_id === user?.id
                    ? user.name || user.email || 'CRM'
                    : message.operator_id
                      ? 'CRM'
                      : 'Менеджер',
                )

                return (
                  <div
                    id={`message-${message.id}`}
                    key={message.id}
                    className={`flex ${isOutgoing ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`flex max-w-[72%] flex-col ${isOutgoing ? 'items-end' : 'items-start'}`}
                    >
                      <div
                      className={`w-fit max-w-full rounded-2xl border px-3 py-2 shadow-sm transition ${
                        isOutgoing
                          ? isBot
                            ? 'border-accent-300/25 bg-accent-400/10 text-accent-50 shadow-glow-accent'
                            : 'border-primary-300/25 bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary'
                          : 'border-white/10 bg-white/[0.055] text-gray-100'
                      } ${
                        highlightedMessageId === message.id
                          ? 'ring-2 ring-amber-300/70'
                          : ''
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
                      {message.sender_type === 'manager' ? (
                        <p className="mt-1 max-w-full truncate px-1 text-[11px] leading-4 text-gray-500">
                          Отправил: {operatorName}
                        </p>
                      ) : null}
                    </div>
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>
          ) : null}
        </div>

        <form className="shrink-0 border-t border-white/5 bg-surface/80 p-4" onSubmit={handleSend}>
          {attachment ? (
            <div className="mb-3 flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.04] p-3">
              {attachment.media_type === 'photo' && attachmentPreviewUrl ? (
                <img
                  src={attachmentPreviewUrl}
                  alt=""
                  className="h-12 w-12 shrink-0 rounded-lg object-cover"
                />
              ) : (
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.06]">
                  {(() => {
                    const Icon = getMediaIcon(attachment.media_type)
                    return <Icon size={18} />
                  })()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-white">{attachment.file_name}</p>
                <p className="text-xs text-gray-500">
                  {[mediaLabels[attachment.media_type], formatFileSize(attachment.file_size)].filter(Boolean).join(' · ')}
                </p>
              </div>
              <button
                type="button"
                onClick={clearAttachment}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-red-300/40 hover:text-red-100"
                title="Убрать вложение"
              >
                <X size={16} />
              </button>
            </div>
          ) : null}
          <div className="flex min-h-[52px] items-end gap-2 rounded-xl border border-white/10 bg-background/70 p-2 transition focus-within:border-accent-300/45 focus-within:ring-2 focus-within:ring-accent-400/25">
            <input
              ref={attachmentInputRef}
              type="file"
              accept={attachmentModes.find((mode) => mode.type === attachmentMode)?.accept ?? '*/*'}
              className="hidden"
              onChange={(event) => handleAttachmentSelected(event.target.files?.[0])}
            />
            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => setIsAttachmentMenuOpen((value) => !value)}
                disabled={!selectedChat || isSending}
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                title="Прикрепить файл"
              >
                <Paperclip size={18} />
              </button>
              {isAttachmentMenuOpen ? (
                <div className="absolute bottom-full left-0 z-30 mb-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-[#0B0F19]/98 p-2 shadow-card backdrop-blur-xl">
                  {attachmentModes.map((mode) => {
                    const Icon = getMediaIcon(mode.type)
                    return (
                      <button
                        key={mode.type}
                        type="button"
                        onClick={() => openAttachmentPicker(mode.type)}
                        className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-white/[0.05]"
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.05] text-accent-100">
                          <Icon size={16} />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-sm font-medium text-white">{mode.label}</span>
                          <span className="block truncate text-xs text-gray-500">
                            {mode.description}
                          </span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              ) : null}
            </div>
            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => setIsSnippetsOpen((value) => !value)}
                disabled={!selectedChat || isSending || isSnippetsLoading}
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                title="Быстрые ответы"
              >
                {isSnippetsLoading ? (
                  <LoaderCircle size={17} className="animate-spin" />
                ) : (
                  <Zap size={17} />
                )}
              </button>
              {isSnippetsOpen ? (
                <div className="absolute bottom-full left-0 z-30 mb-2 w-[min(360px,calc(100vw-2rem))] overflow-hidden rounded-xl border border-white/10 bg-[#0B0F19]/98 p-3 shadow-card backdrop-blur-xl">
                  <label className="relative block">
                    <Search
                      size={15}
                      className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
                    />
                    <input
                      value={snippetSearch}
                      onChange={(event) => setSnippetSearch(event.target.value)}
                      placeholder="Найти заготовку"
                      className="h-10 w-full rounded-lg border border-white/10 bg-background/70 pl-9 pr-3 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                    />
                  </label>
                  <div className="mt-2 max-h-72 overflow-y-auto pr-1">
                    {filteredSnippets.length > 0 ? (
                      <div className="space-y-1">
                        {filteredSnippets.map((snippet) => {
                          const Icon = getMediaIcon(snippet.type)
                          return (
                            <button
                              key={snippet.id}
                              type="button"
                              onClick={() => void sendSnippet(snippet)}
                              disabled={isSending}
                              className="flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.05] text-accent-100">
                                <Icon size={16} />
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="flex items-center gap-2">
                                  <span className="truncate text-sm font-semibold text-white">
                                    {snippet.name}
                                  </span>
                                  <span className="shrink-0 rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-gray-400">
                                    {mediaLabels[snippet.type] ?? snippet.type}
                                  </span>
                                </span>
                                {snippet.content ? (
                                  <span className="mt-0.5 line-clamp-2 text-xs leading-5 text-gray-500">
                                    {snippet.content}
                                  </span>
                                ) : null}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="px-2 py-5 text-center text-sm text-gray-500">
                        Заготовки не найдены
                      </p>
                    )}
                  </div>
                </div>
              ) : null}
            </div>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              onPaste={handleComposerPaste}
              className="max-h-32 min-h-10 flex-1 resize-none overflow-y-auto rounded-lg border-0 bg-transparent px-2 py-2 text-sm leading-6 text-gray-100 outline-none placeholder:text-gray-600 disabled:text-gray-500"
              placeholder={attachment ? 'Добавить подпись к вложению' : 'Ответить в Telegram'}
              disabled={!selectedChat || isSending}
              rows={1}
            />
            <button
              type="submit"
              title="Отправить сообщение"
              disabled={!selectedChat || (!draft.trim() && !attachment) || isSending}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSending ? <LoaderCircle size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
        </form>
        {isDraggingAttachment ? (
          <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-background/75 backdrop-blur-sm">
            <div className="rounded-2xl border border-dashed border-accent-300/70 bg-surface/95 px-6 py-5 text-center shadow-glow-accent">
              <Paperclip size={24} className="mx-auto mb-2 text-accent-200" />
              <p className="text-sm font-semibold text-white">Отпустите файл, чтобы прикрепить</p>
              <p className="mt-1 text-xs text-gray-400">Фото, видео или документ</p>
            </div>
          </div>
        ) : null}
      </div>

      <div className="hidden h-full min-h-0 xl:block">
        <LeadSidebar
          activeBotId={selectedBotIds.length === 1 ? selectedBotIds[0] : null}
          activeBotName={botScopeLabel}
          activeChatId={selectedChatId}
          hasActiveScope={Boolean(selectedProjectId)}
          currentUserId={user?.id ?? null}
          onResetRequest={() => setIsResetConfirmOpen(true)}
          onLeadStatusChanged={() => void loadChats()}
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
              onLeadStatusChanged={() => void loadChats()}
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

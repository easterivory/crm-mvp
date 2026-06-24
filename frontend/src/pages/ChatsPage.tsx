import {
  AlertCircle,
  ArrowLeft,
  Bot,
  CheckCheck,
  Download,
  FileText,
  Film,
  Image as ImageIcon,
  Languages,
  LoaderCircle,
  Mic,
  MessageSquareText,
  Music,
  Paperclip,
  Plus,
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
  translated_text: string | null
  original_text: string | null
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

type SnippetEditorDraft = {
  snippet: ProjectSnippet
  text: string
}

type ProjectTranslationConfig = {
  id: string
  operator_lang: string
  default_client_lang: string
  is_translation_enabled: boolean
}

type TranslationPreview = {
  original_text: string
  translated_text: string
  source_lang: string
  target_lang: string
}

type PendingTranslationApproval = {
  originalText: string
  approvedText: string
  sourceLang: string
  targetLang: string
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

const languageOptions = [
  { value: 'en', label: 'Английский', shortLabel: 'EN' },
  { value: 'es', label: 'Испанский', shortLabel: 'ES' },
  { value: 'pt', label: 'Португальский', shortLabel: 'PT' },
  { value: 'ar', label: 'Арабский', shortLabel: 'AR' },
  { value: 'ru', label: 'Русский', shortLabel: 'RU' },
  { value: 'fr', label: 'Французский', shortLabel: 'FR' },
  { value: 'de', label: 'Немецкий', shortLabel: 'DE' },
  { value: 'it', label: 'Итальянский', shortLabel: 'IT' },
  { value: 'tr', label: 'Турецкий', shortLabel: 'TR' },
  { value: 'hi', label: 'Хинди', shortLabel: 'HI' },
] as const

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

function normalizeLanguageCode(value: string | null | undefined) {
  const normalized = value?.trim().replace('_', '-').toLowerCase()
  return normalized || null
}

function languageShortLabel(value: string | null | undefined) {
  const normalized = normalizeLanguageCode(value)
  if (!normalized) {
    return 'EN'
  }
  return languageOptions.find((item) => item.value === normalized)?.shortLabel
    ?? normalized.toUpperCase()
}

function languageName(value: string | null | undefined) {
  const normalized = normalizeLanguageCode(value)
  if (!normalized) {
    return 'Английский'
  }
  return languageOptions.find((item) => item.value === normalized)?.label
    ?? normalized.toUpperCase()
}

function hasText(value: string | null | undefined) {
  return Boolean(value?.trim())
}

function normalizeTranslationForChat(value: string) {
  return value.replace(/[¿¡]/g, '').trim()
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
    description: 'Видео будет приведено к формату Telegram-кружка',
    accept: 'video/*',
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

function getMediaQueryMatches(query: string) {
  if (typeof window === 'undefined') {
    return false
  }
  return window.matchMedia(query).matches
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => getMediaQueryMatches(query))

  useEffect(() => {
    const media = window.matchMedia(query)
    const handleChange = () => setMatches(media.matches)

    handleChange()
    media.addEventListener('change', handleChange)
    return () => media.removeEventListener('change', handleChange)
  }, [query])

  return matches
}

export default function ChatsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const user = useAuthStore((state) => state.user)
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const notify = useNotificationStore((state) => state.notify)
  const isDesktopChatLayout = useMediaQuery('(min-width: 768px)')

  const [chats, setChats] = useState<Chat[]>([])
  const [bots, setBots] = useState<BotRecord[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [projectTranslation, setProjectTranslation] = useState<ProjectTranslationConfig | null>(null)
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
  const [isPreparingTranslation, setIsPreparingTranslation] = useState(false)
  const [isAutoTranslateEnabled, setIsAutoTranslateEnabled] = useState(true)
  const [pendingTranslation, setPendingTranslation] =
    useState<PendingTranslationApproval | null>(null)
  const [translatingMessageId, setTranslatingMessageId] = useState<string | null>(null)
  const [isUpdatingChatLanguage, setIsUpdatingChatLanguage] = useState(false)
  const [attachment, setAttachment] = useState<ChatAttachmentDraft | null>(null)
  const [attachmentMode, setAttachmentMode] = useState<OutgoingMediaType>('document')
  const [isAttachmentMenuOpen, setIsAttachmentMenuOpen] = useState(false)
  const [attachmentPreviewUrl, setAttachmentPreviewUrl] = useState<string | null>(null)
  const [isDraggingAttachment, setIsDraggingAttachment] = useState(false)
  const [isSnippetsOpen, setIsSnippetsOpen] = useState(false)
  const [snippetSearch, setSnippetSearch] = useState('')
  const [snippetEditor, setSnippetEditor] = useState<SnippetEditorDraft | null>(null)
  const [isSnippetCreateOpen, setIsSnippetCreateOpen] = useState(false)
  const [newSnippetName, setNewSnippetName] = useState('')
  const [newSnippetContent, setNewSnippetContent] = useState('')
  const [isCreatingSnippet, setIsCreatingSnippet] = useState(false)
  const [openingMediaId, setOpeningMediaId] = useState<string | null>(null)
  const [isResetConfirmOpen, setIsResetConfirmOpen] = useState(false)
  const [isResettingChat, setIsResettingChat] = useState(false)
  const [isBlockConfirmOpen, setIsBlockConfirmOpen] = useState(false)
  const [isUpdatingChatBlock, setIsUpdatingChatBlock] = useState(false)
  const [isLeadOpen, setIsLeadOpen] = useState(false)
  const [alternateMessageTextIds, setAlternateMessageTextIds] = useState<Set<string>>(
    () => new Set(),
  )
  const messagesScrollRef = useRef<HTMLDivElement | null>(null)
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

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    window.requestAnimationFrame(() => {
      const container = messagesScrollRef.current
      if (!container) {
        return
      }
      container.scrollTo({
        top: container.scrollHeight,
        behavior,
      })
    })
  }, [])

  const handleComposerFocus = useCallback(() => {
    scrollMessagesToBottom()
    window.setTimeout(() => scrollMessagesToBottom(), 250)
  }, [scrollMessagesToBottom])

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  )
  const effectiveClientLang = normalizeLanguageCode(
    selectedChat?.client_lang ?? projectTranslation?.default_client_lang ?? 'en',
  ) ?? 'en'
  const clientLangLabel = languageShortLabel(effectiveClientLang)
  const operatorLangLabel = languageShortLabel(projectTranslation?.operator_lang ?? 'ru')
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
  const canManageSnippets = user?.role_name === 'admin' || user?.role_name === 'super_admin'
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
    setIsLeadOpen(false)
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
      const hasActiveSearch = Boolean(debouncedChatFilters.q.trim())
      const hasAssignmentFilter = Boolean(
        debouncedChatFilters.assignedUserId || debouncedChatFilters.unassigned,
      )
      const selectedChatIsOutsideFilter = Boolean(
        (hasActiveSearch || hasAssignmentFilter)
        && selectedChatIdRef.current
        && !data.items.some((chat) => chat.id === selectedChatIdRef.current),
      )
      setChats((current) => {
        const currentSelectedChatId = selectedChatIdRef.current
        const selected = currentSelectedChatId
          ? current.find((chat) => chat.id === currentSelectedChatId)
          : null
        if (
          selected
          && !hasActiveSearch
          && !hasAssignmentFilter
          && !data.items.some((chat) => chat.id === selected.id)
        ) {
          return [selected, ...data.items]
        }
        return data.items
      })
      setTotal(data.total)
      if (selectedChatIsOutsideFilter) {
        selectedChatIdRef.current = null
        setSelectedChatId(null)
        setMessages([])
        setAuditLogs([])
        syncChatSearchParams(debouncedChatFilters, null)
      }
      if (!selectedChatIdRef.current && isDesktopChatLayout) {
        const nextChatId = data.items[0]?.id ?? null
        if (nextChatId) {
          selectedChatIdRef.current = nextChatId
          setSelectedChatId(nextChatId)
          syncChatSearchParams(debouncedChatFilters, nextChatId)
        }
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
    isDesktopChatLayout,
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

  const loadProjectTranslation = useCallback(async () => {
    if (!selectedProjectId) {
      setProjectTranslation(null)
      setIsAutoTranslateEnabled(true)
      return
    }

    try {
      const { data } = await api.get<ProjectTranslationConfig>(`/projects/${selectedProjectId}`)
      setProjectTranslation(data)
      setIsAutoTranslateEnabled(data.is_translation_enabled)
    } catch {
      setProjectTranslation(null)
      setIsAutoTranslateEnabled(true)
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
    void loadProjectTranslation()
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
  }, [loadBots, loadChats, loadFilterOptions, loadFilterPresets, loadProjectTranslation, loadSnippets])

  useEffect(() => {
    if (!isDesktopChatLayout || selectedChatId || chats.length === 0) {
      return
    }

    const nextChatId = chats[0]?.id ?? null
    if (!nextChatId) {
      return
    }

    selectedChatIdRef.current = nextChatId
    setSelectedChatId(nextChatId)
    syncChatSearchParams(chatFilters, nextChatId)
  }, [chatFilters, chats, isDesktopChatLayout, selectedChatId, syncChatSearchParams])

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
      setIsLeadOpen(false)
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
    setSnippetEditor(null)
    setPendingTranslation(null)
    setAlternateMessageTextIds(new Set<string>())
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
    scrollMessagesToBottom()
  }, [scrollMessagesToBottom, timelineItems])

  useEffect(() => {
    if (!selectedChatId) {
      return undefined
    }

    const handleViewportChange = () => {
      const activeElement = document.activeElement
      if (
        activeElement instanceof HTMLTextAreaElement &&
        activeElement.dataset.chatComposer === 'true'
      ) {
        scrollMessagesToBottom()
      }
    }

    const viewport = window.visualViewport
    window.addEventListener('resize', handleViewportChange)
    viewport?.addEventListener('resize', handleViewportChange)
    viewport?.addEventListener('scroll', handleViewportChange)

    return () => {
      window.removeEventListener('resize', handleViewportChange)
      viewport?.removeEventListener('resize', handleViewportChange)
      viewport?.removeEventListener('scroll', handleViewportChange)
    }
  }, [scrollMessagesToBottom, selectedChatId])

  useEffect(() => {
    if (!highlightedMessageId) {
      return undefined
    }
    const frame = window.requestAnimationFrame(() => {
      const container = messagesScrollRef.current
      const target = document.getElementById(`message-${highlightedMessageId}`)
      if (!container || !target) {
        return
      }
      const containerRect = container.getBoundingClientRect()
      const targetRect = target.getBoundingClientRect()
      const top =
        container.scrollTop +
        targetRect.top -
        containerRect.top -
        container.clientHeight / 2 +
        targetRect.height / 2
      container.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [highlightedMessageId, messages])

  const prepareTranslationApproval = async (text: string) => {
    if (!selectedChatId || isPreparingTranslation) {
      return false
    }

    setIsPreparingTranslation(true)
    try {
      const { data } = await api.post<TranslationPreview>(
        `/chats/${selectedChatId}/messages/translate-preview`,
        { text },
        {
          params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
        },
      )
      setPendingTranslation({
        originalText: data.original_text,
        approvedText: normalizeTranslationForChat(data.translated_text),
        sourceLang: data.source_lang,
        targetLang: data.target_lang,
      })
      return true
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
      return false
    } finally {
      setIsPreparingTranslation(false)
    }
  }

  const sendMessage = async (options: {
    autoTranslate?: boolean
    originalText?: string
    skipTranslationApproval?: boolean
    textOverride?: string
  } = {}) => {
    const text = (options.textOverride ?? draft).trim()
    if (!selectedChatId || (!text && !attachment) || isSending || isPreparingTranslation) {
      return false
    }

    const shouldPrepareTranslation =
      Boolean(text)
      && isAutoTranslateEnabled
      && !options.skipTranslationApproval
      && projectTranslation?.is_translation_enabled !== false

    if (shouldPrepareTranslation) {
      return prepareTranslationApproval(text)
    }

    setIsSending(true)

    try {
      const params = {
        ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
        auto_translate: options.autoTranslate ?? isAutoTranslateEnabled,
      }
      const originalText = options.originalText?.trim()
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
              if (originalText) {
                formData.append('original_text', originalText)
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
              ...(originalText ? { original_text: originalText } : {}),
            },
            { params },
          )
      setMessages((current) => sortMessagesByDate([...current, data]))
      setDraft('')
      clearAttachment()
      setPendingTranslation(null)
      await loadChats()
      return true
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
      return false
    } finally {
      setIsSending(false)
    }
  }

  const openSnippetEditor = (snippet: ProjectSnippet) => {
    if (!selectedChatId || isSending || isPreparingTranslation) {
      return
    }
    if (attachment) {
      notify({
        tone: 'error',
        message: 'Сначала отправьте или уберите вложение, затем выберите заготовку.',
      })
      return
    }

    setSnippetEditor({
      snippet,
      text: snippet.content ?? '',
    })
    setIsSnippetsOpen(false)
  }

  const sendSnippet = async (snippet: ProjectSnippet, text: string | null) => {
    if (!selectedChatId || isSending) {
      return false
    }

    setIsSending(true)
    try {
      const params = {
        ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
        auto_translate: isAutoTranslateEnabled,
      }
      const payload: { snippet_id: string; text?: string } = { snippet_id: snippet.id }
      if (text !== null) {
        payload.text = text
      }
      const { data } = await api.post<Message>(
        `/chats/${selectedChatId}/messages`,
        payload,
        { params },
      )
      setMessages((current) => sortMessagesByDate([...current, data]))
      setSnippetEditor(null)
      await loadChats()
      return true
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
      return false
    } finally {
      setIsSending(false)
    }
  }

  const handleSendSnippet = async () => {
    if (!snippetEditor) {
      return
    }

    const { snippet } = snippetEditor
    const text = snippetEditor.text.trim()
    if (snippet.type === 'text' && !text) {
      notify({ tone: 'error', message: 'Текст заготовки не может быть пустым.' })
      return
    }

    if (
      snippet.type === 'text'
      && isAutoTranslateEnabled
      && projectTranslation?.is_translation_enabled !== false
    ) {
      const translationPrepared = await prepareTranslationApproval(text)
      if (translationPrepared) {
        setDraft(text)
        setSnippetEditor(null)
      }
      return
    }

    await sendSnippet(
      snippet,
      snippet.type === 'video_note' ? null : text,
    )
  }

  const openSnippetCreate = () => {
    setNewSnippetName('')
    setNewSnippetContent(draft)
    setIsSnippetCreateOpen(true)
  }

  const handleCreateSnippet = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedProjectId || isCreatingSnippet) {
      return
    }

    const name = newSnippetName.trim()
    const content = newSnippetContent.trim()
    if (!name || !content) {
      notify({ tone: 'error', message: 'Укажите название и текст заготовки.' })
      return
    }

    setIsCreatingSnippet(true)
    try {
      const { data } = await api.post<ProjectSnippet>(
        `/projects/${selectedProjectId}/snippets`,
        {
          name,
          type: 'text',
          content,
          channel: 'telegram',
        },
      )
      setSnippets((current) => [data, ...current.filter((snippet) => snippet.id !== data.id)])
      setIsSnippetCreateOpen(false)
      setIsSnippetsOpen(true)
      notify({ tone: 'success', message: 'Заготовка добавлена.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsCreatingSnippet(false)
    }
  }

  const handleTranslateMessage = async (message: Message) => {
    const isOutgoing = message.sender_type === 'manager' || message.sender_type === 'bot'
    const hasSavedAlternative = isOutgoing
      ? hasText(message.original_text)
      : hasText(message.translated_text)

    if (hasSavedAlternative) {
      setAlternateMessageTextIds((current) => {
        const next = new Set(current)
        if (next.has(message.id)) {
          next.delete(message.id)
        } else {
          next.add(message.id)
        }
        return next
      })
      return
    }

    if (!selectedChatId || translatingMessageId || isOutgoing) {
      return
    }

    setTranslatingMessageId(message.id)
    try {
      const { data } = await api.post<Message>(
        `/chats/${selectedChatId}/messages/${message.id}/translate`,
        null,
        {
          params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
        },
      )
      setMessages((current) =>
        sortMessagesByDate(current.map((item) => (item.id === data.id ? data : item))),
      )
      setAlternateMessageTextIds((current) => {
        const next = new Set(current)
        next.add(data.id)
        return next
      })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setTranslatingMessageId(null)
    }
  }

  const handleClientLanguageChange = async (clientLang: string) => {
    if (!selectedChat || !selectedProjectId || isUpdatingChatLanguage) {
      return
    }

    const normalizedLang = normalizeLanguageCode(clientLang)
    setIsUpdatingChatLanguage(true)
    try {
      const { data } = await api.patch<Chat>(
        `/chats/${selectedChat.id}/language`,
        { client_lang: normalizedLang },
        { params: { project_id: selectedProjectId } },
      )
      setChats((current) =>
        current.map((chat) => (chat.id === data.id ? { ...chat, ...data } : chat)),
      )
      notify({
        tone: 'success',
        message: `Язык клиента: ${languageName(data.client_lang)}.`,
      })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsUpdatingChatLanguage(false)
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

  const handleSetChatBlocked = async (isBlocked: boolean) => {
    if (!selectedChatId || !selectedProjectId || isUpdatingChatBlock) {
      return
    }
    setIsUpdatingChatBlock(true)
    try {
      const { data } = await api.post<Chat>(
        `/chats/${selectedChatId}/${isBlocked ? 'block' : 'unblock'}`,
        null,
        { params: { project_id: selectedProjectId } },
      )
      setChats((current) => current.map((chat) => (chat.id === data.id ? { ...chat, ...data } : chat)))
      setIsBlockConfirmOpen(false)
      notify({
        tone: 'success',
        message: isBlocked ? 'Диалог заблокирован в CRM.' : 'Диалог разблокирован.',
      })
      await loadChats()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsUpdatingChatBlock(false)
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

  const handleApproveTranslation = async () => {
    if (!pendingTranslation || isSending) {
      return
    }
    const approvedText = pendingTranslation.approvedText.trim()
    if (!approvedText) {
      notify({ tone: 'error', message: 'Перевод не может быть пустым.' })
      return
    }
    await sendMessage({
      autoTranslate: false,
      originalText: pendingTranslation.originalText,
      skipTranslationApproval: true,
      textOverride: approvedText,
    })
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
    <section className="relative grid h-full min-h-0 grid-cols-1 gap-0 overflow-hidden text-gray-200 md:gap-4 md:grid-cols-[20rem_minmax(0,1fr)] lg:grid-cols-[minmax(280px,25%)_minmax(0,50%)_minmax(280px,25%)]">
      <div
        className={`h-full min-h-0 overflow-hidden ${
          selectedChat ? 'hidden md:block' : ''
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
        className={`${selectedChat ? 'flex' : 'hidden md:flex'} relative h-full min-h-0 min-w-0 flex-col overflow-hidden bg-surface/90 shadow-card md:rounded-xl md:border md:border-white/5`}
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
        <header className="flex min-h-14 shrink-0 items-center justify-between gap-2 border-b border-white/5 px-2.5 sm:min-h-[96px] sm:gap-4 sm:px-5">
          {selectedChat ? (
            <>
              <div className="flex min-w-0 flex-1 items-center gap-3">
                <button
                  type="button"
                  onClick={handleClearSelectedChat}
                  className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 md:hidden"
                  title="К списку чатов"
                  aria-label="К списку чатов"
                >
                  <ArrowLeft size={16} />
                </button>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="truncate text-base font-semibold text-white">
                      {getChatTitle(selectedChat)}
                    </h2>
                    {selectedChat.is_red ? <AlertCircle size={16} className="text-red-300 drop-shadow-[0_0_10px_rgba(248,113,113,0.6)]" /> : null}
                    {selectedChat.is_blocked ? (
                      <span className="rounded-full border border-red-300/25 bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-100">
                        Заблокирован
                      </span>
                    ) : null}
                  </div>
                  <p className="hidden truncate text-sm text-gray-500 sm:block">
                    {getBotLabel(selectedChat)} · Telegram ID {selectedChat.external_chat_id}
                  </p>
                  <p className="mt-1 hidden flex-wrap items-center gap-1.5 text-xs text-gray-500 sm:flex">
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
              <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
                <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-2 py-2 text-xs text-gray-400 sm:px-3">
                  <Languages size={15} className="text-accent-200" />
                  <span className="sr-only">Язык клиента</span>
                  <select
                    value={effectiveClientLang}
                    onChange={(event) => void handleClientLanguageChange(event.target.value)}
                    disabled={isUpdatingChatLanguage}
                    className="bg-transparent text-xs font-semibold uppercase text-gray-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
                    title="Язык клиента"
                  >
                    {languageOptions.map((language) => (
                      <option key={language.value} value={language.value} className="bg-[#0B0F19] text-gray-100">
                        {language.shortLabel}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => setIsLeadOpen(true)}
                  className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-2 text-sm text-gray-200 transition hover:border-accent-300/50 sm:px-3 lg:hidden"
                  aria-label="Открыть информацию о лиде"
                >
                  <UserRound size={15} />
                  <span className="hidden min-[360px]:inline">Инфо</span>
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

        <div
          ref={messagesScrollRef}
          className="touch-scroll min-h-0 flex-1 overflow-y-auto bg-background/45 px-3 py-4 md:px-5"
        >
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
                const translatedText = message.translated_text?.trim() || null
                const originalText = message.original_text?.trim() || null
                const hasTranslatableText = hasText(message.body) || hasText(message.caption)
                const isAlternateTextVisible = alternateMessageTextIds.has(message.id)
                const canUseMessageTextToggle = isOutgoing
                  ? Boolean(originalText)
                  : hasTranslatableText
                const isTranslationLoading = translatingMessageId === message.id
                const visibleBody =
                  isAlternateTextVisible && isOutgoing && originalText
                    ? originalText
                    : isAlternateTextVisible && !isOutgoing && translatedText
                      ? translatedText
                      : message.body
                const visibleCaption =
                  isAlternateTextVisible && isOutgoing && originalText
                    ? originalText
                    : isAlternateTextVisible && !isOutgoing && translatedText
                      ? translatedText
                      : message.caption
                const textToggleLabel = isAlternateTextVisible
                  ? (isOutgoing ? 'Перевод' : 'Оригинал')
                  : isOutgoing
                    ? 'Исходник'
                    : translatedText
                      ? 'Перевод'
                      : 'Перевести'
                const textToggleTitle = isAlternateTextVisible
                  ? 'Показать исходный текст сообщения'
                  : isOutgoing
                    ? 'Показать текст до перевода'
                    : 'Показать перевод вместо оригинала'

                return (
                  <div
                    id={`message-${message.id}`}
                    key={message.id}
                    className={`flex ${isOutgoing ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`flex max-w-[86%] flex-col md:max-w-[72%] ${isOutgoing ? 'items-end' : 'items-start'}`}
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
                            {visibleBody || ''}
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
                            {visibleCaption ? (
                              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                                {visibleCaption}
                              </p>
                            ) : null}
                          </div>
                        )}
                        {canUseMessageTextToggle ? (
                          <div className="mt-2 flex justify-end border-t border-white/10 pt-1.5">
                            <button
                              type="button"
                              onClick={() => void handleTranslateMessage(message)}
                              disabled={isTranslationLoading}
                              className="inline-flex h-7 items-center gap-1.5 rounded-full border border-white/10 bg-black/10 px-2 text-[11px] font-medium text-white/75 transition hover:border-accent-300/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                              title={textToggleTitle}
                            >
                              {isTranslationLoading ? (
                                <LoaderCircle size={12} className="animate-spin" />
                              ) : (
                                <Languages size={12} />
                              )}
                              <span>{textToggleLabel}</span>
                            </button>
                          </div>
                        ) : null}
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

        <form
          className="relative z-10 shrink-0 border-t border-white/5 bg-surface/95 p-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:p-4"
          onSubmit={handleSend}
        >
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
          <div className="mb-2 flex justify-end">
            <label
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-sky-300/20 bg-sky-300/10 px-3 text-xs font-medium text-sky-50 transition hover:border-sky-300/40"
              title={`Подготовить перевод с ${operatorLangLabel} на ${clientLangLabel} перед отправкой`}
            >
              <input
                type="checkbox"
                checked={isAutoTranslateEnabled}
                onChange={(event) => setIsAutoTranslateEnabled(event.target.checked)}
                disabled={!selectedChat || isSending || isPreparingTranslation}
                className="h-4 w-4 accent-sky-300 disabled:cursor-not-allowed"
              />
              <Languages size={14} />
              <span className="whitespace-nowrap">Перевод на {clientLangLabel}</span>
            </label>
          </div>
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
                disabled={!selectedChat || isSending || isPreparingTranslation}
                className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                title="Прикрепить файл"
              >
                <Paperclip size={18} />
              </button>
              {isAttachmentMenuOpen ? (
                <div className="absolute bottom-full left-0 z-30 mb-2 w-[min(18rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-white/10 bg-[#0B0F19]/98 p-2 shadow-card backdrop-blur-xl">
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
                disabled={!selectedChat || isSending || isPreparingTranslation || isSnippetsLoading}
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
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-white">Заготовки</p>
                    {canManageSnippets ? (
                      <button
                        type="button"
                        onClick={openSnippetCreate}
                        className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-accent-300/30 bg-accent-300/10 px-2.5 text-xs font-semibold text-accent-100 transition hover:border-accent-300/60 hover:bg-accent-300/15"
                        title="Добавить заготовку"
                      >
                        <Plus size={15} />
                        Новая
                      </button>
                    ) : null}
                  </div>
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
                              onClick={() => openSnippetEditor(snippet)}
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
              onFocus={handleComposerFocus}
              data-chat-composer="true"
              enterKeyHint="send"
              className="touch-scroll max-h-32 min-h-10 flex-1 resize-none overflow-y-auto rounded-lg border-0 bg-transparent px-2 py-2 text-sm leading-6 text-gray-100 outline-none placeholder:text-gray-600 disabled:text-gray-500"
              placeholder={attachment ? 'Добавить подпись к вложению' : 'Ответить в Telegram'}
              disabled={!selectedChat || isSending || isPreparingTranslation}
              rows={1}
            />
            <button
              type="submit"
              title="Отправить сообщение"
              disabled={!selectedChat || (!draft.trim() && !attachment) || isSending || isPreparingTranslation}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSending || isPreparingTranslation ? <LoaderCircle size={18} className="animate-spin" /> : <Send size={18} />}
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

      <div className="hidden h-full min-h-0 lg:block">
        <LeadSidebar
          activeBotId={selectedBotIds.length === 1 ? selectedBotIds[0] : null}
          activeBotName={botScopeLabel}
          activeChatId={selectedChatId}
          hasActiveScope={Boolean(selectedProjectId)}
          isChatBlocked={Boolean(selectedChat?.is_blocked)}
          isUpdatingChatBlock={isUpdatingChatBlock}
          currentUserId={user?.id ?? null}
          currentUserRole={user?.role_name ?? null}
          onSetBlocked={user?.role_name === 'manager'
            ? undefined
            : (isBlocked) => {
                if (isBlocked) {
                  setIsBlockConfirmOpen(true)
                  return
                }
                void handleSetChatBlocked(false)
              }}
          onResetRequest={user?.role_name === 'manager' ? undefined : () => setIsResetConfirmOpen(true)}
          onLeadStatusChanged={() => void loadChats()}
        />
      </div>

      {snippetEditor ? (
        <Modal
          title="Перед отправкой"
          description={`Заготовка «${snippetEditor.snippet.name}» будет изменена только для этого диалога.`}
          maxWidthClassName="max-w-lg"
          onClose={() => {
            if (!isSending && !isPreparingTranslation) {
              setSnippetEditor(null)
            }
          }}
        >
          <form className="space-y-4" onSubmit={(event) => {
            event.preventDefault()
            void handleSendSnippet()
          }}>
            {snippetEditor.snippet.type === 'video_note' ? (
              <div className="rounded-xl border border-white/10 bg-white/[0.035] px-4 py-3 text-sm leading-6 text-gray-400">
                Кружок отправится без подписи. Если исходный ролик не квадратный, сервер приведёт его к формату Telegram video note.
              </div>
            ) : (
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-gray-200">
                  {snippetEditor.snippet.type === 'text' ? 'Текст сообщения' : 'Подпись к вложению'}
                </span>
                <textarea
                  value={snippetEditor.text}
                  onChange={(event) => setSnippetEditor((current) => (
                    current ? { ...current, text: event.target.value } : current
                  ))}
                  rows={7}
                  autoFocus
                  className="touch-scroll w-full resize-y rounded-xl border border-accent-300/25 bg-background/80 px-3 py-2.5 text-base leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                  placeholder="Текст к отправке"
                  disabled={isSending || isPreparingTranslation}
                />
              </label>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setSnippetEditor(null)}
                disabled={isSending || isPreparingTranslation}
                className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 px-4 text-sm font-medium text-gray-200 transition hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={
                  isSending
                  || isPreparingTranslation
                  || (snippetEditor.snippet.type === 'text' && !snippetEditor.text.trim())
                }
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSending || isPreparingTranslation ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
                {snippetEditor.snippet.type === 'text' && isAutoTranslateEnabled && projectTranslation?.is_translation_enabled !== false
                  ? 'Проверить перевод'
                  : 'Отправить'}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {isSnippetCreateOpen ? (
        <Modal
          title="Новая заготовка"
          description="Её смогут использовать операторы этого проекта. Редактировать и добавлять заготовки могут только администраторы."
          maxWidthClassName="max-w-lg"
          onClose={() => {
            if (!isCreatingSnippet) {
              setIsSnippetCreateOpen(false)
            }
          }}
        >
          <form className="space-y-4" onSubmit={(event) => void handleCreateSnippet(event)}>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-gray-200">Название</span>
              <input
                value={newSnippetName}
                onChange={(event) => setNewSnippetName(event.target.value)}
                autoFocus
                maxLength={255}
                placeholder="Например, Приветствие LATAM"
                className="h-11 w-full rounded-xl border border-white/10 bg-background/80 px-3 text-base text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                disabled={isCreatingSnippet}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-gray-200">Текст</span>
              <textarea
                value={newSnippetContent}
                onChange={(event) => setNewSnippetContent(event.target.value)}
                rows={8}
                placeholder="Текст быстрого ответа"
                className="touch-scroll w-full resize-y rounded-xl border border-white/10 bg-background/80 px-3 py-2.5 text-base leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                disabled={isCreatingSnippet}
              />
            </label>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setIsSnippetCreateOpen(false)}
                disabled={isCreatingSnippet}
                className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 px-4 text-sm font-medium text-gray-200 transition hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isCreatingSnippet || !newSnippetName.trim() || !newSnippetContent.trim()}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCreatingSnippet ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Добавить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {pendingTranslation ? (
        <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/60 p-3 backdrop-blur-sm md:items-center">
          <div className="max-h-[calc(100dvh-24px)] w-[calc(100%-24px)] max-w-2xl overflow-hidden rounded-2xl border border-white/10 bg-[#0d1222] shadow-2xl md:w-full">
            <div className="flex items-start justify-between gap-4 border-b border-white/10 px-4 py-3">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-white">Проверка перевода</h3>
                <p className="mt-1 text-xs text-gray-500">
                  {languageShortLabel(pendingTranslation.sourceLang)} → {languageShortLabel(pendingTranslation.targetLang)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPendingTranslation(null)}
                disabled={isSending}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
                aria-label="Закрыть проверку перевода"
              >
                <X size={16} />
              </button>
            </div>
            <div className="touch-scroll max-h-[calc(100dvh-11rem)] space-y-4 overflow-y-auto p-4">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Исходный текст
                </span>
                <textarea
                  value={pendingTranslation.originalText}
                  readOnly
                  rows={4}
                  className="touch-scroll w-full resize-none rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-base leading-6 text-gray-300 outline-none"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Текст к отправке
                </span>
                <textarea
                  value={pendingTranslation.approvedText}
                  onChange={(event) =>
                    setPendingTranslation((current) =>
                      current ? { ...current, approvedText: event.target.value } : current,
                    )
                  }
                  rows={6}
                  autoFocus
                  className="touch-scroll w-full resize-none rounded-xl border border-accent-300/25 bg-background/80 px-3 py-2 text-base leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                />
              </label>
            </div>
            <div className="flex flex-col-reverse gap-2 border-t border-white/10 p-4 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setPendingTranslation(null)}
                disabled={isSending}
                className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 px-4 text-sm font-medium text-gray-200 transition hover:border-white/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Вернуться к тексту
              </button>
              <button
                type="button"
                onClick={() => void handleApproveTranslation()}
                disabled={isSending || !pendingTranslation.approvedText.trim()}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSending ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
                Отправить
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {isLeadOpen ? (
        <>
          <button
            type="button"
            aria-label="Закрыть информацию о лиде"
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
            onClick={() => setIsLeadOpen(false)}
          />
          <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-sm transform flex-col bg-[#0d1222] shadow-2xl transition-transform duration-300 lg:hidden">
            <div className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-white/10 px-4">
              <div className="flex min-w-0 items-center gap-2 text-sm font-semibold text-white">
                <UserRound size={16} className="text-accent-200" />
                <span className="truncate">Инфо лида</span>
              </div>
              <button
                type="button"
                onClick={() => setIsLeadOpen(false)}
                aria-label="Закрыть"
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>
            <div className="min-h-0 flex-1 p-3">
            <LeadSidebar
              activeBotId={selectedBotIds.length === 1 ? selectedBotIds[0] : null}
              activeBotName={botScopeLabel}
              activeChatId={selectedChatId}
              hasActiveScope={Boolean(selectedProjectId)}
              isChatBlocked={Boolean(selectedChat?.is_blocked)}
              isUpdatingChatBlock={isUpdatingChatBlock}
              currentUserId={user?.id ?? null}
              currentUserRole={user?.role_name ?? null}
              onSetBlocked={user?.role_name === 'manager'
                ? undefined
                : (isBlocked) => {
                    if (isBlocked) {
                      setIsBlockConfirmOpen(true)
                      return
                    }
                    void handleSetChatBlocked(false)
                  }}
              onResetRequest={user?.role_name === 'manager' ? undefined : () => setIsResetConfirmOpen(true)}
              onLeadStatusChanged={() => void loadChats()}
            />
          </div>
          </aside>
        </>
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

      {isBlockConfirmOpen ? (
        <ConfirmDialog
          title="Заблокировать клиента в боте?"
          description="Новые сообщения и нажатия на старые кнопки останутся без реакции сценария. Разблокировать можно в карточке лида."
          confirmLabel="Заблокировать"
          tone="danger"
          isLoading={isUpdatingChatBlock}
          onCancel={() => setIsBlockConfirmOpen(false)}
          onConfirm={() => void handleSetChatBlocked(true)}
        />
      ) : null}
    </section>
  )
}

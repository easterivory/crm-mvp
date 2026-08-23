import {
  AlertCircle,
  ArrowLeft,
  Ban,
  Bot,
  CheckCheck,
  Clock3,
  Eye,
  FileText,
  Film,
  Image as ImageIcon,
  Languages,
  LoaderCircle,
  Mic,
  MessageSquareText,
  MousePointerClick,
  Music,
  Paperclip,
  Pencil,
  Plus,
  Reply,
  Search,
  Send,
  Star,
  Trash2,
  UserRound,
  Video,
  Phone,
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
  useLayoutEffect,
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
  countActiveChatFilters,
  EMPTY_CHAT_FILTERS,
  type ChatDatePreset,
  type ChatFiltersState,
  type ChatSort,
  type ChatTagMode,
  type ChatWorkspaceView,
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

type ChatWorkspaceCounts = Record<ChatWorkspaceView, number> & {
  unanswered: number
  hide_assigned_chats_from_all: boolean
  chat_lease_minutes: number
  project_format: 'submission' | 'gambling'
  push_unread_threshold: number
}

const EMPTY_WORKSPACE_COUNTS: ChatWorkspaceCounts = {
  unread: 0,
  mine: 0,
  all: 0,
  favorites: 0,
  unanswered: 0,
  hide_assigned_chats_from_all: false,
  chat_lease_minutes: 30,
  project_format: 'submission',
  push_unread_threshold: 1,
}

type FunnelStepOptionRecord = {
  id: string
  key: string
  title: string
  funnel_id: string
  funnel_name: string
  version_number: number
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
  reply_to_message_id: string | null
  reply_to: {
    id: string
    sender_type: 'user' | 'manager' | 'bot' | 'system'
    message_type: string
    body: string | null
    caption: string | null
    file_name: string | null
    deleted_at: string | null
  } | null
  edited_at: string | null
  deleted_at: string | null
  buttons?: string[]
  transport_source?: string
  is_external_account_message?: boolean
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

type MediaPreview = {
  message: Message
  url: string
}

type ProjectSnippet = {
  id: string
  project_id: string
  channel: string
  name: string
  type: 'text' | OutgoingMediaType
  content: string | null
  file_id: string | null
  file_name: string | null
  mime_type: string | null
  file_size: number | null
  created_at: string
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

type ScheduledMessage = {
  id: string
  scheduled_at: string
  text: string | null
  media_type: 'text' | OutgoingMediaType
  file_name: string | null
  status: 'pending' | 'running' | 'sent' | 'failed' | 'cancelled'
  last_error: string | null
  created_by_user_id: string
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
  contact: 'Контакт',
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

function getErrorMessage(err: unknown, fallback = 'Запрос не выполнен. Попробуйте снова.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен. Проверьте backend или контейнер.'
    }
  }

  return fallback
}

function isRequestCanceled(err: unknown) {
  return axios.isCancel(err) || (axios.isAxiosError(err) && err.code === 'ERR_CANCELED')
}

function isTelegramUserBlockError(err: unknown) {
  if (!axios.isAxiosError(err)) {
    return false
  }
  const detail = err.response?.data?.detail
  return err.response?.status === 409
    && typeof detail === 'string'
    && detail.toLowerCase().includes('заблокировал бота')
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

function mergeById<T extends { id: string }>(...groups: T[][]) {
  const merged = new Map<string, T>()
  for (const group of groups) {
    for (const item of group) {
      merged.set(item.id, item)
    }
  }
  return [...merged.values()]
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

function messageSummary(message: Pick<Message, 'body' | 'caption' | 'file_name' | 'message_type'>) {
  return (
    message.body?.trim()
    || message.caption?.trim()
    || message.file_name?.trim()
    || mediaLabels[message.message_type]
    || 'Сообщение'
  )
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
  if (messageType === 'contact') {
    return Phone
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

function isWorkspaceView(value: string | null | undefined): value is ChatWorkspaceView {
  return value === 'unread' || value === 'mine' || value === 'all' || value === 'favorites'
}

function isChatSort(value: string | null): value is ChatSort {
  return value === 'latest' || value === 'priority'
}

function normalizeChatFilters(value: Partial<ChatFiltersState> | null | undefined) {
  const quickFilter = isQuickFilter(value?.quickFilter ?? null) ? value?.quickFilter ?? '' : ''
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
    isRed: value?.isRed === true && quickFilter !== 'hot',
    isHotLead: value?.isHotLead === true || (quickFilter === 'hot' && value?.isRed === true),
    quickFilter,
    workspaceView: isWorkspaceView(value?.workspaceView) ? value.workspaceView : 'all',
    sortBy: isChatSort(value?.sortBy ?? null) ? value?.sortBy ?? 'latest' : 'latest',
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
    currentStepId: params.get('current_step_id') ?? '',
    funnelState: isFunnelState(funnelState) ? funnelState : '',
    hasUnansweredIncoming: params.get('has_unanswered_incoming') === 'true',
    isRed: params.get('is_red') === 'true' && quickFilter !== 'hot',
    isHotLead: params.get('is_hot_lead') === 'true'
      || (quickFilter === 'hot' && params.get('is_red') === 'true'),
    assignedUserId: params.get('assigned_user_id') ?? '',
    unassigned: params.get('unassigned') === 'true',
    quickFilter: isQuickFilter(quickFilter) ? quickFilter : '',
    workspaceView: isWorkspaceView(params.get('view'))
      ? params.get('view') as ChatWorkspaceView
      : 'all',
    sortBy: isChatSort(params.get('sort_by'))
      ? params.get('sort_by') as ChatSort
      : 'latest',
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
  if (filters.currentStepId) params.set('current_step_id', filters.currentStepId)
  if (filters.funnelState) params.set('funnel_state', filters.funnelState)
  if (filters.hasUnansweredIncoming) params.set('has_unanswered_incoming', 'true')
  if (filters.isRed) params.set('is_red', 'true')
  if (filters.isHotLead) params.set('is_hot_lead', 'true')
  if (filters.assignedUserId) params.set('assigned_user_id', filters.assignedUserId)
  if (filters.unassigned) params.set('unassigned', 'true')
  if (filters.quickFilter) params.set('quick_filter', filters.quickFilter)
  if (filters.workspaceView !== 'all') params.set('view', filters.workspaceView)
  if (filters.sortBy !== 'latest') params.set('sort_by', filters.sortBy)
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
  const [stepOptions, setStepOptions] = useState<FilterOption[]>([])
  const [userOptions, setUserOptions] = useState<FilterOption[]>([])
  const [users, setUsers] = useState<UserOptionRecord[]>([])
  const [filterPresets, setFilterPresets] = useState<ChatFilterPreset[]>([])
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [total, setTotal] = useState(0)
  const [workspaceCounts, setWorkspaceCounts] = useState<ChatWorkspaceCounts>(
    EMPTY_WORKSPACE_COUNTS,
  )
  const [loadedChatCount, setLoadedChatCount] = useState(0)
  const [selectedChatId, setSelectedChatId] = useState<string | null>(() =>
    searchParams.get('chat_id'),
  )
  const [chatFilters, setChatFilters] = useState<ChatFiltersState>(() =>
    readChatFilters(searchParams),
  )
  const debouncedChatFilters = useDebouncedValue(chatFilters, 350)
  const [draft, setDraft] = useState('')
  const [isChatsLoading, setIsChatsLoading] = useState(true)
  const [isChatsLoadingMore, setIsChatsLoadingMore] = useState(false)
  const [isMessagesLoading, setIsMessagesLoading] = useState(false)
  const [isMessagesLoadingMore, setIsMessagesLoadingMore] = useState(false)
  const [messageTotal, setMessageTotal] = useState(0)
  const [isSnippetsLoading, setIsSnippetsLoading] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [isPreparingTranslation, setIsPreparingTranslation] = useState(false)
  const [translatedDraftOriginal, setTranslatedDraftOriginal] = useState<string | null>(null)
  const [translatingMessageId, setTranslatingMessageId] = useState<string | null>(null)
  const [isUpdatingChatLanguage, setIsUpdatingChatLanguage] = useState(false)
  const [attachment, setAttachment] = useState<ChatAttachmentDraft | null>(null)
  const [attachmentMode, setAttachmentMode] = useState<OutgoingMediaType>('document')
  const [isAttachmentMenuOpen, setIsAttachmentMenuOpen] = useState(false)
  const [attachmentPreviewUrl, setAttachmentPreviewUrl] = useState<string | null>(null)
  const [isDraggingAttachment, setIsDraggingAttachment] = useState(false)
  const [isSnippetsOpen, setIsSnippetsOpen] = useState(false)
  const [snippetSearch, setSnippetSearch] = useState('')
  const [snippetMedia, setSnippetMedia] = useState<ProjectSnippet | null>(null)
  const [isSnippetCreateOpen, setIsSnippetCreateOpen] = useState(false)
  const [newSnippetName, setNewSnippetName] = useState('')
  const [newSnippetContent, setNewSnippetContent] = useState('')
  const [newSnippetType, setNewSnippetType] = useState<ProjectSnippet['type']>('text')
  const [newSnippetFile, setNewSnippetFile] = useState<File | null>(null)
  const [isCreatingSnippet, setIsCreatingSnippet] = useState(false)
  const [snippetPendingDeletion, setSnippetPendingDeletion] = useState<ProjectSnippet | null>(null)
  const [isDeletingSnippet, setIsDeletingSnippet] = useState(false)
  const [scheduledMessages, setScheduledMessages] = useState<ScheduledMessage[]>([])
  const [isScheduleOpen, setIsScheduleOpen] = useState(false)
  const [scheduledAtLocal, setScheduledAtLocal] = useState('')
  const [isScheduling, setIsScheduling] = useState(false)
  const [cancellingScheduledMessageId, setCancellingScheduledMessageId] = useState<string | null>(null)
  const [replyingToMessage, setReplyingToMessage] = useState<Message | null>(null)
  const [editingMessage, setEditingMessage] = useState<Message | null>(null)
  const [editingMessageText, setEditingMessageText] = useState('')
  const [isEditingMessage, setIsEditingMessage] = useState(false)
  const [messagePendingDeletion, setMessagePendingDeletion] = useState<Message | null>(null)
  const [isDeletingMessage, setIsDeletingMessage] = useState(false)
  const [openingMediaId, setOpeningMediaId] = useState<string | null>(null)
  const [mediaPreview, setMediaPreview] = useState<MediaPreview | null>(null)
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
  const loadedChatCountRef = useRef(0)
  const totalChatsRef = useRef(0)
  const chatQueryKeyRef = useRef('')
  const chatsAbortRef = useRef<AbortController | null>(null)
  const messagesAbortRef = useRef<AbortController | null>(null)
  const olderMessagesAbortRef = useRef<AbortController | null>(null)
  const selectedChatAbortRef = useRef<AbortController | null>(null)
  const readRequestsRef = useRef<Set<string>>(new Set())
  const shouldAutoScrollMessagesRef = useRef(true)
  const latestLoadedMessageIdRef = useRef<string | null>(null)
  const prependScrollAnchorRef = useRef<{ messageId: string; top: number } | null>(null)
  const handledSearchHitRef = useRef<string | null>(null)

  const scrollMessagesToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const container = messagesScrollRef.current
        if (!container) {
          return
        }
        container.scrollTo({
          top: container.scrollHeight,
          behavior,
        })
        messagesEndRef.current?.scrollIntoView({ block: 'end', behavior })
      })
    })
  }, [])

  const handleComposerFocus = useCallback(() => {
    shouldAutoScrollMessagesRef.current = true
    scrollMessagesToBottom()
    window.setTimeout(() => scrollMessagesToBottom(), 250)
  }, [scrollMessagesToBottom])

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  )
  const isTelegramBlockedByUser = Boolean(selectedChat?.is_blocked_by_user)
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
  const canCreateSnippets = user?.role_name === 'manager' || user?.role_name === 'admin' || user?.role_name === 'super_admin'
  const canDeleteSnippets = user?.role_name === 'admin' || user?.role_name === 'super_admin'
  const isBuyer = user?.role_name === 'buyer'
  const highlightedMessageId = selectedChat?.search_hit_message_id ?? null
  const searchNavigationKey = selectedChatId && highlightedMessageId
    ? `${selectedChatId}:${highlightedMessageId}`
    : null
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

  const loadWorkspaceCounts = useCallback(async () => {
    if (!selectedProjectId) {
      setWorkspaceCounts(EMPTY_WORKSPACE_COUNTS)
      return
    }
    const params: Record<string, string> = { project_id: selectedProjectId }
    if (selectedBotIds.length === 1) {
      params.bot_id = selectedBotIds[0]
    } else if (selectedBotIds.length > 1) {
      params.bot_ids = selectedBotIds.join(',')
    }
    try {
      const { data } = await api.get<ChatWorkspaceCounts>('/chats/workspace-counts', {
        params,
      })
      setWorkspaceCounts(data)
    } catch (err) {
      if (!isRequestCanceled(err)) {
        notify({ tone: 'error', message: getErrorMessage(err) })
      }
    }
  }, [notify, selectedBotIds, selectedProjectId])

  const markChatAsRead = useCallback(async (chatId: string) => {
    if (!selectedProjectId) {
      return
    }

    setChats((current) => current.map((chat) => (
      chat.id === chatId && (chat.unread || !chat.is_read)
        ? { ...chat, unread: false, is_read: true }
        : chat
    )))

    if (readRequestsRef.current.has(chatId)) {
      return
    }
    readRequestsRef.current.add(chatId)

    try {
      await api.post(`/chats/${chatId}/read`, null, {
        params: { project_id: selectedProjectId },
      })
      void loadWorkspaceCounts()
    } catch (err) {
      if (!isRequestCanceled(err)) {
        notify({ tone: 'error', message: 'Не удалось отметить чат прочитанным.' })
      }
    } finally {
      readRequestsRef.current.delete(chatId)
    }
  }, [loadWorkspaceCounts, notify, selectedProjectId])

  const loadChats = useCallback(async (options: { append?: boolean } = {}) => {
    const append = options.append === true
    if (!selectedProjectId) {
      setChats([])
      setTotal(0)
      totalChatsRef.current = 0
      loadedChatCountRef.current = 0
      setLoadedChatCount(0)
      chatQueryKeyRef.current = ''
      selectedChatIdRef.current = null
      setSelectedChatId(null)
      setIsChatsLoading(false)
      setIsChatsLoadingMore(false)
      return
    }

    if (chatsAbortRef.current) {
      return
    }

    const searchQuery = debouncedChatFilters.q.trim()
    const params: Record<string, boolean | number | string> = {
      limit: CHAT_LIMIT,
      offset: append ? loadedChatCountRef.current : 0,
      project_id: selectedProjectId,
      sort_by: debouncedChatFilters.sortBy,
      timezone_offset_minutes: new Date().getTimezoneOffset(),
    }

    if (!searchQuery) {
      params.view = debouncedChatFilters.workspaceView
      if (selectedBotIds.length === 1) {
        params.bot_id = selectedBotIds[0]
      } else if (selectedBotIds.length > 1) {
        params.bot_ids = selectedBotIds.join(',')
      }
    }

    if (searchQuery) {
      params.q = searchQuery
    }
    if (!searchQuery) {
      if (debouncedChatFilters.hasUnansweredIncoming) {
        params.has_unanswered_incoming = true
      }
      if (debouncedChatFilters.isRed) {
        params.is_red = true
      }
      if (debouncedChatFilters.isHotLead) {
        params.is_hot_lead = true
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
      if (debouncedChatFilters.currentStepId) {
        params.current_step_id = debouncedChatFilters.currentStepId
      }
    }

    const queryParams = { ...params }
    delete queryParams.limit
    delete queryParams.offset
    const requestKey = JSON.stringify(queryParams)
    const isNewQuery = requestKey !== chatQueryKeyRef.current

    if (append && (isNewQuery || loadedChatCountRef.current >= totalChatsRef.current)) {
      return
    }

    if (isNewQuery) {
      chatQueryKeyRef.current = requestKey
      loadedChatCountRef.current = 0
      setLoadedChatCount(0)
      setChats([])
      params.offset = 0
    }

    const controller = new AbortController()
    chatsAbortRef.current = controller
    if (append) {
      setIsChatsLoadingMore(true)
    } else {
      setIsChatsLoading(true)
    }

    try {
      const { data } = await api.get<PaginatedResponse<Chat>>('/chats', {
        params,
        signal: controller.signal,
      })
      if (controller.signal.aborted) {
        return
      }
      const freshItems = data.items.map((chat) => (
        chat.id === selectedChatIdRef.current
          ? { ...chat, unread: false, is_read: true }
          : chat
      ))
      const hasRestrictiveFilter =
        countActiveChatFilters(debouncedChatFilters) > 0
        || selectedBotIds.length > 0
        || debouncedChatFilters.workspaceView !== 'all'
      const selectedChatIsOutsideFilter = Boolean(
        isNewQuery
        && hasRestrictiveFilter
        && selectedChatIdRef.current
        && !freshItems.some((chat) => chat.id === selectedChatIdRef.current),
      )
      if (append) {
        setChats((current) => {
          const knownIds = new Set(current.map((chat) => chat.id))
          return [...current, ...freshItems.filter((chat) => !knownIds.has(chat.id))]
        })
        loadedChatCountRef.current = Number(params.offset) + freshItems.length
      } else if (isNewQuery) {
        setChats(freshItems)
        loadedChatCountRef.current = freshItems.length
      } else {
        setChats((current) => {
          const freshIds = new Set(freshItems.map((chat) => chat.id))
          const selectedCarry = current.find((chat) => (
            chat.id === selectedChatIdRef.current && !freshIds.has(chat.id)
          ))
          const remainingLoadedChats = current.filter((chat) => (
            !freshIds.has(chat.id) && chat.id !== selectedCarry?.id
          ))
          const merged = [...freshItems, ...remainingLoadedChats].slice(0, data.total)
          return selectedCarry && !merged.some((chat) => chat.id === selectedCarry.id)
            ? [...merged, { ...selectedCarry, unread: false, is_read: true }]
            : merged
        })
        loadedChatCountRef.current = Math.max(
          loadedChatCountRef.current,
          freshItems.length,
        )
      }
      setLoadedChatCount(loadedChatCountRef.current)
      totalChatsRef.current = data.total
      setTotal(data.total)
      if (selectedChatIsOutsideFilter) {
        selectedChatIdRef.current = null
        setSelectedChatId(null)
        setMessages([])
        setAuditLogs([])
        syncChatSearchParams(debouncedChatFilters, null)
      }
      if (
        !selectedChatIdRef.current
        && isDesktopChatLayout
        && debouncedChatFilters.workspaceView !== 'unread'
      ) {
        const nextChatId = freshItems[0]?.id ?? null
        if (nextChatId) {
          selectedChatIdRef.current = nextChatId
          setSelectedChatId(nextChatId)
          syncChatSearchParams(debouncedChatFilters, nextChatId)
        }
      }
    } catch (err) {
      if (isRequestCanceled(err)) {
        return
      }
      if (isNewQuery) {
        chatQueryKeyRef.current = ''
        totalChatsRef.current = 0
        setTotal(0)
      }
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      if (chatsAbortRef.current === controller) {
        chatsAbortRef.current = null
        if (append) {
          setIsChatsLoadingMore(false)
        } else {
          setIsChatsLoading(false)
        }
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
      return
    }

    try {
      const { data } = await api.get<ProjectTranslationConfig>(`/projects/${selectedProjectId}`)
      setProjectTranslation(data)
    } catch {
      setProjectTranslation(null)
    }
  }, [selectedProjectId])

  const loadFilterOptions = useCallback(async () => {
    if (!selectedProjectId) {
      setTrackingOptions([])
      setTagOptions([])
      setStatusOptions([])
      setStepOptions([])
      setUserOptions([])
      setUsers([])
      return
    }

    try {
      const [trackingResponse, tagsResponse, statusesResponse, usersResponse, stepsResponse] = await Promise.all([
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
        api.get<FunnelStepOptionRecord[]>('/funnels/step-options', {
          params: { project_id: selectedProjectId },
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
      setStepOptions(stepsResponse.data.map((step) => ({
        id: step.id,
        label: `${step.funnel_name} v${step.version_number} · ${step.title}`,
      })))
    } catch {
      setTrackingOptions([])
      setTagOptions([])
      setStatusOptions([])
      setStepOptions([])
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

  const loadScheduledMessages = useCallback(async (chatId: string) => {
    if (!selectedProjectId) {
      setScheduledMessages([])
      return
    }
    try {
      const { data } = await api.get<ScheduledMessage[]>(
        `/chats/${chatId}/scheduled-messages`,
        { params: { project_id: selectedProjectId, active_only: true } },
      )
      setScheduledMessages(data)
    } catch (err) {
      if (!axios.isAxiosError(err) || err.response?.status !== 403) {
        notify({ tone: 'error', message: getErrorMessage(err) })
      }
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
      const selectedData = { ...data, unread: false, is_read: true }
      setChats((current) => {
        const existingIndex = current.findIndex((chat) => chat.id === selectedData.id)
        if (existingIndex < 0) {
          return [selectedData, ...current]
        }
        return current.map((chat, index) => (index === existingIndex ? selectedData : chat))
      })
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
      const nextMessages = sortMessagesByDate(messagesResponse.data.items)
      const latestMessageId = nextMessages[nextMessages.length - 1]?.id ?? null
      const hasNewLatestMessage = latestMessageId !== latestLoadedMessageIdRef.current
      if (showLoader || hasNewLatestMessage) {
        shouldAutoScrollMessagesRef.current = true
      }
      latestLoadedMessageIdRef.current = latestMessageId
      setMessageTotal(messagesResponse.data.total)
      setMessages((current) => (
        showLoader
          ? nextMessages
          : sortMessagesByDate(mergeById(current, nextMessages))
      ))
      setAuditLogs((current) => (
        showLoader
          ? auditResponse.data
          : mergeById(current, auditResponse.data)
      ))
      if (hasNewLatestMessage) {
        void markChatAsRead(chatId)
      }
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
  }, [markChatAsRead, notify, selectedProjectId])

  const loadOlderMessages = useCallback(async () => {
    if (
      !selectedChatId
      || isMessagesLoading
      || isMessagesLoadingMore
      || messages.length >= messageTotal
    ) {
      return
    }

    const chatId = selectedChatId
    const anchorMessage = messages[0]
    const container = messagesScrollRef.current
    const anchorElement = anchorMessage
      ? document.getElementById(`message-${anchorMessage.id}`)
      : null
    const anchorTop = container && anchorElement
      ? anchorElement.getBoundingClientRect().top - container.getBoundingClientRect().top
      : null

    olderMessagesAbortRef.current?.abort()
    const controller = new AbortController()
    olderMessagesAbortRef.current = controller
    setIsMessagesLoadingMore(true)

    try {
      const [messagesResponse, auditResponse] = await Promise.all([
        api.get<PaginatedResponse<Message>>(`/chats/${chatId}/messages`, {
          params: {
            limit: MESSAGE_LIMIT,
            offset: 0,
            ...(anchorMessage ? { before_message_id: anchorMessage.id } : {}),
            ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
          },
          signal: controller.signal,
        }),
        api.get<ChatAuditLog[]>(`/chats/${chatId}/audit-logs`, {
          params: {
            limit: MESSAGE_LIMIT,
            offset: auditLogs.length,
            ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
          },
          signal: controller.signal,
        }),
      ])
      if (controller.signal.aborted || selectedChatIdRef.current !== chatId) {
        return
      }

      const olderMessages = messagesResponse.data.items
      setMessageTotal(messagesResponse.data.total)
      if (olderMessages.length > 0) {
        if (anchorMessage && anchorTop !== null) {
          prependScrollAnchorRef.current = {
            messageId: anchorMessage.id,
            top: anchorTop,
          }
        }
        shouldAutoScrollMessagesRef.current = false
        setMessages((current) =>
          sortMessagesByDate(mergeById(current, olderMessages)),
        )
      }
      if (auditResponse.data.length > 0) {
        setAuditLogs((current) => mergeById(current, auditResponse.data))
      }
    } catch (err) {
      if (!isRequestCanceled(err)) {
        notify({
          tone: 'error',
          message: getErrorMessage(err, 'Не удалось загрузить предыдущие сообщения.'),
        })
      }
    } finally {
      if (olderMessagesAbortRef.current === controller) {
        olderMessagesAbortRef.current = null
        setIsMessagesLoadingMore(false)
      }
    }
  }, [
    auditLogs.length,
    isMessagesLoading,
    isMessagesLoadingMore,
    messageTotal,
    messages,
    notify,
    selectedChatId,
    selectedProjectId,
  ])

  const handleMessagesScroll = useCallback(() => {
    const container = messagesScrollRef.current
    if (!container) {
      return
    }
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
    shouldAutoScrollMessagesRef.current = distanceFromBottom <= 96
    if (container.scrollTop <= 120) {
      void loadOlderMessages()
    }
  }, [loadOlderMessages])

  const handleLeadSidebarChanged = useCallback(() => {
    void loadChats()
    if (!selectedChatId) {
      return
    }
    void loadMessages(selectedChatId)
    void loadSelectedChat(selectedChatId)
  }, [loadChats, loadMessages, loadSelectedChat, selectedChatId])

  const handleLeadTagsChanged = useCallback((tags: Chat['tags']) => {
    const chatId = selectedChatIdRef.current
    if (!chatId) {
      return
    }
    setChats((current) => current.map((chat) => (
      chat.id === chatId ? { ...chat, tags } : chat
    )))
  }, [])

  const handleToggleFavorite = useCallback(async (
    chatId: string,
    isFavorite: boolean,
  ) => {
    if (!selectedProjectId) {
      return
    }
    setChats((current) => current.map((chat) => (
      chat.id === chatId ? { ...chat, is_favorite: isFavorite } : chat
    )))
    setWorkspaceCounts((current) => ({
      ...current,
      favorites: Math.max(0, current.favorites + (isFavorite ? 1 : -1)),
    }))
    try {
      const { data } = await api.patch<Chat>(
        `/chats/${chatId}/favorite`,
        { is_favorite: isFavorite },
        { params: { project_id: selectedProjectId } },
      )
      setChats((current) => current.map((chat) => (chat.id === chatId ? data : chat)))
      await loadWorkspaceCounts()
      void loadChats()
    } catch (err) {
      setChats((current) => current.map((chat) => (
        chat.id === chatId ? { ...chat, is_favorite: !isFavorite } : chat
      )))
      await loadWorkspaceCounts()
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }, [loadChats, loadWorkspaceCounts, notify, selectedProjectId])

  useEffect(() => {
    void loadChats()
    void loadWorkspaceCounts()
    void loadBots()
    void loadProjectTranslation()
    void loadFilterOptions()
    void loadFilterPresets()
    void loadSnippets()
    const timer = window.setInterval(() => {
      void loadChats()
      void loadWorkspaceCounts()
    }, 5000)

    return () => {
      window.clearInterval(timer)
      chatsAbortRef.current?.abort()
      chatsAbortRef.current = null
    }
  }, [loadBots, loadChats, loadFilterOptions, loadFilterPresets, loadProjectTranslation, loadSnippets, loadWorkspaceCounts])

  useEffect(() => {
    if (
      !isDesktopChatLayout
      || chatFilters.workspaceView === 'unread'
      || selectedChatId
      || chats.length === 0
    ) {
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
    messagesAbortRef.current?.abort()
    olderMessagesAbortRef.current?.abort()
    prependScrollAnchorRef.current = null
    setMessages([])
    setMessageTotal(0)
    setIsMessagesLoadingMore(false)
    latestLoadedMessageIdRef.current = null
    setAuditLogs([])
    syncChatSearchParams(EMPTY_CHAT_FILTERS, null)
  }, [selectedProjectId, syncChatSearchParams])

  useEffect(() => {
    if (!selectedChatId) {
      setIsLeadOpen(false)
      shouldAutoScrollMessagesRef.current = true
      latestLoadedMessageIdRef.current = null
      messagesAbortRef.current?.abort()
      olderMessagesAbortRef.current?.abort()
      prependScrollAnchorRef.current = null
      setMessages([])
      setMessageTotal(0)
      setIsMessagesLoadingMore(false)
      setAuditLogs([])
      setScheduledMessages([])
      setIsMessagesLoading(false)
      return undefined
    }
    if (selectedChat && selectedChat.project_id !== selectedProjectId) {
      return undefined
    }

    shouldAutoScrollMessagesRef.current = true
    latestLoadedMessageIdRef.current = null
    olderMessagesAbortRef.current?.abort()
    prependScrollAnchorRef.current = null
    setMessages([])
    setMessageTotal(0)
    setIsMessagesLoadingMore(false)
    setAuditLogs([])
    setScheduledMessages([])
    void markChatAsRead(selectedChatId)
    void loadMessages(selectedChatId, true)
    void loadSelectedChat(selectedChatId)
    void loadScheduledMessages(selectedChatId)
    const timer = window.setInterval(() => {
      void loadMessages(selectedChatId)
      void loadSelectedChat(selectedChatId)
      void loadScheduledMessages(selectedChatId)
    }, 7000)

    return () => {
      window.clearInterval(timer)
      messagesAbortRef.current?.abort()
      olderMessagesAbortRef.current?.abort()
    }
  }, [loadMessages, loadScheduledMessages, loadSelectedChat, markChatAsRead, selectedChat?.project_id, selectedChatId, selectedProjectId])

  useEffect(() => {
    setAttachment(null)
    setDraft('')
    setIsAttachmentMenuOpen(false)
    setIsSnippetsOpen(false)
    setSnippetSearch('')
    setSnippetMedia(null)
    setTranslatedDraftOriginal(null)
    setReplyingToMessage(null)
    setEditingMessage(null)
    setMessagePendingDeletion(null)
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

  useLayoutEffect(() => {
    const pendingAnchor = prependScrollAnchorRef.current
    if (pendingAnchor) {
      prependScrollAnchorRef.current = null
      const container = messagesScrollRef.current
      const anchorElement = document.getElementById(`message-${pendingAnchor.messageId}`)
      if (container && anchorElement) {
        const nextTop =
          anchorElement.getBoundingClientRect().top - container.getBoundingClientRect().top
        container.scrollTop += nextTop - pendingAnchor.top
      }
      return
    }
    if (shouldAutoScrollMessagesRef.current) {
      scrollMessagesToBottom()
    }
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
    if (!searchNavigationKey) {
      handledSearchHitRef.current = null
      return undefined
    }
    if (handledSearchHitRef.current === searchNavigationKey) {
      return undefined
    }
    const frame = window.requestAnimationFrame(() => {
      const container = messagesScrollRef.current
      const target = document.getElementById(`message-${highlightedMessageId}`)
      if (!container || !target) {
        return
      }
      shouldAutoScrollMessagesRef.current = false
      handledSearchHitRef.current = searchNavigationKey
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
  }, [highlightedMessageId, messages, searchNavigationKey])

  const handleTranslateDraft = async () => {
    const text = draft.trim()
    if (!selectedChatId || isPreparingTranslation) {
      return
    }
    if (translatedDraftOriginal !== null) {
      setDraft(translatedDraftOriginal)
      setTranslatedDraftOriginal(null)
      return
    }
    if (!text) {
      notify({ tone: 'error', message: 'Сначала напишите текст для перевода.' })
      return
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
      setTranslatedDraftOriginal(data.original_text)
      setDraft(normalizeTranslationForChat(data.translated_text))
    } catch (err) {
      if (isTelegramUserBlockError(err) && selectedChatId) {
        setChats((current) => current.map((chat) => (
          chat.id === selectedChatId ? { ...chat, is_blocked_by_user: true } : chat
        )))
      }
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsPreparingTranslation(false)
    }
  }

  const sendMessage = async (options: {
    autoTranslate?: boolean
    originalText?: string
    textOverride?: string
  } = {}) => {
    const text = (options.textOverride ?? draft).trim()
    if (
      !selectedChatId ||
      isTelegramBlockedByUser ||
      (!text && !attachment && !snippetMedia) ||
      isSending ||
      isPreparingTranslation
    ) {
      return false
    }

    setIsSending(true)

    try {
      const params = {
        ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
        auto_translate: options.autoTranslate ?? false,
      }
      const originalText = (options.originalText ?? translatedDraftOriginal)?.trim()
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
              if (replyingToMessage) {
                formData.append('reply_to_message_id', replyingToMessage.id)
              }
              return formData
            })(),
            { params },
          )
        : snippetMedia
          ? await api.post<Message>(
              `/chats/${selectedChatId}/messages`,
              {
                snippet_id: snippetMedia.id,
                text,
                ...(originalText ? { original_text: originalText } : {}),
                ...(replyingToMessage ? { reply_to_message_id: replyingToMessage.id } : {}),
              },
              { params },
            )
        : await api.post<Message>(
            `/chats/${selectedChatId}/messages`,
            {
              media_type: 'text',
              text,
              ...(originalText ? { original_text: originalText } : {}),
              ...(replyingToMessage ? { reply_to_message_id: replyingToMessage.id } : {}),
            },
            { params },
          )
      shouldAutoScrollMessagesRef.current = true
      latestLoadedMessageIdRef.current = data.id
      setMessageTotal((current) => current + 1)
      setMessages((current) => sortMessagesByDate([...current, data]))
      setChats((current) => current.map((chat) => (
        chat.id === selectedChatId
          ? { ...chat, has_restarted_bot: false, is_read: true, unread: false }
          : chat
      )))
      setDraft('')
      clearAttachment()
      setSnippetMedia(null)
      setTranslatedDraftOriginal(null)
      setReplyingToMessage(null)
      await loadChats()
      void loadWorkspaceCounts()
      return true
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
      return false
    } finally {
      setIsSending(false)
    }
  }

  const insertSnippetIntoComposer = (snippet: ProjectSnippet) => {
    if (!selectedChatId || isTelegramBlockedByUser || isSending || isPreparingTranslation) {
      return
    }
    clearAttachment()
    setSnippetMedia(snippet.type === 'text' ? null : snippet)
    setDraft(snippet.content ?? '')
    setTranslatedDraftOriginal(null)
    setIsSnippetsOpen(false)
  }

  const openSnippetCreate = () => {
    setNewSnippetName('')
    setNewSnippetContent(draft)
    setNewSnippetType('text')
    setNewSnippetFile(null)
    setIsSnippetCreateOpen(true)
  }

  const handleCreateSnippet = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedProjectId || isCreatingSnippet) {
      return
    }

    const name = newSnippetName.trim()
    const content = newSnippetContent.trim()
    if (!name || (newSnippetType === 'text' && !content) || (newSnippetType !== 'text' && !newSnippetFile)) {
      notify({ tone: 'error', message: newSnippetType === 'text' ? 'Укажите название и текст заготовки.' : 'Укажите название и файл заготовки.' })
      return
    }

    setIsCreatingSnippet(true)
    try {
      const { data } = newSnippetType === 'text'
        ? await api.post<ProjectSnippet>(
            `/projects/${selectedProjectId}/snippets`,
            { name, type: 'text', content, channel: 'telegram' },
          )
        : await api.post<ProjectSnippet>(
            `/projects/${selectedProjectId}/snippets/media`,
            (() => {
              const formData = new FormData()
              formData.append('name', name)
              formData.append('type', newSnippetType)
              if (content) {
                formData.append('content', content)
              }
              formData.append('file', newSnippetFile as File, (newSnippetFile as File).name)
              return formData
            })(),
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

  const handleDeleteSnippet = async () => {
    if (!selectedProjectId || !snippetPendingDeletion || !canDeleteSnippets || isDeletingSnippet) {
      return
    }

    const snippetId = snippetPendingDeletion.id
    setIsDeletingSnippet(true)
    try {
      await api.delete(`/projects/${selectedProjectId}/snippets/${snippetId}`)
      setSnippets((current) => current.filter((snippet) => snippet.id !== snippetId))
      setSnippetMedia((current) => current?.id === snippetId ? null : current)
      setSnippetPendingDeletion(null)
      notify({ tone: 'success', message: 'Заготовка удалена.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err, 'Не удалось удалить заготовку.') })
    } finally {
      setIsDeletingSnippet(false)
    }
  }

  const handleTranslateMessage = async (message: Message) => {
    const isOutgoing = message.sender_type === 'manager' || message.sender_type === 'bot'
    const hasSavedAlternative = isOutgoing
      ? hasText(message.original_text) || hasText(message.translated_text)
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

    if (!selectedChatId || translatingMessageId) {
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

  const openMessageEditor = (message: Message) => {
    setEditingMessage(message)
    setEditingMessageText((message.body ?? message.caption ?? '').trim())
  }

  const handleEditMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedChatId || !editingMessage || isEditingMessage) {
      return
    }
    const text = editingMessageText.trim()
    if (!text) {
      notify({ tone: 'error', message: 'Текст сообщения не может быть пустым.' })
      return
    }
    setIsEditingMessage(true)
    try {
      const { data } = await api.patch<Message>(
        `/chats/${selectedChatId}/messages/${editingMessage.id}`,
        { text },
        { params: selectedProjectId ? { project_id: selectedProjectId } : undefined },
      )
      setMessages((current) => sortMessagesByDate(
        current.map((message) => message.id === data.id ? data : message),
      ))
      setEditingMessage(null)
      setEditingMessageText('')
      notify({ tone: 'success', message: 'Сообщение изменено в Telegram.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err, 'Не удалось изменить сообщение.') })
    } finally {
      setIsEditingMessage(false)
    }
  }

  const handleDeleteMessage = async () => {
    if (!selectedChatId || !messagePendingDeletion || isDeletingMessage) {
      return
    }
    const messageId = messagePendingDeletion.id
    setIsDeletingMessage(true)
    try {
      await api.delete(`/chats/${selectedChatId}/messages/${messageId}`, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setMessages((current) => current.filter((message) => message.id !== messageId))
      setMessageTotal((current) => Math.max(0, current - 1))
      setReplyingToMessage((current) => current?.id === messageId ? null : current)
      setMessagePendingDeletion(null)
      notify({ tone: 'success', message: 'Сообщение удалено из Telegram.' })
      void loadChats()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err, 'Не удалось удалить сообщение.') })
    } finally {
      setIsDeletingMessage(false)
    }
  }

  const scrollToMessage = (messageId: string) => {
    const target = document.getElementById(`message-${messageId}`)
    const container = messagesScrollRef.current
    if (!target || !container) {
      notify({ tone: 'info', message: 'Исходное сообщение находится выше. Загрузите предыдущие сообщения.' })
      return
    }
    shouldAutoScrollMessagesRef.current = false
    target.scrollIntoView({ block: 'center', behavior: 'smooth' })
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
    setSnippetMedia(null)
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

  const openScheduleMessage = () => {
    if (!selectedChatId || isTelegramBlockedByUser || (!draft.trim() && !attachment && !snippetMedia)) {
      return
    }
    const date = new Date(Date.now() + 5 * 60 * 1000)
    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60 * 1000)
    setScheduledAtLocal(localDate.toISOString().slice(0, 16))
    setIsScheduleOpen(true)
  }

  const handleScheduleMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedChatId || isTelegramBlockedByUser || !scheduledAtLocal || isScheduling) {
      return
    }
    const scheduledAt = new Date(scheduledAtLocal)
    if (Number.isNaN(scheduledAt.getTime()) || scheduledAt.getTime() <= Date.now()) {
      notify({ tone: 'error', message: 'Укажите время в будущем.' })
      return
    }
    const text = draft.trim()
    if (!text && !attachment && !snippetMedia) {
      return
    }

    setIsScheduling(true)
    try {
      const params = selectedProjectId ? { project_id: selectedProjectId } : undefined
      if (attachment) {
        const formData = new FormData()
        formData.append('scheduled_at', scheduledAt.toISOString())
        formData.append('media_type', attachment.media_type)
        formData.append('auto_translate', 'false')
        if (translatedDraftOriginal) {
          formData.append('original_text', translatedDraftOriginal)
        }
        formData.append('file', attachment.file, attachment.file.name)
        if (text) {
          formData.append('text', text)
        }
        await api.post(`/chats/${selectedChatId}/scheduled-messages`, formData, { params })
      } else if (snippetMedia) {
        await api.post(
          `/chats/${selectedChatId}/scheduled-messages`,
          {
            scheduled_at: scheduledAt.toISOString(),
            media_type: snippetMedia.type,
            snippet_id: snippetMedia.id,
            text,
            auto_translate: false,
            ...(translatedDraftOriginal ? { original_text: translatedDraftOriginal } : {}),
          },
          { params },
        )
      } else {
        await api.post(
          `/chats/${selectedChatId}/scheduled-messages`,
          {
            scheduled_at: scheduledAt.toISOString(),
            media_type: 'text',
            text,
            auto_translate: false,
            ...(translatedDraftOriginal ? { original_text: translatedDraftOriginal } : {}),
          },
          { params },
        )
      }
      setDraft('')
      setTranslatedDraftOriginal(null)
      clearAttachment()
      setSnippetMedia(null)
      setIsScheduleOpen(false)
      await loadScheduledMessages(selectedChatId)
      notify({ tone: 'success', message: 'Сообщение запланировано.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsScheduling(false)
    }
  }

  const handleCancelScheduledMessage = async (scheduledMessageId: string) => {
    if (!selectedChatId || !selectedProjectId || cancellingScheduledMessageId) {
      return
    }
    setCancellingScheduledMessageId(scheduledMessageId)
    try {
      await api.delete(`/chats/${selectedChatId}/scheduled-messages/${scheduledMessageId}`, {
        params: { project_id: selectedProjectId },
      })
      await loadScheduledMessages(selectedChatId)
      notify({ tone: 'success', message: 'Отложенное сообщение отменено.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setCancellingScheduledMessageId(null)
    }
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
      setMediaPreview((current) => {
        if (current) window.URL.revokeObjectURL(current.url)
        return { message, url: blobUrl }
      })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) || 'Не удалось открыть медиа.' })
    } finally {
      setOpeningMediaId(null)
    }
  }

  const closeMediaPreview = () => {
    setMediaPreview((current) => {
      if (current) window.URL.revokeObjectURL(current.url)
      return null
    })
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
    <section className="relative grid h-full min-h-0 grid-cols-1 gap-0 overflow-hidden text-gray-200 md:gap-4 md:grid-cols-[minmax(250px,35%)_minmax(0,1fr)] lg:grid-cols-[minmax(250px,25%)_minmax(0,50%)_minmax(250px,25%)]">
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
          hasMore={loadedChatCount < total}
          trackingOptions={trackingOptions}
          tagOptions={tagOptions}
          statusOptions={statusOptions}
          stepOptions={stepOptions}
          userOptions={userOptions}
          isLoading={isChatsLoading}
          isLoadingMore={isChatsLoadingMore}
          scopeLabel={botScopeLabel}
          selectedChatId={selectedChatId}
          total={total}
          workspaceCounts={workspaceCounts}
          onFiltersChange={setChatFilters}
          onLoadMore={() => void loadChats({ append: true })}
          onApplyPreset={handleApplyPreset}
          onDeletePreset={(presetId) => void handleDeletePreset(presetId)}
          onResetFilters={() => setChatFilters(EMPTY_CHAT_FILTERS)}
          onRefresh={() => void loadChats()}
          onSavePreset={(name, isShared) => void handleSavePreset(name, isShared)}
          onSelectChat={handleSelectChat}
          onToggleFavorite={(chatId, isFavorite) => void handleToggleFavorite(chatId, isFavorite)}
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
                    {selectedChat.is_hot_lead ? (
                      <span className="hidden rounded-full border border-amber-300/25 bg-amber-400/10 px-2 py-0.5 text-[11px] font-medium text-amber-100 sm:inline-flex">
                        Горячий
                      </span>
                    ) : null}
                    {selectedChat.is_red ? <AlertCircle size={16} className="text-red-300 drop-shadow-[0_0_10px_rgba(248,113,113,0.6)]" /> : null}
                    {selectedChat.is_blocked_by_user ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-red-300/25 bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-100">
                        <Ban size={12} />
                        Бот заблокирован
                      </span>
                    ) : null}
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
                <button
                  type="button"
                  onClick={() => void handleToggleFavorite(selectedChat.id, !selectedChat.is_favorite)}
                  className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition ${
                    selectedChat.is_favorite
                      ? 'border-amber-300/30 bg-amber-300/10 text-amber-200'
                      : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-amber-300/30 hover:text-amber-200'
                  }`}
                  title={selectedChat.is_favorite ? 'Убрать из избранного' : 'Добавить в избранное'}
                  aria-label={selectedChat.is_favorite ? 'Убрать из избранного' : 'Добавить в избранное'}
                >
                  <Star size={16} className={selectedChat.is_favorite ? 'fill-current' : ''} />
                </button>
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
                  <span>
                    {selectedChat.is_read ? 'Прочитано лидом' : 'Не прочитано лидом'}
                  </span>
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
          onScroll={handleMessagesScroll}
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
              {messages.length < messageTotal ? (
                <div className="flex justify-center pb-1">
                  <button
                    type="button"
                    onClick={() => void loadOlderMessages()}
                    disabled={isMessagesLoadingMore}
                    className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-300 transition hover:border-accent-300/40 hover:text-white disabled:cursor-wait disabled:opacity-60"
                  >
                    {isMessagesLoadingMore ? (
                      <LoaderCircle size={14} className="animate-spin" />
                    ) : (
                      <Clock3 size={14} />
                    )}
                    Предыдущие сообщения
                  </button>
                </div>
              ) : null}
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
                const isExternalAccountMessage = message.is_external_account_message === true
                const isBot = message.sender_type === 'bot' && !isExternalAccountMessage
                const messageButtons = message.buttons ?? []
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
                const outgoingAlternativeText = originalText ?? translatedText
                const hasTranslatableText = hasText(message.body) || hasText(message.caption)
                const isAlternateTextVisible = alternateMessageTextIds.has(message.id)
                const canUseMessageTextToggle = isOutgoing
                  ? hasTranslatableText || Boolean(outgoingAlternativeText)
                  : hasTranslatableText
                const isTranslationLoading = translatingMessageId === message.id
                const visibleBody =
                  isAlternateTextVisible && isOutgoing && outgoingAlternativeText
                    ? outgoingAlternativeText
                    : isAlternateTextVisible && !isOutgoing && translatedText
                      ? translatedText
                      : message.body
                const visibleCaption =
                  isAlternateTextVisible && isOutgoing && outgoingAlternativeText
                    ? outgoingAlternativeText
                    : isAlternateTextVisible && !isOutgoing && translatedText
                      ? translatedText
                      : message.caption
                const textToggleLabel = isAlternateTextVisible
                  ? (isOutgoing && originalText ? 'Перевод' : 'Оригинал')
                  : isOutgoing
                    ? originalText
                      ? 'Исходник'
                      : translatedText
                        ? 'Перевод'
                        : 'Перевести'
                    : translatedText
                      ? 'Перевод'
                      : 'Перевести'
                const textToggleTitle = isAlternateTextVisible
                  ? 'Показать исходный текст сообщения'
                  : isOutgoing
                    ? originalText
                      ? 'Показать текст до перевода'
                      : 'Перевести сообщение для оператора'
                    : 'Показать перевод вместо оригинала'
                const canReplyToMessage = !isBuyer && Boolean(message.external_message_id)
                const canEditMessage =
                  !isBuyer
                  && isOutgoing
                  && Boolean(message.external_message_id)
                  && hasTranslatableText
                  && message.message_type !== 'video_note'
                const canDeleteMessage = !isBuyer && Boolean(message.external_message_id)

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
                              : isExternalAccountMessage
                                ? 'border-cyan-300/25 bg-cyan-400/10 text-cyan-50 shadow-glow-accent'
                                : 'border-primary-300/25 bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary'
                            : 'border-white/10 bg-white/[0.055] text-gray-100'
                        } ${
                          highlightedMessageId === message.id
                            ? 'ring-2 ring-amber-300/70'
                            : ''
                        }`}
                      >
                        {message.reply_to ? (
                          <button
                            type="button"
                            onClick={() => scrollToMessage(message.reply_to?.id ?? '')}
                            className="mb-2 block w-full border-l-2 border-accent-300/60 bg-black/10 px-2 py-1.5 text-left"
                            title="Перейти к исходному сообщению"
                          >
                            <span className="block text-[11px] font-semibold text-accent-100">
                              Ответ на сообщение
                            </span>
                            <span className="block max-w-[22rem] truncate text-xs opacity-70">
                              {message.reply_to.deleted_at
                                ? 'Сообщение удалено'
                                : messageSummary(message.reply_to)}
                            </span>
                          </button>
                        ) : null}
                        <div className="mb-1 flex items-center gap-1.5 text-xs opacity-75">
                          {isExternalAccountMessage ? <UserRound size={13} /> : isBot ? <Bot size={13} /> : null}
                          <span>
                            {message.sender_type === 'manager'
                              ? 'менеджер'
                              : isExternalAccountMessage
                                ? 'рабочий аккаунт · из Telegram'
                                : message.sender_type === 'bot'
                                  ? 'бот'
                                  : 'клиент'}
                          </span>
                          <span>{formatDateTime(message.created_at)}</span>
                          {message.edited_at ? <span>· изменено</span> : null}
                        </div>
                        {message.message_type === 'text' || message.message_type === 'system' || message.message_type === 'contact' ? (
                          <p className="whitespace-pre-wrap break-words text-sm leading-6">
                            {message.message_type === 'contact' ? `Телефон: ${visibleBody || 'не указан'}` : visibleBody || ''}
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
                                          <Eye size={15} />
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
                        {messageButtons.length > 0 ? (
                          <div className="mt-2 border-t border-white/10 pt-2">
                            <p className="mb-1.5 inline-flex items-center gap-1.5 text-[11px] font-medium opacity-70">
                              <MousePointerClick size={12} />
                              Кнопки сообщения
                            </p>
                            <div className="grid gap-1.5">
                              {messageButtons.map((label, index) => (
                                <span
                                  key={`${message.id}:button:${index}`}
                                  className="block min-h-8 rounded-lg border border-white/15 bg-black/10 px-3 py-1.5 text-center text-xs leading-5"
                                >
                                  {label}
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        {canUseMessageTextToggle || canReplyToMessage || canEditMessage || canDeleteMessage ? (
                          <div className="mt-2 flex flex-wrap justify-end gap-1 border-t border-white/10 pt-1.5">
                            {canReplyToMessage ? (
                              <button
                                type="button"
                                onClick={() => {
                                  setReplyingToMessage(message)
                                  handleComposerFocus()
                                }}
                                className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-black/10 text-white/70 transition hover:border-accent-300/40 hover:text-white"
                                title="Ответить на сообщение"
                                aria-label="Ответить на сообщение"
                              >
                                <Reply size={12} />
                              </button>
                            ) : null}
                            {canEditMessage ? (
                              <button
                                type="button"
                                onClick={() => openMessageEditor(message)}
                                className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-black/10 text-white/70 transition hover:border-accent-300/40 hover:text-white"
                                title="Редактировать сообщение"
                                aria-label="Редактировать сообщение"
                              >
                                <Pencil size={12} />
                              </button>
                            ) : null}
                            {canDeleteMessage ? (
                              <button
                                type="button"
                                onClick={() => setMessagePendingDeletion(message)}
                                className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-red-300/15 bg-red-500/5 text-red-100/70 transition hover:border-red-300/40 hover:text-red-100"
                                title="Удалить сообщение"
                                aria-label="Удалить сообщение"
                              >
                                <Trash2 size={12} />
                              </button>
                            ) : null}
                            {canUseMessageTextToggle ? (
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
                            ) : null}
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

        {selectedChat && scheduledMessages.some((item) => ['pending', 'running', 'failed'].includes(item.status)) ? (
          <div className="shrink-0 border-t border-white/5 bg-[#0B0F19]/95 px-3 py-2 md:px-4">
            <div className="flex items-center gap-2 overflow-x-auto">
              <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold text-gray-300">
                <Clock3 size={14} className="text-accent-200" />
                Отложенные
              </span>
              {scheduledMessages
                .filter((item) => ['pending', 'running', 'failed'].includes(item.status))
                .slice(0, 5)
                .map((item) => (
                  <div
                    key={item.id}
                    className={`flex min-w-[13rem] max-w-xs shrink-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 ${
                      item.status === 'failed'
                        ? 'border-red-300/25 bg-red-500/10'
                        : 'border-white/10 bg-white/[0.04]'
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs text-gray-200">
                        {item.file_name ?? item.text ?? 'Сообщение'}
                      </p>
                      <p className={`truncate text-[11px] ${item.status === 'failed' ? 'text-red-200' : 'text-gray-500'}`}>
                        {item.status === 'failed'
                          ? item.last_error || 'Ошибка отправки'
                          : new Date(item.scheduled_at).toLocaleString()}
                      </p>
                    </div>
                    {!isBuyer && item.status === 'pending' ? (
                      <button
                        type="button"
                        onClick={() => void handleCancelScheduledMessage(item.id)}
                        disabled={cancellingScheduledMessageId === item.id}
                        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition hover:bg-red-500/10 hover:text-red-100 disabled:opacity-50"
                        title="Отменить отложенное сообщение"
                      >
                        {cancellingScheduledMessageId === item.id
                          ? <LoaderCircle size={13} className="animate-spin" />
                          : <X size={14} />}
                      </button>
                    ) : null}
                  </div>
                ))}
            </div>
          </div>
        ) : null}

        <form
          className={`${isBuyer ? 'hidden' : 'relative z-10'} shrink-0 border-t border-white/5 bg-surface/95 p-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:p-4`}
          onSubmit={handleSend}
        >
          {isTelegramBlockedByUser ? (
            <div className="flex items-start gap-3 rounded-xl border border-red-300/25 bg-red-500/10 px-4 py-3 text-red-100">
              <Ban size={18} className="mt-0.5 shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-semibold">Пользователь заблокировал бота.</p>
                <p className="mt-1 text-xs leading-5 text-red-100/75">
                  Отправка сообщений невозможна, пока клиент снова не разблокирует бота в Telegram.
                </p>
              </div>
            </div>
          ) : (
            <div>
          {replyingToMessage ? (
            <div className="mb-2 flex items-center gap-3 border-l-2 border-accent-300/60 bg-accent-300/[0.06] px-3 py-2">
              <Reply size={15} className="shrink-0 text-accent-100" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-accent-100">Ответ на сообщение</p>
                <p className="truncate text-xs text-gray-400">{messageSummary(replyingToMessage)}</p>
              </div>
              <button
                type="button"
                onClick={() => setReplyingToMessage(null)}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-white/[0.05] hover:text-white"
                title="Отменить ответ"
              >
                <X size={15} />
              </button>
            </div>
          ) : null}
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
          {snippetMedia ? (
            <div className="mb-3 flex items-center gap-3 rounded-xl border border-accent-300/25 bg-accent-300/[0.06] p-3">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-accent-300/20 bg-accent-300/10 text-accent-100">
                {(() => {
                  const Icon = getMediaIcon(snippetMedia.type)
                  return <Icon size={18} />
                })()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-white">{snippetMedia.name}</p>
                <p className="text-xs text-gray-500">Заготовка · {mediaLabels[snippetMedia.type]}</p>
              </div>
              <button
                type="button"
                onClick={() => setSnippetMedia(null)}
                className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-red-300/40 hover:text-red-100"
                title="Убрать заготовку"
              >
                <X size={16} />
              </button>
            </div>
          ) : null}
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={() => void handleTranslateDraft()}
              disabled={
                !selectedChat
                || !draft.trim()
                || isSending
                || isPreparingTranslation
                || projectTranslation?.is_translation_enabled === false
              }
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-sky-300/20 bg-sky-300/10 px-3 text-xs font-medium text-sky-50 transition hover:border-sky-300/40 disabled:cursor-not-allowed disabled:opacity-50"
              title={translatedDraftOriginal
                ? 'Вернуть текст до перевода'
                : `Перевести набранный текст с ${operatorLangLabel} на ${clientLangLabel}`}
            >
              {isPreparingTranslation
                ? <LoaderCircle size={14} className="animate-spin" />
                : <Languages size={14} />}
              <span className="whitespace-nowrap">
                {translatedDraftOriginal ? 'Вернуть исходник' : `Перевести на ${clientLangLabel}`}
              </span>
            </button>
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
                    {canCreateSnippets ? (
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
                            <div
                              key={snippet.id}
                              className="group flex items-start gap-1 rounded-lg transition hover:bg-white/[0.05]"
                            >
                              <button
                                type="button"
                                onClick={() => insertSnippetIntoComposer(snippet)}
                                disabled={isSending || isDeletingSnippet}
                                className="flex min-w-0 flex-1 items-start gap-3 rounded-lg px-3 py-2 text-left disabled:cursor-not-allowed disabled:opacity-50"
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
                              {canDeleteSnippets ? (
                                <button
                                  type="button"
                                  onClick={() => setSnippetPendingDeletion(snippet)}
                                  disabled={isDeletingSnippet}
                                  className="mr-1 mt-2 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-gray-500 transition hover:bg-red-500/10 hover:text-red-200 disabled:cursor-not-allowed disabled:opacity-50"
                                  title={`Удалить заготовку «${snippet.name}»`}
                                  aria-label={`Удалить заготовку «${snippet.name}»`}
                                >
                                  <Trash2 size={15} />
                                </button>
                              ) : null}
                            </div>
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
              placeholder={attachment || snippetMedia ? 'Добавить подпись к вложению' : 'Ответить в Telegram'}
              disabled={!selectedChat || isSending || isPreparingTranslation}
              rows={1}
            />
            <button
              type="button"
              title="Отложить отправку"
              onClick={openScheduleMessage}
              disabled={!selectedChat || (!draft.trim() && !attachment && !snippetMedia) || isSending || isPreparingTranslation}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Clock3 size={17} />
            </button>
            <button
              type="submit"
              title="Отправить сообщение"
              disabled={!selectedChat || isTelegramBlockedByUser || (!draft.trim() && !attachment && !snippetMedia) || isSending || isPreparingTranslation}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSending || isPreparingTranslation ? <LoaderCircle size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </div>
            </div>
          )}
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
          onSetBlocked={user?.role_name === 'manager' || isBuyer
            ? undefined
            : (isBlocked) => {
                if (isBlocked) {
                  setIsBlockConfirmOpen(true)
                  return
                }
                void handleSetChatBlocked(false)
              }}
          onResetRequest={user?.role_name === 'manager' || isBuyer ? undefined : () => setIsResetConfirmOpen(true)}
          onLeadStatusChanged={handleLeadSidebarChanged}
          onLeadTagsChanged={handleLeadTagsChanged}
        />
      </div>

      {isSnippetCreateOpen ? (
        <Modal
          title="Новая заготовка"
          description="Её смогут использовать операторы этого проекта. Менеджеры могут добавлять заготовки, а удаление остаётся у администраторов."
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
              <span className="mb-1.5 block text-sm font-medium text-gray-200">Тип</span>
              <select
                value={newSnippetType}
                onChange={(event) => setNewSnippetType(event.target.value as ProjectSnippet['type'])}
                className="h-11 w-full rounded-xl border border-white/10 bg-background/80 px-3 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 md:text-sm"
                disabled={isCreatingSnippet}
              >
                <option value="text">Текст</option>
                {attachmentModes.map((mode) => (
                  <option key={mode.type} value={mode.type}>{mode.label}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-gray-200">
                {newSnippetType === 'text' ? 'Текст' : 'Подпись к вложению'}
              </span>
              <textarea
                value={newSnippetContent}
                onChange={(event) => setNewSnippetContent(event.target.value)}
                rows={8}
                placeholder={newSnippetType === 'text' ? 'Текст быстрого ответа' : 'Необязательная подпись'}
                className="touch-scroll w-full resize-y rounded-xl border border-white/10 bg-background/80 px-3 py-2.5 text-base leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                disabled={isCreatingSnippet}
              />
            </label>
            {newSnippetType !== 'text' ? (
              <label className="block rounded-xl border border-dashed border-white/15 bg-white/[0.025] p-3">
                <span className="flex items-center gap-2 text-sm font-medium text-gray-200">
                  <Paperclip size={16} />
                  Файл заготовки
                </span>
                <input
                  type="file"
                  accept={attachmentModes.find((mode) => mode.type === newSnippetType)?.accept ?? '*/*'}
                  onChange={(event) => setNewSnippetFile(event.target.files?.[0] ?? null)}
                  className="mt-2 block w-full text-sm text-gray-400 file:mr-3 file:rounded-lg file:border-0 file:bg-accent-300/15 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-accent-100 hover:file:bg-accent-300/25"
                  disabled={isCreatingSnippet}
                />
                {newSnippetFile ? <span className="mt-2 block truncate text-xs text-emerald-200">{newSnippetFile.name}</span> : null}
              </label>
            ) : null}
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
                disabled={isCreatingSnippet || !newSnippetName.trim() || (newSnippetType === 'text' ? !newSnippetContent.trim() : !newSnippetFile)}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCreatingSnippet ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Добавить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {isScheduleOpen ? (
        <Modal
          title="Отложить сообщение"
          description="Сообщение хранится на сервере и будет отправлено worker’ом, даже если браузер закрыт."
          maxWidthClassName="max-w-lg"
          onClose={() => {
            if (!isScheduling) {
              setIsScheduleOpen(false)
            }
          }}
        >
          <form className="space-y-4" onSubmit={(event) => void handleScheduleMessage(event)}>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-gray-200">Дата и время</span>
              <input
                type="datetime-local"
                value={scheduledAtLocal}
                onChange={(event) => setScheduledAtLocal(event.target.value)}
                min={new Date().toISOString().slice(0, 16)}
                className="h-11 w-full rounded-xl border border-white/10 bg-background/80 px-3 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 md:text-sm"
                required
                disabled={isScheduling}
              />
            </label>
            <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3 text-sm text-gray-300">
              {attachment
                ? `${mediaLabels[attachment.media_type]}: ${attachment.file_name}`
                : snippetMedia
                  ? `${mediaLabels[snippetMedia.type]}: ${snippetMedia.name}`
                  : draft.trim()}
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setIsScheduleOpen(false)} disabled={isScheduling} className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 px-4 text-sm font-medium text-gray-200 transition hover:border-white/20 disabled:opacity-60">Отмена</button>
              <button type="submit" disabled={isScheduling || !scheduledAtLocal} className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition disabled:opacity-60">
                {isScheduling ? <LoaderCircle size={16} className="animate-spin" /> : <Clock3 size={16} />}
                Запланировать
              </button>
            </div>
          </form>
          {scheduledMessages.filter((item) => item.status === 'pending').length > 0 ? (
            <div className="mt-5 border-t border-white/10 pt-4">
              <p className="text-sm font-semibold text-white">В очереди</p>
              <div className="mt-2 max-h-44 space-y-2 overflow-y-auto pr-1">
                {scheduledMessages.filter((item) => item.status === 'pending').map((item) => (
                  <div key={item.id} className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.025] px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-gray-200">{item.file_name ?? item.text ?? 'Сообщение'}</p>
                      <p className="text-xs text-gray-500">{new Date(item.scheduled_at).toLocaleString()}</p>
                    </div>
                    <button type="button" onClick={() => void handleCancelScheduledMessage(item.id)} disabled={cancellingScheduledMessageId === item.id} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-gray-400 transition hover:border-red-300/40 hover:text-red-100 disabled:opacity-50" title="Отменить">
                      {cancellingScheduledMessageId === item.id ? <LoaderCircle size={14} className="animate-spin" /> : <X size={15} />}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </Modal>
      ) : null}

      {editingMessage ? (
        <Modal
          title="Редактировать сообщение"
          description="Изменение будет сразу применено в Telegram и в истории CRM."
          maxWidthClassName="max-w-xl"
          onClose={() => {
            if (!isEditingMessage) {
              setEditingMessage(null)
              setEditingMessageText('')
            }
          }}
        >
          <form className="space-y-4" onSubmit={(event) => void handleEditMessage(event)}>
            <textarea
              value={editingMessageText}
              onChange={(event) => setEditingMessageText(event.target.value)}
              rows={7}
              autoFocus
              className="touch-scroll w-full resize-y rounded-xl border border-white/10 bg-background/80 px-3 py-2.5 text-base leading-6 text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
              disabled={isEditingMessage}
            />
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => {
                  setEditingMessage(null)
                  setEditingMessageText('')
                }}
                disabled={isEditingMessage}
                className="inline-flex h-11 items-center justify-center rounded-xl border border-white/10 px-4 text-sm font-medium text-gray-200 transition hover:border-white/20 disabled:opacity-60"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isEditingMessage || !editingMessageText.trim()}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-gradient-to-br from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition disabled:opacity-60"
              >
                {isEditingMessage ? <LoaderCircle size={16} className="animate-spin" /> : <Pencil size={16} />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {mediaPreview ? (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm" role="dialog" aria-modal="true">
          <button type="button" className="absolute inset-0" aria-label="Закрыть просмотр медиа" onClick={closeMediaPreview} />
          <div className="relative flex max-h-[calc(100dvh-24px)] w-full max-w-4xl flex-col overflow-hidden rounded-lg border border-white/10 bg-[#0d1222] shadow-2xl">
            <div className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-white/10 px-4">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-white">{mediaPreview.message.file_name || getMediaLabel(mediaPreview.message)}</p>
                <p className="text-xs text-gray-500">{getMediaLabel(mediaPreview.message)}</p>
              </div>
              <button type="button" onClick={closeMediaPreview} className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-white/25 hover:text-white" aria-label="Закрыть">
                <X size={17} />
              </button>
            </div>
            <div className="touch-scroll flex min-h-0 flex-1 items-center justify-center overflow-auto bg-black/25 p-3 md:p-5">
              {mediaPreview.message.message_type === 'photo' || mediaPreview.message.message_type === 'image' || mediaPreview.message.message_type === 'sticker' ? (
                <img src={mediaPreview.url} alt={mediaPreview.message.file_name || 'Медиа Telegram'} className="max-h-[calc(100dvh-8rem)] max-w-full object-contain" />
              ) : mediaPreview.message.message_type === 'video' || mediaPreview.message.message_type === 'animation' || mediaPreview.message.message_type === 'video_note' ? (
                <video
                  src={mediaPreview.url}
                  controls
                  autoPlay
                  playsInline
                  className={mediaPreview.message.message_type === 'video_note' ? 'aspect-square max-h-[min(70dvh,32rem)] max-w-full rounded-full bg-black object-cover' : 'max-h-[calc(100dvh-8rem)] max-w-full bg-black object-contain'}
                />
              ) : mediaPreview.message.message_type === 'voice' || mediaPreview.message.message_type === 'audio' ? (
                <div className="w-full max-w-xl rounded-lg border border-white/10 bg-white/[0.04] p-5">
                  <audio src={mediaPreview.url} controls autoPlay className="w-full" />
                </div>
              ) : (
                <iframe src={mediaPreview.url} title={mediaPreview.message.file_name || 'Документ Telegram'} className="h-[75dvh] w-full rounded-lg border-0 bg-white" />
              )}
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
              onSetBlocked={user?.role_name === 'manager' || isBuyer
                ? undefined
                : (isBlocked) => {
                    if (isBlocked) {
                      setIsBlockConfirmOpen(true)
                      return
                    }
                    void handleSetChatBlocked(false)
                  }}
              onResetRequest={user?.role_name === 'manager' || isBuyer ? undefined : () => setIsResetConfirmOpen(true)}
              onLeadStatusChanged={handleLeadSidebarChanged}
              onLeadTagsChanged={handleLeadTagsChanged}
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

      {snippetPendingDeletion ? (
        <ConfirmDialog
          title="Удалить заготовку?"
          description={`«${snippetPendingDeletion.name}» исчезнет у всех операторов проекта. Это действие нельзя отменить.`}
          confirmLabel="Удалить"
          tone="danger"
          isLoading={isDeletingSnippet}
          onCancel={() => {
            if (!isDeletingSnippet) {
              setSnippetPendingDeletion(null)
            }
          }}
          onConfirm={() => void handleDeleteSnippet()}
        />
      ) : null}

      {messagePendingDeletion ? (
        <ConfirmDialog
          title="Удалить сообщение?"
          description="Сообщение будет удалено и из Telegram, и из истории CRM. Telegram разрешает удаление только в пределах своих ограничений."
          confirmLabel="Удалить"
          tone="danger"
          isLoading={isDeletingMessage}
          onCancel={() => {
            if (!isDeletingMessage) {
              setMessagePendingDeletion(null)
            }
          }}
          onConfirm={() => void handleDeleteMessage()}
        />
      ) : null}
    </section>
  )
}

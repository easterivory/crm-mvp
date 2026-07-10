import {
  AtSign,
  CalendarDays,
  Check,
  Clock3,
  Ban,
  Copy,
  LoaderCircle,
  Palette,
  Phone,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Tag,
  UserRound,
  WalletCards,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'

import api from '../api/client'
import FunnelTraceWidget from '../features/chats/components/FunnelTraceWidget'
import DuplicateWarning from '../features/leads/components/DuplicateWarning'
import { useProjectBotSelection } from '../shared/lib'

type Lead = {
  id: string
  project_id: string
  chat_id: string
  manager_id: string | null
  status_id: string
  name: string | null
  first_name: string | null
  last_name: string | null
  phone: string | null
  username: string | null
  age: number | null
  country: string | null
  call_time_text: string | null
  preferred_call_time: string | null
  manager_comment: string | null
  has_card: boolean | null
  custom_fields?: Record<string, unknown>
  updated_at: string
  created_at: string
  is_deleted: boolean
  tags?: Array<{ id: string; name: string; color: string }>
  external_chat_id?: string | null
  external_user_id?: string | null
}

type LeadStatus = {
  id: string
  code: string
  name: string
  sort_order: number
  is_final: boolean
  created_at: string
}

type User = {
  id: string
  email: string
  name: string
  project_id: string | null
  role_id: string
  created_at: string
  is_deleted: boolean
}

type FunnelControl = {
  is_available: boolean
  is_paused: boolean
  funnel_id: string | null
  funnel_name: string | null
  current_step_id: string | null
  current_step_title: string | null
  steps: Array<{
    id: string
    title: string
    step_type: string
    block_type: string
  }>
}

type ProjectTag = {
  id: string
  project_id: string
  name: string
  color: string
  created_at: string
}

type PaginatedResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type LeadSidebarProps = {
  activeBotId: string | null
  activeBotName: string | null
  activeChatId: string | null
  hasActiveScope: boolean
  isChatBlocked: boolean
  isUpdatingChatBlock?: boolean
  currentUserId: string | null
  currentUserRole: string | null
  onSetBlocked?: (isBlocked: boolean) => void
  onResetRequest?: () => void
  onLeadStatusChanged?: () => void
}

const TAG_COLOR_PALETTE = [
  '#BFDBFE',
  '#C7D2FE',
  '#DDD6FE',
  '#FBCFE8',
  '#FECACA',
  '#FED7AA',
  '#FDE68A',
  '#D9F99D',
  '#BBF7D0',
  '#A7F3D0',
  '#BAE6FD',
  '#E9D5FF',
]

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

function tagStyle(color: string | null | undefined) {
  return {
    backgroundColor: withAlpha(color, 0.14),
    borderColor: withAlpha(color, 0.6),
    color: '#F8FAFC',
  }
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
    year: 'numeric',
  }).format(new Date(value))
}

function attributionEntries(customFields: Record<string, unknown> | undefined) {
  const raw = customFields?.fb_data
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return []
  }

  return Object.entries(raw as Record<string, unknown>)
    .filter(([key, value]) => (
      key.startsWith('utm_') || ['fbclid', 'gclid', 'ttclid'].includes(key)
    ) && (typeof value === 'string' || typeof value === 'number'))
    .map(([key, value]) => [key, String(value)] as const)
}

function customFieldEntries(customFields: Record<string, unknown> | undefined) {
  if (!customFields) {
    return []
  }
  return Object.entries(customFields)
    .filter(([key, value]) => (
      key !== 'fb_data'
      && key !== 'expected_start_amount'
      && key !== 'budget'
      && !key.startsWith('__')
      && value !== null
      && value !== undefined
      && ['string', 'number', 'boolean'].includes(typeof value)
      && String(value).trim() !== ''
    ))
    .map(([key, value]) => [
      key.replace(/_/g, ' ').replace(/^\p{L}/u, (letter) => letter.toUpperCase()),
      typeof value === 'boolean' ? (value ? 'Да' : 'Нет') : String(value),
    ] as const)
}

function expectedStartAmount(customFields: Record<string, unknown> | undefined) {
  const value = customFields?.expected_start_amount ?? customFields?.budget
  return value === null || value === undefined || String(value).trim() === ''
    ? null
    : String(value)
}

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => item?.msg)
        .filter((message): message is string => typeof message === 'string')
      if (messages.length > 0) {
        return messages.join('; ')
      }
    }
    if (err.response?.status === 404) {
      return 'Лид для этого чата ещё не создан.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }

  return fallback
}

export default function LeadSidebar({
  activeBotId,
  activeBotName,
  activeChatId,
  hasActiveScope,
  isChatBlocked,
  isUpdatingChatBlock = false,
  currentUserId,
  currentUserRole,
  onSetBlocked,
  onResetRequest,
  onLeadStatusChanged,
}: LeadSidebarProps) {
  const { selectedProjectId } = useProjectBotSelection()
  const [lead, setLead] = useState<Lead | null>(null)
  const [statuses, setStatuses] = useState<LeadStatus[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [tags, setTags] = useState<ProjectTag[]>([])
  const [selectedTagId, setSelectedTagId] = useState('')
  const [tagSearch, setTagSearch] = useState('')
  const [firstNameDraft, setFirstNameDraft] = useState('')
  const [lastNameDraft, setLastNameDraft] = useState('')
  const [usernameDraft, setUsernameDraft] = useState('')
  const [phoneDraft, setPhoneDraft] = useState('')
  const [preferredCallTimeDraft, setPreferredCallTimeDraft] = useState('')
  const [managerCommentDraft, setManagerCommentDraft] = useState('')
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [editingTagColorId, setEditingTagColorId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [managerCommentError, setManagerCommentError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSavingContact, setIsSavingContact] = useState(false)
  const [isSavingManagerComment, setIsSavingManagerComment] = useState(false)
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false)
  const [isAssigning, setIsAssigning] = useState(false)
  const [isTagsLoading, setIsTagsLoading] = useState(false)
  const [isTagMutating, setIsTagMutating] = useState(false)
  const [funnelControl, setFunnelControl] = useState<FunnelControl | null>(null)
  const [selectedReturnStepId, setSelectedReturnStepId] = useState('')
  const [isFunnelControlLoading, setIsFunnelControlLoading] = useState(false)
  const [isResumingFunnel, setIsResumingFunnel] = useState(false)
  const managerCommentSaveSeqRef = useRef(0)

  const currentStatus = useMemo(
    () => statuses.find((status) => status.id === lead?.status_id) ?? null,
    [lead?.status_id, statuses],
  )

  const assignedManager = useMemo(
    () => users.find((user) => user.id === lead?.manager_id) ?? null,
    [lead?.manager_id, users],
  )

  const isContactDirty = Boolean(
    lead &&
      (firstNameDraft.trim() !== (lead.first_name ?? '') ||
        lastNameDraft.trim() !== (lead.last_name ?? '') ||
        usernameDraft.trim() !== (lead.username ?? '') ||
        phoneDraft.trim() !== (lead.phone ?? '') ||
        preferredCallTimeDraft.trim() !== (lead.preferred_call_time ?? lead.call_time_text ?? '')),
  )

  const availableTags = useMemo(() => {
    const attachedTagIds = new Set((lead?.tags ?? []).map((tag) => tag.id))
    return tags.filter((tag) => !attachedTagIds.has(tag.id))
  }, [lead?.tags, tags])

  const filteredAvailableTags = useMemo(() => {
    const needle = tagSearch.trim().toLowerCase()
    if (!needle) {
      return availableTags
    }
    return availableTags.filter((tag) => tag.name.toLowerCase().includes(needle))
  }, [availableTags, tagSearch])

  const mappedDetails = useMemo(() => {
    if (!lead) {
      return []
    }
    return [
      ['Возраст', lead.age ? String(lead.age) : null],
      ['Страна', lead.country],
      ['Карта', lead.has_card === null ? null : lead.has_card ? 'Есть' : 'Нет'],
      ...customFieldEntries(lead.custom_fields),
    ].filter(([, value]) => Boolean(value))
  }, [lead])

  const attributionDetails = useMemo(
    () => attributionEntries(lead?.custom_fields),
    [lead?.custom_fields],
  )
  const startAmount = useMemo(
    () => expectedStartAmount(lead?.custom_fields),
    [lead?.custom_fields],
  )

  const loadStatuses = useCallback(async () => {
    const { data } = await api.get<LeadStatus[]>('/leads/statuses')
    setStatuses(data)
  }, [])

  const loadUsers = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<User>>('/users', {
      params: {
        limit: 100,
        offset: 0,
        ...(selectedProjectId ? { project_id: selectedProjectId } : {}),
      },
    })
    setUsers(data.items)
  }, [selectedProjectId])

  const loadTags = useCallback(async () => {
    if (!selectedProjectId) {
      setTags([])
      setSelectedTagId('')
      return
    }

    setIsTagsLoading(true)
    try {
      const { data } = await api.get<PaginatedResponse<ProjectTag>>('/tags', {
        params: {
          limit: 100,
          offset: 0,
          project_id: selectedProjectId,
        },
      })
      setTags(data.items)
      setSelectedTagId((current) =>
        current && data.items.some((tag) => tag.id === current) ? current : '',
      )
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsTagsLoading(false)
    }
  }, [selectedProjectId])

  const loadLead = useCallback(async () => {
    if (!activeChatId) {
      setLead(null)
      setFirstNameDraft('')
      setLastNameDraft('')
      setUsernameDraft('')
      setPhoneDraft('')
      setPreferredCallTimeDraft('')
      setManagerCommentDraft('')
      setManagerCommentError('')
      setError('')
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const { data } = await api.get<Lead>(`/leads/by-chat/${activeChatId}`, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setLead(data)
      setFirstNameDraft(data.first_name ?? '')
      setLastNameDraft(data.last_name ?? '')
      setUsernameDraft(data.username ?? '')
      setPhoneDraft(data.phone ?? '')
      setPreferredCallTimeDraft(data.preferred_call_time ?? data.call_time_text ?? '')
      setManagerCommentDraft(data.manager_comment ?? '')
      setManagerCommentError('')
    } catch (err) {
      setLead(null)
      setFirstNameDraft('')
      setLastNameDraft('')
      setUsernameDraft('')
      setPhoneDraft('')
      setPreferredCallTimeDraft('')
      setManagerCommentDraft('')
      setManagerCommentError('')
      setError(getErrorMessage(err))
    } finally {
      setIsLoading(false)
    }
  }, [activeChatId, selectedProjectId])

  useEffect(() => {
    loadStatuses().catch(() => undefined)
    loadUsers().catch(() => undefined)
    loadTags().catch(() => undefined)
  }, [loadStatuses, loadTags, loadUsers])

  useEffect(() => {
    void loadLead()
  }, [loadLead])

  useEffect(() => {
    if (!lead || !selectedProjectId || managerCommentDraft === (lead.manager_comment ?? '')) {
      return undefined
    }

    const timeoutId = window.setTimeout(() => {
      const saveSeq = managerCommentSaveSeqRef.current + 1
      managerCommentSaveSeqRef.current = saveSeq
      setIsSavingManagerComment(true)
      setManagerCommentError('')

      void api.patch<Lead>(
        `/leads/${lead.id}`,
        { manager_comment: managerCommentDraft.trim() || null },
        { params: { project_id: selectedProjectId } },
      )
        .then(({ data }) => {
          if (managerCommentSaveSeqRef.current === saveSeq) {
            setLead(data)
            setManagerCommentDraft(data.manager_comment ?? '')
          }
        })
        .catch((err) => {
          if (managerCommentSaveSeqRef.current === saveSeq) {
            setManagerCommentError(getErrorMessage(err, 'Не удалось сохранить комментарий.'))
          }
        })
        .finally(() => {
          if (managerCommentSaveSeqRef.current === saveSeq) {
            setIsSavingManagerComment(false)
          }
        })
    }, 650)

    return () => window.clearTimeout(timeoutId)
  }, [lead, managerCommentDraft, selectedProjectId])

  const loadFunnelControl = useCallback(async () => {
    if (!activeChatId || !selectedProjectId) {
      setFunnelControl(null)
      setSelectedReturnStepId('')
      return
    }

    setIsFunnelControlLoading(true)
    try {
      const { data } = await api.get<FunnelControl>(`/chats/${activeChatId}/funnel-control`, {
        params: { project_id: selectedProjectId },
      })
      setFunnelControl(data)
      setSelectedReturnStepId((current) => {
        if (current && data.steps.some((step) => step.id === current)) {
          return current
        }
        return data.current_step_id ?? data.steps[0]?.id ?? ''
      })
    } catch {
      setFunnelControl(null)
      setSelectedReturnStepId('')
    } finally {
      setIsFunnelControlLoading(false)
    }
  }, [activeChatId, selectedProjectId])

  useEffect(() => {
    void loadFunnelControl()
  }, [loadFunnelControl])

  const handleStatusChange = async (nextStatusId: string) => {
    if (!lead || nextStatusId === lead.status_id || isUpdatingStatus) {
      return
    }

    setIsUpdatingStatus(true)
    setError('')

    try {
      const { data } = await api.post<Lead>(`/leads/${lead.id}/status`, {
        status_id: nextStatusId,
      }, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setLead(data)
      onLeadStatusChanged?.()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsUpdatingStatus(false)
    }
  }

  const handleContactSave = async () => {
    if (!lead || !isContactDirty || isSavingContact) {
      return
    }

    setIsSavingContact(true)
    setError('')

    try {
      const username = usernameDraft.trim()
      const phone = phoneDraft.trim()
      const firstName = firstNameDraft.trim()
      const lastName = lastNameDraft.trim()
      const preferredCallTime = preferredCallTimeDraft.trim()
      const { data } = await api.post<Lead>(`/leads/${lead.id}/contact`, {
        first_name: firstName || null,
        last_name: lastName || null,
        username: username || null,
        phone: phone || null,
        preferred_call_time: preferredCallTime || null,
      }, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setLead(data)
      setFirstNameDraft(data.first_name ?? '')
      setLastNameDraft(data.last_name ?? '')
      setUsernameDraft(data.username ?? '')
      setPhoneDraft(data.phone ?? '')
      setPreferredCallTimeDraft(data.preferred_call_time ?? data.call_time_text ?? '')
      onLeadStatusChanged?.()
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось сохранить контакты лида.'))
    } finally {
      setIsSavingContact(false)
    }
  }

  const handleManagerChange = async (managerId: string | null) => {
    if (!lead || managerId === lead.manager_id || isAssigning) {
      return
    }

    setIsAssigning(true)
    setError('')

    try {
      const { data } = await api.post<Lead>(`/leads/${lead.id}/assign`, {
        manager_id: managerId,
      }, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setLead(data)
      onLeadStatusChanged?.()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsAssigning(false)
    }
  }

  const handleResumeFunnel = async () => {
    if (!activeChatId || !selectedProjectId || !selectedReturnStepId || isResumingFunnel) {
      return
    }

    setIsResumingFunnel(true)
    setError('')
    try {
      const { data } = await api.post<FunnelControl>(
        `/chats/${activeChatId}/funnel-resume`,
        { step_id: selectedReturnStepId },
        { params: { project_id: selectedProjectId } },
      )
      setFunnelControl(data)
      setSelectedReturnStepId(data.current_step_id ?? data.steps[0]?.id ?? '')
      onLeadStatusChanged?.()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsResumingFunnel(false)
    }
  }

  const handleAddTag = async () => {
    if (!lead || !selectedTagId || isTagMutating) {
      return
    }

    setIsTagMutating(true)
    setError('')

    try {
      await api.post(`/tags/leads/${lead.id}/tags/${selectedTagId}`, null, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setSelectedTagId('')
      setTagSearch('')
      await loadLead()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsTagMutating(false)
    }
  }

  const handleRemoveTag = async (tagId: string) => {
    if (!lead || isTagMutating) {
      return
    }

    setIsTagMutating(true)
    setError('')

    try {
      await api.delete(`/tags/leads/${lead.id}/tags/${tagId}`, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      await loadLead()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsTagMutating(false)
    }
  }

  const handleTagColorChange = async (tagId: string, color: string) => {
    if (!selectedProjectId || isTagMutating) {
      return
    }

    setIsTagMutating(true)
    setError('')

    try {
      const { data } = await api.patch<ProjectTag>(
        `/projects/${selectedProjectId}/tags/${tagId}`,
        { color },
      )
      setTags((current) => current.map((tag) => (tag.id === tagId ? data : tag)))
      setLead((current) =>
        current
          ? {
              ...current,
              tags: (current.tags ?? []).map((tag) =>
                tag.id === tagId ? { ...tag, color: data.color } : tag,
              ),
            }
          : current,
      )
      setEditingTagColorId(null)
      onLeadStatusChanged?.()
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsTagMutating(false)
    }
  }

  const handleCopy = async (key: string, value: string | null | undefined) => {
    if (!value) {
      return
    }

    try {
      await navigator.clipboard.writeText(value)
      setCopiedField(key)
      window.setTimeout(() => {
        setCopiedField((current) => (current === key ? null : current))
      }, 1400)
    } catch {
      setError('Не удалось скопировать значение.')
    }
  }

  return (
    <aside className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/90 shadow-card">
      <div className="flex min-h-[73px] items-center justify-between gap-3 border-b border-white/5 px-5">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-300">
            Карточка лида
          </h2>
          <p className="text-xs text-gray-500">
            {currentStatus?.name ?? activeBotName ?? 'Статус не указан'}
          </p>
        </div>
        <button
          type="button"
          title="Обновить лида"
          onClick={() => void loadLead()}
          disabled={!activeChatId || isLoading}
          className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-accent-200 hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {!activeChatId ? (
          <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] p-4 text-sm text-gray-500">
            {hasActiveScope || activeBotId
              ? 'Выберите чат, чтобы увидеть карточку лида.'
              : 'Выберите проект, чтобы загрузить чаты.'}
          </div>
        ) : null}

        {activeChatId && isLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <LoaderCircle size={16} className="animate-spin" />
            Загрузка лида
          </div>
        ) : null}

        {activeChatId && !isLoading && error ? (
          <div className="rounded-xl border border-red-400/20 bg-red-500/10 p-4 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        {lead && !isLoading ? (
          <div className="space-y-5">
            <DuplicateWarning
              leadId={lead.id}
              projectId={selectedProjectId ?? lead.project_id}
            />

            <div className="rounded-xl border border-white/5 bg-white/[0.035] p-4">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-accent-300/20 bg-accent-400/10 text-accent-200 shadow-glow-accent">
                  <UserRound size={20} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">
                    {lead.name || lead.username || 'Telegram лид'}
                  </p>
                  <p className="text-xs text-gray-500">ID лида {lead.id.slice(0, 8)}</p>
                </div>
              </div>

              <div className="mb-4 grid gap-2">
                <CopyRow
                  label="Chat ID"
                  value={lead.chat_id}
                  isCopied={copiedField === 'chat_id'}
                  onCopy={() => void handleCopy('chat_id', lead.chat_id)}
                />
                <CopyRow
                  label="Telegram ID"
                  value={lead.external_user_id ?? lead.external_chat_id ?? null}
                  isCopied={copiedField === 'telegram_id'}
                  onCopy={() => void handleCopy('telegram_id', lead.external_user_id ?? lead.external_chat_id)}
                />
              </div>

              <div className="mb-4 flex items-center gap-3 rounded-xl border border-emerald-300/20 bg-emerald-400/[0.07] px-3 py-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-300/10 text-emerald-200">
                  <WalletCards size={17} />
                </div>
                <div className="min-w-0">
                  <p className="text-xs text-emerald-100/60">Ожидаемая сумма для старта</p>
                  <p className="mt-0.5 truncate text-sm font-semibold text-emerald-50">
                    {startAmount ?? 'Не указана'}
                  </p>
                </div>
              </div>

              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Статус
                </span>
                <div className="relative">
                  <select
                    value={lead.status_id}
                    onChange={(event) => void handleStatusChange(event.target.value)}
                    disabled={isUpdatingStatus}
                    className="w-full appearance-none rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {statuses.map((status) => (
                      <option key={status.id} value={status.id}>
                        {status.name}
                      </option>
                    ))}
                  </select>
                  {isUpdatingStatus ? (
                    <LoaderCircle
                      size={16}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-gray-400"
                    />
                  ) : null}
                </div>
              </label>

              {currentStatus?.is_final ? (
                <p className="mt-3 text-xs text-amber-300">
                  Финальный статус можно исправить вручную при необходимости.
                </p>
              ) : null}
            </div>

            {attributionDetails.length > 0 ? (
              <div className="rounded-xl border border-cyan-300/15 bg-cyan-400/[0.05] p-4">
                <p className="text-sm font-medium text-cyan-100">Атрибуция трафика</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {attributionDetails.map(([key, value]) => (
                    <span key={key} className="rounded-md border border-cyan-300/15 bg-background/40 px-2 py-1 text-xs text-gray-200">
                      <span className="text-cyan-100">{key}</span>={value}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="rounded-xl border border-accent-300/15 bg-accent-400/[0.045] p-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-medium text-white">
                  <Tag size={16} className="text-accent-200" />
                  Теги
                </div>
                {isTagsLoading ? (
                  <LoaderCircle size={15} className="animate-spin text-gray-400" />
                ) : null}
              </div>
              {lead.tags && lead.tags.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {lead.tags.map((tag) => (
                    <span key={tag.id} className="relative inline-flex">
                      <button
                        type="button"
                        onClick={() =>
                          setEditingTagColorId((current) => (current === tag.id ? null : tag.id))
                        }
                        disabled={isTagMutating}
                        className="inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-medium transition hover:brightness-125 disabled:cursor-not-allowed disabled:opacity-50"
                        style={tagStyle(tag.color)}
                        title="Изменить цвет тега"
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full border border-white/30"
                          style={{ backgroundColor: tag.color }}
                        />
                        <span className="max-w-[120px] truncate">{tag.name}</span>
                        <Palette size={12} className="opacity-70" />
                      </button>
                      <button
                        type="button"
                        title="Убрать тег"
                        onClick={() => void handleRemoveTag(tag.id)}
                        disabled={isTagMutating}
                        className="-ml-1 inline-flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-background/90 text-gray-300 transition hover:border-red-300/40 hover:text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <X size={12} />
                      </button>
                      {editingTagColorId === tag.id ? (
                        <div className="absolute left-0 top-full z-20 mt-2 grid w-40 grid-cols-6 gap-1 rounded-xl border border-white/10 bg-[#0B0F19]/95 p-2 shadow-card backdrop-blur-xl">
                          {TAG_COLOR_PALETTE.map((color) => (
                            <button
                              key={color}
                              type="button"
                              title={color}
                              onClick={() => void handleTagColorChange(tag.id, color)}
                              className="h-5 w-5 rounded-full border border-white/20 transition hover:scale-110"
                              style={{ backgroundColor: color }}
                            />
                          ))}
                        </div>
                      ) : null}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">Тегов пока нет.</p>
              )}

              <div className="mt-4 grid gap-2">
                <div className="rounded-xl border border-white/10 bg-background/70 p-2">
                  <label className="relative block">
                    <Search
                      size={14}
                      className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500"
                    />
                    <input
                      value={tagSearch}
                      onChange={(event) => {
                        setTagSearch(event.target.value)
                        setSelectedTagId('')
                      }}
                      disabled={isTagsLoading || isTagMutating || availableTags.length === 0}
                      placeholder={
                        isTagsLoading
                          ? 'Загрузка тегов...'
                          : availableTags.length === 0
                            ? 'Нет доступных тегов'
                            : 'Найти тег'
                      }
                      className="h-9 w-full rounded-lg border border-white/8 bg-white/[0.03] pl-8 pr-3 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50"
                    />
                  </label>
                  <div className="mt-2 max-h-44 overflow-y-auto pr-1">
                    {filteredAvailableTags.length > 0 ? (
                      <div className="space-y-1">
                        {filteredAvailableTags.map((tag) => {
                          const isSelected = selectedTagId === tag.id
                          return (
                            <button
                              key={tag.id}
                              type="button"
                              onClick={() => setSelectedTagId(isSelected ? '' : tag.id)}
                              disabled={isTagsLoading || isTagMutating}
                              className={`flex min-h-9 w-full items-center rounded-lg px-3 text-left text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
                                isSelected
                                  ? 'bg-accent-300/15 text-accent-50'
                                  : 'text-gray-300 hover:bg-white/[0.05] hover:text-white'
                              }`}
                            >
                              <span
                                className="mr-2 h-2.5 w-2.5 shrink-0 rounded-full border border-white/25"
                                style={{ backgroundColor: tag.color }}
                              />
                              <span className="truncate">{tag.name}</span>
                            </button>
                          )
                        })}
                      </div>
                    ) : (
                      <p className="px-2 py-3 text-xs text-gray-500">
                        {availableTags.length === 0 ? 'Нет доступных тегов' : 'Теги не найдены'}
                      </p>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void handleAddTag()}
                  disabled={!selectedTagId || isTagMutating}
                  className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-accent-300/25 bg-accent-300/10 px-3 text-sm font-medium text-accent-50 transition hover:border-accent-300/50 hover:bg-accent-300/15 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isTagMutating ? (
                    <LoaderCircle size={15} className="animate-spin" />
                  ) : (
                    <Plus size={15} />
                  )}
                  Добавить тег
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-white">Менеджер</p>
                  <p className="text-xs text-gray-500">
                    {assignedManager?.name ?? 'Не назначен'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void handleManagerChange(currentUserId)}
                  disabled={!currentUserId || isAssigning || lead.manager_id === currentUserId}
                  className="rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-3 py-2 text-xs font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Взять себе
                </button>
              </div>
              {currentUserRole === 'manager' ? (
                <p className="text-xs leading-5 text-gray-500">
                  Менеджер может взять диалог только себе. Взятый диалог ставит сценарий на паузу.
                </p>
              ) : (
                <div className="relative">
                  <select
                    value={lead.manager_id ?? ''}
                    onChange={(event) => {
                      const nextValue = event.target.value
                      void handleManagerChange(nextValue || null)
                    }}
                    disabled={isAssigning}
                    className="w-full appearance-none rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60 md:text-sm"
                  >
                    <option value="">Без менеджера</option>
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.name} ({user.email})
                      </option>
                    ))}
                  </select>
                  {isAssigning ? (
                    <LoaderCircle
                      size={16}
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-gray-400"
                    />
                  ) : null}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <label className="text-sm font-medium text-white" htmlFor="lead-manager-comment">
                  Комментарий для партнера
                </label>
                {isSavingManagerComment ? (
                  <span className="inline-flex items-center gap-1.5 text-xs text-cyan-100">
                    <LoaderCircle size={12} className="animate-spin" />
                    Сохраняю
                  </span>
                ) : null}
              </div>
              <textarea
                id="lead-manager-comment"
                value={managerCommentDraft}
                onChange={(event) => setManagerCommentDraft(event.target.value)}
                maxLength={5000}
                rows={4}
                className="touch-scroll min-h-28 w-full resize-y rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                placeholder="Например: что уточнить партнеру, важные детали по лиду"
              />
              {managerCommentError ? (
                <p className="mt-2 text-xs leading-5 text-red-200">{managerCommentError}</p>
              ) : (
                <p className="mt-2 text-xs leading-5 text-gray-500">
                  Автосохраняется и доступен в маппинге партнерских payload.
                </p>
              )}
            </div>

            {funnelControl?.is_available ? (
              <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white">Воронка</p>
                    <p className="mt-1 truncate text-xs text-gray-500">
                      {funnelControl.funnel_name || 'Активный сценарий'}
                      {funnelControl.current_step_title ? ` · ${funnelControl.current_step_title}` : ''}
                    </p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-medium ${
                    funnelControl.is_paused
                      ? 'bg-yellow-400/10 text-yellow-100'
                      : 'bg-emerald-400/10 text-emerald-100'
                  }`}>
                    {funnelControl.is_paused ? 'На паузе' : 'Активна'}
                  </span>
                </div>

                {funnelControl.is_paused ? (
                  <div className="mt-3 space-y-3">
                    <select
                      value={selectedReturnStepId}
                      onChange={(event) => setSelectedReturnStepId(event.target.value)}
                      disabled={isFunnelControlLoading || isResumingFunnel}
                      className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60 md:text-sm"
                    >
                      {funnelControl.steps.map((step) => (
                        <option key={step.id} value={step.id}>
                          {step.title}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => void handleResumeFunnel()}
                      disabled={!selectedReturnStepId || isResumingFunnel}
                      className="inline-flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border border-accent-300/25 bg-accent-300/10 px-3 py-2 text-sm font-semibold text-accent-50 transition hover:border-accent-300/50 hover:bg-accent-300/15 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isResumingFunnel ? <LoaderCircle size={16} className="animate-spin" /> : <RotateCcw size={16} />}
                      Вернуть в выбранный шаг
                    </button>
                  </div>
                ) : (
                  <p className="mt-3 text-xs leading-5 text-gray-500">
                    Сценарий продолжится автоматически. При взятии диалога менеджером он будет поставлен на паузу.
                  </p>
                )}
              </div>
            ) : null}

                <div className="space-y-3">
              <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-white">Контакты</p>
                  <button
                    type="button"
                    onClick={() => void handleContactSave()}
                    disabled={!isContactDirty || isSavingContact}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.06] px-3 py-2 text-xs font-semibold text-gray-100 transition hover:border-accent-300/45 hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isSavingContact ? (
                      <LoaderCircle size={14} className="animate-spin" />
                    ) : (
                      <Save size={14} />
                    )}
                    Сохранить
                  </button>
                </div>
	                <div className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                        <UserRound size={14} />
                        Имя
                      </span>
                      <input
                        value={firstNameDraft}
                        onChange={(event) => setFirstNameDraft(event.target.value)}
                        maxLength={255}
                        placeholder="Имя клиента"
                        className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                        <UserRound size={14} />
                        Фамилия
                      </span>
                      <input
                        value={lastNameDraft}
                        onChange={(event) => setLastNameDraft(event.target.value)}
                        maxLength={255}
                        placeholder="Фамилия клиента"
                        className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                      />
                    </label>
                  </div>

                  <label className="block">
                    <span className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                      <Clock3 size={14} />
                      Удобное время звонка
                    </span>
                    <input
                      value={preferredCallTimeDraft}
                      onChange={(event) => setPreferredCallTimeDraft(event.target.value)}
                      maxLength={255}
                      placeholder="Например: понедельник 15:00"
                      className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                    />
                  </label>

                  <label className="block">
                    <span className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                      <AtSign size={14} />
                      Username
                    </span>
                    <input
                      value={usernameDraft}
                      onChange={(event) => setUsernameDraft(event.target.value)}
                      maxLength={255}
                      placeholder="username"
                      className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                    />
                  </label>

                  <label className="block">
                    <span className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                      <Phone size={14} />
                      Телефон
                    </span>
                    <input
                      value={phoneDraft}
                      onChange={(event) => setPhoneDraft(event.target.value)}
                      maxLength={50}
                      placeholder="+1 555 0100"
                      className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                    />
                  </label>
                </div>

                {mappedDetails.length > 0 ? (
                  <div className="mt-4 rounded-xl border border-white/5 bg-background/35 p-3">
                    <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                      Данные из воронки
                    </p>
                    <div className="grid gap-2 text-sm">
                      {mappedDetails.map(([label, value]) => (
                        <div key={label} className="flex items-start justify-between gap-3">
                          <span className="text-gray-500">{label}</span>
                          <span className="max-w-[60%] break-words text-right text-gray-100">
                            {value}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>

              <div className="flex items-start gap-3 rounded-xl border border-white/5 bg-white/[0.03] p-3">
                <CalendarDays size={16} className="mt-0.5 text-gray-500" />
                <div className="min-w-0">
                  <p className="text-xs text-gray-500">Создан</p>
                  <p className="truncate text-sm text-white">
                    {formatDateTime(lead.created_at)}
                  </p>
                </div>
              </div>
            </div>

            <FunnelTraceWidget chatId={activeChatId} projectId={selectedProjectId} />

            {onSetBlocked ? (
              <div className={`rounded-xl border p-4 ${
                isChatBlocked
                  ? 'border-red-300/25 bg-red-500/[0.06]'
                  : 'border-white/5 bg-white/[0.02]'
              }`}>
                <p className="text-sm font-medium text-gray-200">Доступ к боту</p>
                <p className="mt-1 text-xs leading-5 text-gray-500">
                  {isChatBlocked
                    ? 'Клиент заблокирован в CRM: сообщения и старые кнопки не запускают сценарий бота.'
                    : 'Блокировка остановит сценарий и автоответы для этого Telegram-диалога.'}
                </p>
                <button
                  type="button"
                  onClick={() => onSetBlocked(!isChatBlocked)}
                  disabled={isUpdatingChatBlock}
                  className={`mt-3 inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
                    isChatBlocked
                      ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100 hover:border-emerald-300/45'
                      : 'border-red-300/20 bg-transparent text-red-200 hover:border-red-300/40 hover:bg-red-500/10'
                  }`}
                >
                  {isUpdatingChatBlock ? <LoaderCircle size={15} className="animate-spin" /> : isChatBlocked ? <ShieldCheck size={15} /> : <Ban size={15} />}
                  {isChatBlocked ? 'Разблокировать в CRM' : 'Заблокировать в CRM'}
                </button>
              </div>
            ) : null}

            {onResetRequest ? (
              <div className="rounded-xl border border-red-300/10 bg-red-500/[0.035] p-4">
                <p className="text-sm font-medium text-gray-200">Опасная зона</p>
                <p className="mt-1 text-xs leading-5 text-gray-500">
                  Сброс очищает текущий цикл диалога, теги и состояние воронки.
                </p>
                <button
                  type="button"
                  onClick={onResetRequest}
                  className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/20 bg-transparent px-3 text-sm text-red-200 transition hover:border-red-300/40 hover:bg-red-500/10"
                >
                  <RotateCcw size={15} />
                  Сбросить диалог
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </aside>
  )
}

function CopyRow({
  label,
  value,
  isCopied,
  onCopy,
}: {
  label: string
  value: string | null
  isCopied: boolean
  onCopy: () => void
}) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-xl border border-white/5 bg-background/45 px-3 py-2">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium uppercase text-gray-500">{label}</p>
        <p className="truncate text-xs text-gray-200">{value || 'Не указан'}</p>
      </div>
      <button
        type="button"
        onClick={onCopy}
        disabled={!value}
        title={`Скопировать ${label}`}
        className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-gray-300 transition hover:border-accent-300/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        {isCopied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  )
}

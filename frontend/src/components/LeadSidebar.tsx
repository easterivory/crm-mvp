import {
  AtSign,
  CalendarDays,
  LoaderCircle,
  Phone,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Tag,
  UserRound,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'

type Lead = {
  id: string
  project_id: string
  chat_id: string
  manager_id: string | null
  status_id: string
  name: string | null
  phone: string | null
  username: string | null
  age: number | null
  country: string | null
  call_time_text: string | null
  has_card: boolean | null
  custom_fields?: Record<string, unknown>
  updated_at: string
  created_at: string
  is_deleted: boolean
  tags?: Array<{ id: string; name: string }>
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

type ProjectTag = {
  id: string
  project_id: string
  name: string
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
  currentUserId: string | null
  onResetRequest?: () => void
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

function getErrorMessage(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.response?.status === 404) {
      return 'Лид для этого чата ещё не создан.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }

  return 'Не удалось загрузить лида.'
}

export default function LeadSidebar({
  activeBotId,
  activeBotName,
  activeChatId,
  hasActiveScope,
  currentUserId,
  onResetRequest,
}: LeadSidebarProps) {
  const { selectedProjectId } = useProjectBotSelection()
  const [lead, setLead] = useState<Lead | null>(null)
  const [statuses, setStatuses] = useState<LeadStatus[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [tags, setTags] = useState<ProjectTag[]>([])
  const [selectedTagId, setSelectedTagId] = useState('')
  const [usernameDraft, setUsernameDraft] = useState('')
  const [phoneDraft, setPhoneDraft] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSavingContact, setIsSavingContact] = useState(false)
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false)
  const [isAssigning, setIsAssigning] = useState(false)
  const [isTagsLoading, setIsTagsLoading] = useState(false)
  const [isTagMutating, setIsTagMutating] = useState(false)

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
      (usernameDraft.trim() !== (lead.username ?? '') ||
        phoneDraft.trim() !== (lead.phone ?? '')),
  )

  const availableTags = useMemo(() => {
    const attachedTagIds = new Set((lead?.tags ?? []).map((tag) => tag.id))
    return tags.filter((tag) => !attachedTagIds.has(tag.id))
  }, [lead?.tags, tags])

  const mappedDetails = useMemo(() => {
    if (!lead) {
      return []
    }
    return [
      ['Имя', lead.name],
      ['Телефон', lead.phone],
      ['Возраст', lead.age ? String(lead.age) : null],
      ['Страна', lead.country],
      ['Удобное время', lead.call_time_text],
      ['Карта', lead.has_card === null ? null : lead.has_card ? 'Есть' : 'Нет'],
    ].filter(([, value]) => Boolean(value))
  }, [lead])

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
      setUsernameDraft('')
      setPhoneDraft('')
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
      setUsernameDraft(data.username ?? '')
      setPhoneDraft(data.phone ?? '')
    } catch (err) {
      setLead(null)
      setUsernameDraft('')
      setPhoneDraft('')
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
      const { data } = await api.patch<Lead>(`/leads/${lead.id}`, {
        username: username || null,
        phone: phone || null,
      }, {
        params: selectedProjectId ? { project_id: selectedProjectId } : undefined,
      })
      setLead(data)
      setUsernameDraft(data.username ?? '')
      setPhoneDraft(data.phone ?? '')
    } catch (err) {
      setError(getErrorMessage(err))
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
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsAssigning(false)
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
            <div className="rounded-xl border border-white/5 bg-white/[0.035] p-4">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-accent-300/20 bg-accent-400/10 text-accent-200 shadow-glow-accent">
                  <UserRound size={20} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-white">
                    {lead.username ? `@${lead.username}` : 'Telegram лид'}
                  </p>
                  <p className="text-xs text-gray-500">ID лида {lead.id.slice(0, 8)}</p>
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
                    disabled={isUpdatingStatus || currentStatus?.is_final}
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
                  Этот лид находится в финальном статусе.
                </p>
              ) : null}
            </div>

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
                    <span
                      key={tag.id}
                      className="inline-flex items-center gap-1 rounded-full border border-accent-300/20 bg-accent-300/10 px-2 py-1 text-xs font-medium text-accent-50"
                    >
                      {tag.name}
                      <button
                        type="button"
                        title="Убрать тег"
                        onClick={() => void handleRemoveTag(tag.id)}
                        disabled={isTagMutating}
                        className="rounded-full text-accent-50/70 transition hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <X size={12} />
                      </button>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">Тегов пока нет.</p>
              )}

              <div className="mt-4 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] xl:grid-cols-1 2xl:grid-cols-[minmax(0,1fr)_auto]">
                <select
                  value={selectedTagId}
                  onChange={(event) => setSelectedTagId(event.target.value)}
                  disabled={isTagsLoading || isTagMutating || availableTags.length === 0}
                  className="min-w-0 rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <option value="">
                    {isTagsLoading
                      ? 'Загрузка тегов...'
                      : availableTags.length === 0
                        ? 'Нет доступных тегов'
                        : 'Выберите тег'}
                  </option>
                  {availableTags.map((tag) => (
                    <option key={tag.id} value={tag.id}>
                      {tag.name}
                    </option>
                  ))}
                </select>
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
              <div className="relative">
                <select
                  value={lead.manager_id ?? ''}
                  onChange={(event) => {
                    const nextValue = event.target.value
                    void handleManagerChange(nextValue || null)
                  }}
                  disabled={isAssigning}
                  className="w-full appearance-none rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
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
            </div>

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
                  <label className="block">
                    <span className="mb-1 flex items-center gap-2 text-xs text-gray-500">
                      <UserRound size={14} />
                      Имя
                    </span>
                    <input
                      value={lead.name ?? ''}
                      disabled
                      placeholder="Будет заполнено из воронки"
                      className="w-full rounded-xl border border-white/10 bg-background/40 px-3 py-2 text-sm text-gray-400 outline-none placeholder:text-gray-600"
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

import {
  AtSign,
  CalendarDays,
  LoaderCircle,
  Phone,
  RefreshCw,
  Save,
  Tag,
  UserRound,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import api from '../api/client'

type Lead = {
  id: string
  project_id: string
  chat_id: string
  manager_id: string | null
  status_id: string
  phone: string | null
  username: string | null
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
  currentUserId: string | null
}

function formatDateTime(value: string | null) {
  if (!value) {
    return 'No activity'
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
      return 'Lead was not created for this chat yet.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Cannot reach API.'
    }
  }

  return 'Could not load lead.'
}

export default function LeadSidebar({
  activeBotId,
  activeBotName,
  activeChatId,
  currentUserId,
}: LeadSidebarProps) {
  const [lead, setLead] = useState<Lead | null>(null)
  const [statuses, setStatuses] = useState<LeadStatus[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [usernameDraft, setUsernameDraft] = useState('')
  const [phoneDraft, setPhoneDraft] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSavingContact, setIsSavingContact] = useState(false)
  const [isUpdatingStatus, setIsUpdatingStatus] = useState(false)
  const [isAssigning, setIsAssigning] = useState(false)

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

  const loadStatuses = useCallback(async () => {
    const { data } = await api.get<LeadStatus[]>('/leads/statuses')
    setStatuses(data)
  }, [])

  const loadUsers = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<User>>('/users', {
      params: { limit: 100, offset: 0 },
    })
    setUsers(data.items)
  }, [])

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
      const { data } = await api.get<Lead>(`/leads/by-chat/${activeChatId}`)
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
  }, [activeChatId])

  useEffect(() => {
    loadStatuses().catch(() => undefined)
    loadUsers().catch(() => undefined)
  }, [loadStatuses, loadUsers])

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
      })
      setLead(data)
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setIsAssigning(false)
    }
  }

  return (
    <aside className="flex min-h-[420px] min-w-0 flex-col border-t border-zinc-800 bg-zinc-950 xl:min-h-0 xl:border-l xl:border-t-0">
      <div className="flex min-h-[73px] items-center justify-between gap-3 border-b border-zinc-800 px-5">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-300">
            Lead Card
          </h2>
          <p className="text-xs text-zinc-500">
            {currentStatus?.name ?? activeBotName ?? 'No status'}
          </p>
        </div>
        <button
          type="button"
          title="Refresh lead"
          onClick={() => void loadLead()}
          disabled={!activeChatId || isLoading}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 text-zinc-300 transition hover:bg-zinc-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {!activeChatId ? (
          <div className="rounded-lg border border-dashed border-zinc-800 p-4 text-sm text-zinc-500">
            {activeBotId
              ? 'Select a chat to view lead details.'
              : 'Select a bot to load its chats.'}
          </div>
        ) : null}

        {activeChatId && isLoading ? (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <LoaderCircle size={16} className="animate-spin" />
            Loading lead
          </div>
        ) : null}

        {activeChatId && !isLoading && error ? (
          <div className="rounded-lg border border-red-900/70 bg-red-950/40 p-4 text-sm text-red-200">
            {error}
          </div>
        ) : null}

        {lead && !isLoading ? (
          <div className="space-y-5">
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 p-4">
              <div className="mb-4 flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-300">
                  <UserRound size={20} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-zinc-100">
                    {lead.username ? `@${lead.username}` : 'Telegram lead'}
                  </p>
                  <p className="text-xs text-zinc-500">Lead ID {lead.id.slice(0, 8)}</p>
                </div>
              </div>

              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                  Status
                </span>
                <div className="relative">
                  <select
                    value={lead.status_id}
                    onChange={(event) => void handleStatusChange(event.target.value)}
                    disabled={isUpdatingStatus || currentStatus?.is_final}
                    className="w-full appearance-none rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
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
                      className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-zinc-400"
                    />
                  ) : null}
                </div>
              </label>

              {currentStatus?.is_final ? (
                <p className="mt-3 text-xs text-amber-300">
                  This lead is in a final status.
                </p>
              ) : null}
            </div>

            <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-zinc-100">Менеджер</p>
                  <p className="text-xs text-zinc-500">
                    {assignedManager?.name ?? 'Не назначен'}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void handleManagerChange(currentUserId)}
                  disabled={!currentUserId || isAssigning || lead.manager_id === currentUserId}
                  className="rounded-lg bg-emerald-500 px-3 py-2 text-xs font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
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
                  className="w-full appearance-none rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
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
                    className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-zinc-400"
                  />
                ) : null}
              </div>
            </div>

            <div className="space-y-3">
              <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-zinc-100">Контакты</p>
                  <button
                    type="button"
                    onClick={() => void handleContactSave()}
                    disabled={!isContactDirty || isSavingContact}
                    className="inline-flex items-center gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-xs font-semibold text-zinc-950 transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-50"
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
                    <span className="mb-1 flex items-center gap-2 text-xs text-zinc-500">
                      <AtSign size={14} />
                      Username
                    </span>
                    <input
                      value={usernameDraft}
                      onChange={(event) => setUsernameDraft(event.target.value)}
                      maxLength={255}
                      placeholder="username"
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                    />
                  </label>

                  <label className="block">
                    <span className="mb-1 flex items-center gap-2 text-xs text-zinc-500">
                      <Phone size={14} />
                      Phone
                    </span>
                    <input
                      value={phoneDraft}
                      onChange={(event) => setPhoneDraft(event.target.value)}
                      maxLength={50}
                      placeholder="+1 555 0100"
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                    />
                  </label>
                </div>
              </div>

              <div className="flex items-start gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
                <CalendarDays size={16} className="mt-0.5 text-zinc-500" />
                <div className="min-w-0">
                  <p className="text-xs text-zinc-500">Created</p>
                  <p className="truncate text-sm text-zinc-100">
                    {formatDateTime(lead.created_at)}
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-zinc-100">
                <Tag size={16} className="text-zinc-500" />
                Tags
              </div>
              {lead.tags && lead.tags.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {lead.tags.map((tag) => (
                    <span
                      key={tag.id}
                      className="rounded bg-zinc-800 px-2 py-1 text-xs font-medium text-zinc-200"
                    >
                      {tag.name}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-zinc-500">No tags yet.</p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  )
}

import { Filter, LoaderCircle, RefreshCw, Search, Tag, Trash2, UsersRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'

import api from '../api/client'
import LeadCard from '../features/leads/components/LeadCard'
import {
  fetchLeads,
  fetchLeadStatuses,
  restoreLead,
  trashLead,
  type Lead,
  type LeadStatus,
} from '../features/leads'
import { fetchPartnerIntegrations, LeadSubmissionDrawer, type PartnerIntegration } from '../features/partners'
import { useProjectBotSelection } from '../shared/lib'
import type { PaginatedResponse } from '../shared/types'
import { ConfirmDialog, EmptyState } from '../shared/ui'

type ProjectTag = {
  id: string
  project_id: string
  name: string
  created_at: string
}

type PendingAction = { type: 'trash'; lead: Lead } | null
type LeadTab = 'active' | 'trash'

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoIso(days: number) {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString().slice(0, 10)
}

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.response?.status === 403) {
      return 'Недостаточно прав для этого действия.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен. Проверьте backend.'
    }
  }

  return fallback
}

function parseOptionalNumber(value: string) {
  const normalized = value.trim()
  if (!normalized) {
    return undefined
  }
  const parsed = Number.parseInt(normalized, 10)
  return Number.isFinite(parsed) ? parsed : undefined
}

export default function LeadsPage() {
  const navigate = useNavigate()
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const [leads, setLeads] = useState<Lead[]>([])
  const [statuses, setStatuses] = useState<LeadStatus[]>([])
  const [tags, setTags] = useState<ProjectTag[]>([])
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState<LeadTab>('active')
  const [isFiltersOpen, setIsFiltersOpen] = useState(false)
  const [partnerFilter, setPartnerFilter] = useState('')
  const [ageFrom, setAgeFrom] = useState('')
  const [ageTo, setAgeTo] = useState('')
  const [countryFilter, setCountryFilter] = useState('')
  const [dateFrom, setDateFrom] = useState(daysAgoIso(30))
  const [dateTo, setDateTo] = useState(todayIso())
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [pendingAction, setPendingAction] = useState<PendingAction>(null)
  const [partnerLead, setPartnerLead] = useState<Lead | null>(null)
  const [partners, setPartners] = useState<PartnerIntegration[]>([])
  const [selectedPartnerId, setSelectedPartnerId] = useState('')
  const [mutatingLeadId, setMutatingLeadId] = useState<string | null>(null)

  const activeLeadCount = useMemo(
    () =>
      leads.filter((lead) => !['lost', 'rejected'].includes(lead.status_code ?? ''))
        .length,
    [leads],
  )

  const isTrashTab = activeTab === 'trash'

  const loadTags = useCallback(async () => {
    if (!selectedProjectId) {
      setTags([])
      return
    }

    const { data } = await api.get<PaginatedResponse<ProjectTag>>('/tags', {
      params: { project_id: selectedProjectId, limit: 100, offset: 0 },
    })
    setTags(data.items)
  }, [selectedProjectId])

  const loadPage = useCallback(async () => {
    if (!selectedProjectId) {
      setLeads([])
      setTotal(0)
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const [leadResponse, statusItems] = await Promise.all([
        fetchLeads({
          project_id: selectedProjectId,
          bot_ids: selectedBotIds,
          status: statusFilter,
          tag_ids: tagFilter ? [tagFilter] : [],
          date_from: dateFrom,
          date_to: dateTo,
          q: search,
          is_trash: isTrashTab,
          partner_id: partnerFilter || undefined,
          age_from: parseOptionalNumber(ageFrom),
          age_to: parseOptionalNumber(ageTo),
          country: countryFilter,
          limit: 100,
          offset: 0,
        }),
        fetchLeadStatuses(),
        loadTags(),
      ])
      setLeads(leadResponse.items)
      setTotal(leadResponse.total)
      setStatuses(statusItems)
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось загрузить лиды.'))
    } finally {
      setIsLoading(false)
    }
  }, [
    ageFrom,
    ageTo,
    countryFilter,
    dateFrom,
    dateTo,
    isTrashTab,
    loadTags,
    partnerFilter,
    search,
    selectedBotIds,
    selectedProjectId,
    statusFilter,
    tagFilter,
  ])

  const loadPartners = useCallback(async () => {
    if (!selectedProjectId) {
      setPartners([])
      return
    }
    try {
      const response = await fetchPartnerIntegrations(selectedProjectId)
      const activeItems = response.items.filter((item) => item.is_active)
      setPartners(activeItems)
      setSelectedPartnerId((current) =>
        activeItems.some((item) => item.id === current) ? current : activeItems[0]?.id || '',
      )
    } catch {
      setPartners([])
    }
  }, [selectedProjectId])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  useEffect(() => {
    void loadPartners()
  }, [loadPartners])

  const handleConfirmAction = async () => {
    if (!pendingAction || !selectedProjectId || mutatingLeadId) {
      return
    }

    setMutatingLeadId(pendingAction.lead.id)
    setError('')
    setNotice('')

    try {
      await trashLead(pendingAction.lead.id, selectedProjectId)
      setNotice('Лид перемещён в корзину.')

      setPendingAction(null)
      setLeads((items) => items.filter((item) => item.id !== pendingAction.lead.id))
      setTotal((value) => Math.max(0, value - 1))
    } catch (err) {
      setError(getErrorMessage(err))
    } finally {
      setMutatingLeadId(null)
    }
  }

  const openLeadChat = (lead: Lead) => {
    navigate(`/chats?chat_id=${encodeURIComponent(lead.chat_id)}`)
  }

  const handleRestore = async (lead: Lead) => {
    if (!selectedProjectId || mutatingLeadId) {
      return
    }

    setMutatingLeadId(lead.id)
    setError('')
    setNotice('')

    try {
      await restoreLead(lead.id, selectedProjectId)
      setNotice('Лид восстановлен.')
      setLeads((items) => items.filter((item) => item.id !== lead.id))
      setTotal((value) => Math.max(0, value - 1))
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось восстановить лида.'))
    } finally {
      setMutatingLeadId(null)
    }
  }

  if (!selectedProjectId) {
    return (
      <section className="flex h-full min-h-0 items-center justify-center overflow-y-auto rounded-xl border border-white/5 bg-surface p-6 text-center shadow-card">
        <div>
          <UsersRound className="mx-auto text-accent-300" size={36} />
          <h1 className="mt-4 text-xl font-semibold text-white">Выберите проект</h1>
          <p className="mt-2 text-sm text-gray-500">
            Лиды показываются в рамках выбранного проекта.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0B0F19]/80 text-gray-200 shadow-card">
      <header className="shrink-0 border-b border-white/5 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.25em] text-accent-300/70">
              Лиды
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-white">Карточки лидов</h1>
            <p className="mt-1 text-sm text-gray-500">
              {isTrashTab ? `${total} в корзине` : statusFilter ? `${total} найдено` : `${activeLeadCount} активных`}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveTab('active')}
              className={`inline-flex h-10 items-center justify-center rounded-xl border px-4 text-sm font-semibold transition ${
                !isTrashTab
                  ? 'border-accent-300/50 bg-accent-500/15 text-accent-100'
                  : 'border-white/10 bg-white/[0.04] text-gray-300 hover:border-white/20'
              }`}
            >
              Активные лиды
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('trash')}
              className={`inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
                isTrashTab
                  ? 'border-amber-300/50 bg-amber-500/15 text-amber-100'
                  : 'border-white/10 bg-white/[0.04] text-gray-300 hover:border-white/20'
              }`}
            >
              <Trash2 size={15} />
              Корзина / Треш
            </button>
            <button
              type="button"
              title="Фильтры"
              onClick={() => setIsFiltersOpen((value) => !value)}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-medium text-gray-200 transition hover:border-accent-300/50 hover:text-white"
            >
              <Filter size={16} />
              Фильтры
            </button>
            <button
              type="button"
              onClick={() => void loadPage()}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-medium text-gray-200 transition hover:border-accent-300/50 hover:text-white"
            >
              {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
              Обновить
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(220px,1fr)_180px_180px_180px_180px]">
          <label className="relative block min-w-0">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по имени, username или телефону"
              className="h-10 w-full rounded-xl border border-white/10 bg-white/[0.04] pl-10 pr-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/60"
            />
          </label>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          >
            <option value="">Активные статусы</option>
            {statuses.map((status) => (
              <option key={status.id} value={status.code}>
                {status.name}
              </option>
            ))}
          </select>
          <select
            value={tagFilter}
            onChange={(event) => setTagFilter(event.target.value)}
            className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          >
            <option value="">Все теги</option>
            {tags.map((tag) => (
              <option key={tag.id} value={tag.id}>
                {tag.name}
              </option>
            ))}
          </select>
          <input
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          />
        </div>

        {isFiltersOpen ? (
          <div className="mt-3 grid gap-3 rounded-xl border border-white/5 bg-white/[0.025] p-3 md:grid-cols-2 xl:grid-cols-4">
            <select
              value={partnerFilter}
              onChange={(event) => setPartnerFilter(event.target.value)}
              className="h-10 rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
            >
              <option value="">Все партнёры</option>
              {partners.map((partner) => (
                <option key={partner.id} value={partner.id}>
                  {partner.name}
                </option>
              ))}
            </select>
            <input
              type="number"
              min={0}
              max={150}
              value={ageFrom}
              onChange={(event) => setAgeFrom(event.target.value)}
              placeholder="Возраст от"
              className="h-10 rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/60"
            />
            <input
              type="number"
              min={0}
              max={150}
              value={ageTo}
              onChange={(event) => setAgeTo(event.target.value)}
              placeholder="Возраст до"
              className="h-10 rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/60"
            />
            <input
              value={countryFilter}
              onChange={(event) => setCountryFilter(event.target.value)}
              placeholder="Страна"
              className="h-10 rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/60"
            />
          </div>
        ) : null}
      </header>

      {error ? (
        <div className="border-b border-red-400/20 bg-red-500/10 px-5 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="border-b border-accent-400/20 bg-accent-500/10 px-5 py-3 text-sm text-accent-100">
          {notice}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
        {isLoading ? (
          <div className="flex items-center justify-center rounded-xl border border-white/5 bg-surface px-4 py-16 text-sm text-gray-500">
            <LoaderCircle size={18} className="mr-2 animate-spin" />
            Загрузка лидов
          </div>
        ) : null}

        {!isLoading && leads.length === 0 ? (
          <EmptyState
            icon={<Tag size={30} />}
            title={isTrashTab ? 'Корзина пуста' : 'Лидов пока нет'}
            description={isTrashTab ? 'Здесь появятся лиды, перемещённые в корзину.' : 'Попробуйте изменить фильтры или дождаться новых обращений из Telegram.'}
          />
        ) : null}

        {!isLoading && leads.length > 0 ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {leads.map((lead) => (
              <LeadCard
                key={lead.id}
                lead={lead}
                projectId={selectedProjectId}
                isMutating={mutatingLeadId === lead.id}
                isTrashView={isTrashTab}
                onTrash={(item) => setPendingAction({ type: 'trash', lead: item })}
                onRestore={(item) => void handleRestore(item)}
                onOpenChat={isTrashTab ? undefined : openLeadChat}
                onSubmitToPartner={!isTrashTab && partners.length > 0 ? (item) => setPartnerLead(item) : undefined}
              />
            ))}
          </div>
        ) : null}
      </div>

      {pendingAction ? (
        <ConfirmDialog
          title="Переместить лида в корзину?"
          description="Лид исчезнет из активных карточек, но останется доступен во вкладке «Корзина / Треш»."
          confirmLabel="В корзину"
          tone="danger"
          isLoading={mutatingLeadId === pendingAction.lead.id}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => void handleConfirmAction()}
        />
      ) : null}

      {partnerLead ? (
        <LeadSubmissionDrawer
          lead={partnerLead}
          partners={partners}
          projectId={selectedProjectId}
          initialPartnerId={selectedPartnerId}
          onClose={() => setPartnerLead(null)}
          onSubmitted={() => {
            setNotice('Лид обработан postback-воркером.')
            void loadPage()
          }}
        />
      ) : null}
    </section>
  )
}

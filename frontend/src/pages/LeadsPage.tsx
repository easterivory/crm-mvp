import { CheckCircle2, Filter, LoaderCircle, RefreshCw, Search, Settings2, Tag, Trash2, UsersRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { useNavigate } from 'react-router-dom'

import api from '../api/client'
import LeadCard, {
  DEFAULT_LEAD_CARD_FIELDS,
  LEAD_CARD_FIELD_OPTIONS,
  leadCustomFieldEntries,
} from '../features/leads/components/LeadCard'
import {
  fetchLeads,
  fetchLeadStatuses,
  restoreLead,
  trashLead,
  updateLead,
  type Lead,
  type LeadStatus,
} from '../features/leads'
import { fetchPartnerIntegrations, LeadSubmissionDrawer, type PartnerIntegration } from '../features/partners'
import { useProjectBotSelection } from '../shared/lib'
import type { PaginatedResponse } from '../shared/types'
import { ConfirmDialog, EmptyState, Modal } from '../shared/ui'
import { useAuthStore } from '../store/authStore'

type ProjectTag = {
  id: string
  project_id: string
  name: string
  created_at: string
}

type FunnelStepOption = {
  id: string
  title: string
  funnel_name: string
  version_number: number
}

type PendingAction = { type: 'trash'; lead: Lead } | null
type LeadTab = 'active' | 'submitted' | 'trash'

type LeadEditDraft = {
  firstName: string
  lastName: string
  username: string
  phone: string
  age: string
  country: string
  preferredCallTime: string
  hasCard: '' | 'yes' | 'no'
}

const LEAD_CARD_FIELDS_STORAGE_KEY = 'crm:lead-card-fields'

function leadCardFieldsStorageKey(projectId: string, userId: string) {
  return `${LEAD_CARD_FIELDS_STORAGE_KEY}:${userId}:${projectId}`
}

function readLeadCardFields(projectId: string, userId: string) {
  try {
    const stored = JSON.parse(
      localStorage.getItem(leadCardFieldsStorageKey(projectId, userId)) || 'null',
    )
    if (Array.isArray(stored) && stored.every((item) => typeof item === 'string')) {
      return stored as string[]
    }
  } catch {
    // Ignore malformed preferences and restore the production defaults.
  }
  return [...DEFAULT_LEAD_CARD_FIELDS]
}

function editDraftFromLead(lead: Lead): LeadEditDraft {
  return {
    firstName: lead.first_name ?? '',
    lastName: lead.last_name ?? '',
    username: lead.username ?? '',
    phone: lead.phone ?? '',
    age: lead.age === null ? '' : String(lead.age),
    country: lead.country ?? '',
    preferredCallTime: lead.preferred_call_time ?? lead.call_time_text ?? '',
    hasCard: lead.has_card === null ? '' : lead.has_card ? 'yes' : 'no',
  }
}

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
  const currentUserId = useAuthStore((state) => state.user?.id ?? 'anonymous')
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
  const [currentStepFilter, setCurrentStepFilter] = useState('')
  const [stepOptions, setStepOptions] = useState<FunnelStepOption[]>([])
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
  const [isCardSettingsOpen, setIsCardSettingsOpen] = useState(false)
  const [cardFields, setCardFields] = useState<string[]>([...DEFAULT_LEAD_CARD_FIELDS])
  const [draftCardFields, setDraftCardFields] = useState<string[]>([...DEFAULT_LEAD_CARD_FIELDS])
  const [editingLead, setEditingLead] = useState<Lead | null>(null)
  const [editDraft, setEditDraft] = useState<LeadEditDraft | null>(null)
  const [editError, setEditError] = useState('')
  const [isSavingLead, setIsSavingLead] = useState(false)

  const isTrashTab = activeTab === 'trash'
  const isSubmittedTab = activeTab === 'submitted'
  const customFieldOptions = useMemo(() => {
    const labels = new Map<string, string>()
    for (const lead of leads) {
      for (const field of leadCustomFieldEntries(lead.custom_fields)) {
        labels.set(field.key, field.label)
      }
    }
    return [...labels.entries()].sort((left, right) => left[1].localeCompare(right[1], 'ru'))
  }, [leads])

  useEffect(() => {
    if (!selectedProjectId) {
      return
    }
    const storedFields = readLeadCardFields(selectedProjectId, currentUserId)
    setCardFields(storedFields)
    setDraftCardFields(storedFields)
  }, [currentUserId, selectedProjectId])

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
          submission_state: isTrashTab ? undefined : isSubmittedTab ? 'submitted' : 'active',
          funnel_completed: activeTab === 'active' && !currentStepFilter,
          partner_id: partnerFilter || undefined,
          age_from: parseOptionalNumber(ageFrom),
          age_to: parseOptionalNumber(ageTo),
          country: countryFilter,
          current_step_id: currentStepFilter || undefined,
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
    currentStepFilter,
    dateFrom,
    dateTo,
    isTrashTab,
    isSubmittedTab,
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

  const loadStepOptions = useCallback(async () => {
    if (!selectedProjectId) {
      setStepOptions([])
      setCurrentStepFilter('')
      return
    }
    try {
      const { data } = await api.get<FunnelStepOption[]>('/funnels/step-options', {
        params: { project_id: selectedProjectId },
      })
      setStepOptions(data)
      setCurrentStepFilter((current) => data.some((step) => step.id === current) ? current : '')
    } catch {
      setStepOptions([])
    }
  }, [selectedProjectId])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  useEffect(() => {
    void loadPartners()
  }, [loadPartners])

  useEffect(() => {
    void loadStepOptions()
  }, [loadStepOptions])

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

  const openCardSettings = () => {
    setDraftCardFields(cardFields)
    setIsCardSettingsOpen(true)
  }

  const saveCardSettings = () => {
    if (!selectedProjectId) {
      return
    }
    localStorage.setItem(
      leadCardFieldsStorageKey(selectedProjectId, currentUserId),
      JSON.stringify(draftCardFields),
    )
    setCardFields(draftCardFields)
    setIsCardSettingsOpen(false)
    setNotice('Состав карточки сохранён для этого проекта.')
  }

  const toggleCardField = (fieldId: string) => {
    setDraftCardFields((current) =>
      current.includes(fieldId)
        ? current.filter((item) => item !== fieldId)
        : [...current, fieldId],
    )
  }

  const openLeadEdit = (lead: Lead) => {
    setEditingLead(lead)
    setEditDraft(editDraftFromLead(lead))
    setEditError('')
  }

  const handleLeadUpdated = useCallback((updated: Lead) => {
    setLeads((items) => items.map((item) => (item.id === updated.id ? updated : item)))
  }, [])

  const saveLeadEdit = async () => {
    if (!editingLead || !editDraft || !selectedProjectId || isSavingLead) {
      return
    }
    const age = editDraft.age.trim() ? Number(editDraft.age) : null
    if (age !== null && (!Number.isInteger(age) || age < 0 || age > 150)) {
      setEditError('Возраст должен быть целым числом от 0 до 150.')
      return
    }
    setIsSavingLead(true)
    setEditError('')
    try {
      const updated = await updateLead(editingLead.id, selectedProjectId, {
        first_name: editDraft.firstName.trim() || null,
        last_name: editDraft.lastName.trim() || null,
        username: editDraft.username.trim() || null,
        phone: editDraft.phone.trim() || null,
        age,
        country: editDraft.country.trim() || null,
        preferred_call_time: editDraft.preferredCallTime.trim() || null,
        has_card: editDraft.hasCard === '' ? null : editDraft.hasCard === 'yes',
      })
      setLeads((items) => items.map((item) => (item.id === updated.id ? updated : item)))
      setEditingLead(null)
      setEditDraft(null)
      setNotice('Параметры лида сохранены.')
    } catch (err) {
      setEditError(getErrorMessage(err, 'Не удалось сохранить параметры лида.'))
    } finally {
      setIsSavingLead(false)
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
              {isTrashTab
                ? `${total} в корзине`
                : isSubmittedTab
                  ? `${total} успешно подано`
                  : statusFilter
                    ? `${total} найдено`
                    : `${total} завершили воронку`}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveTab('active')}
              className={`inline-flex h-10 items-center justify-center rounded-xl border px-4 text-sm font-semibold transition ${
                activeTab === 'active'
                  ? 'border-accent-300/50 bg-accent-500/15 text-accent-100'
                  : 'border-white/10 bg-white/[0.04] text-gray-300 hover:border-white/20'
              }`}
            >
              Активные лиды
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('submitted')}
              className={`inline-flex h-10 items-center justify-center gap-2 rounded-xl border px-4 text-sm font-semibold transition ${
                isSubmittedTab
                  ? 'border-emerald-300/50 bg-emerald-500/15 text-emerald-100'
                  : 'border-white/10 bg-white/[0.04] text-gray-300 hover:border-white/20'
              }`}
            >
              <CheckCircle2 size={15} />
              Поданные
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
              title="Настроить карточки"
              onClick={openCardSettings}
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 hover:text-white"
            >
              <Settings2 size={17} />
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
            <option value="">Все статусы</option>
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
            className="crm-date-input h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          />
          <input
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
            className="crm-date-input h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          />
        </div>

        {isFiltersOpen ? (
          <div className="mt-3 grid gap-3 rounded-xl border border-white/5 bg-white/[0.025] p-3 md:grid-cols-2 xl:grid-cols-5">
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
            <select
              value={currentStepFilter}
              onChange={(event) => setCurrentStepFilter(event.target.value)}
              className="h-10 min-w-0 rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
            >
              <option value="">Все шаги воронки</option>
              {stepOptions.map((step) => (
                <option key={step.id} value={step.id}>
                  {step.funnel_name} v{step.version_number} · {step.title}
                </option>
              ))}
            </select>
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
            description={isTrashTab
              ? 'Здесь появятся лиды, перемещённые в корзину.'
              : isSubmittedTab
                ? 'Здесь появятся лиды после успешной подачи партнёру.'
                : 'Здесь появятся лиды, которые дошли до завершения воронки.'}
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
                visibleFields={cardFields}
                onLeadUpdated={handleLeadUpdated}
                onEdit={isTrashTab ? undefined : openLeadEdit}
                onTrash={(item) => setPendingAction({ type: 'trash', lead: item })}
                onRestore={(item) => void handleRestore(item)}
                onOpenChat={isTrashTab ? undefined : openLeadChat}
                onSubmitToPartner={!isTrashTab && !isSubmittedTab && partners.length > 0 ? (item) => setPartnerLead(item) : undefined}
              />
            ))}
          </div>
        ) : null}
      </div>

      {isCardSettingsOpen ? (
        <Modal
          title="Поля карточки лида"
          description="Выберите данные, которые нужны для быстрого просмотра. Настройка сохраняется отдельно для проекта."
          maxWidthClassName="max-w-lg"
          onClose={() => setIsCardSettingsOpen(false)}
        >
          <div className="grid gap-2 sm:grid-cols-2">
            {LEAD_CARD_FIELD_OPTIONS.map(([fieldId, label]) => (
              <label
                key={fieldId}
                className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border border-white/8 bg-white/[0.025] px-3 py-2 text-sm text-gray-200 transition hover:border-accent-300/30"
              >
                <input
                  type="checkbox"
                  checked={draftCardFields.includes(fieldId)}
                  onChange={() => toggleCardField(fieldId)}
                  className="h-4 w-4 accent-cyan-400"
                />
                <span>{label}</span>
              </label>
            ))}
          </div>

          {customFieldOptions.length > 0 ? (
            <div className="mt-5 border-t border-white/8 pt-4">
              <p className="text-sm font-semibold text-white">Отдельные поля воронки</p>
              <p className="mt-1 text-xs text-gray-500">
                Отключите «Все данные из воронки», чтобы выбрать только нужные поля.
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {customFieldOptions.map(([key, label]) => {
                  const fieldId = `custom:${key}`
                  const allCustomFieldsVisible = draftCardFields.includes('custom_fields')
                  return (
                    <label
                      key={fieldId}
                      className="flex min-h-11 items-center gap-3 rounded-lg border border-white/8 bg-white/[0.025] px-3 py-2 text-sm text-gray-200"
                    >
                      <input
                        type="checkbox"
                        checked={allCustomFieldsVisible || draftCardFields.includes(fieldId)}
                        disabled={allCustomFieldsVisible}
                        onChange={() => toggleCardField(fieldId)}
                        className="h-4 w-4 accent-cyan-400 disabled:opacity-40"
                      />
                      <span className="truncate">{label}</span>
                    </label>
                  )
                })}
              </div>
            </div>
          ) : null}

          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
            <button
              type="button"
              onClick={() => setDraftCardFields([...DEFAULT_LEAD_CARD_FIELDS])}
              className="min-h-11 rounded-lg border border-white/10 px-4 text-sm font-medium text-gray-300 transition hover:border-white/20 hover:text-white"
            >
              По умолчанию
            </button>
            <button
              type="button"
              onClick={saveCardSettings}
              className="min-h-11 rounded-lg bg-accent-400 px-5 text-sm font-semibold text-slate-950 transition hover:bg-accent-300"
            >
              Сохранить
            </button>
          </div>
        </Modal>
      ) : null}

      {editingLead && editDraft ? (
        <Modal
          title="Редактирование лида"
          description={editingLead.name || editingLead.username || `Лид ${editingLead.id.slice(0, 8)}`}
          maxWidthClassName="max-w-lg"
          onClose={() => {
            if (!isSavingLead) {
              setEditingLead(null)
              setEditDraft(null)
              setEditError('')
            }
          }}
        >
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              void saveLeadEdit()
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <LeadEditField label="Имя" value={editDraft.firstName} onChange={(firstName) => setEditDraft({ ...editDraft, firstName })} />
              <LeadEditField label="Фамилия" value={editDraft.lastName} onChange={(lastName) => setEditDraft({ ...editDraft, lastName })} />
              <LeadEditField label="Username" value={editDraft.username} onChange={(username) => setEditDraft({ ...editDraft, username })} />
              <LeadEditField label="Телефон" value={editDraft.phone} onChange={(phone) => setEditDraft({ ...editDraft, phone })} />
              <LeadEditField label="Возраст" type="number" value={editDraft.age} onChange={(age) => setEditDraft({ ...editDraft, age })} />
              <LeadEditField label="Страна" value={editDraft.country} onChange={(country) => setEditDraft({ ...editDraft, country })} />
            </div>
            <LeadEditField
              label="Удобное время звонка"
              value={editDraft.preferredCallTime}
              onChange={(preferredCallTime) => setEditDraft({ ...editDraft, preferredCallTime })}
            />
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase text-gray-500">Банковская карта</span>
              <select
                value={editDraft.hasCard}
                onChange={(event) => setEditDraft({ ...editDraft, hasCard: event.target.value as LeadEditDraft['hasCard'] })}
                className="h-11 w-full rounded-lg border border-white/10 bg-background/70 px-3 text-base text-gray-100 outline-none focus:border-accent-300/60 md:text-sm"
              >
                <option value="">Не указано</option>
                <option value="yes">Есть</option>
                <option value="no">Нет</option>
              </select>
            </label>

            {editError ? (
              <div className="rounded-lg border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">{editError}</div>
            ) : null}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setEditingLead(null)
                  setEditDraft(null)
                  setEditError('')
                }}
                disabled={isSavingLead}
                className="min-h-11 rounded-lg border border-white/10 px-4 text-sm font-medium text-gray-300 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isSavingLead}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-accent-400 px-5 text-sm font-semibold text-slate-950 transition hover:bg-accent-300 disabled:opacity-50"
              >
                {isSavingLead ? <LoaderCircle size={16} className="animate-spin" /> : null}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

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

function LeadEditField({
  label,
  value,
  onChange,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'number'
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase text-gray-500">{label}</span>
      <input
        type={type}
        min={type === 'number' ? 0 : undefined}
        max={type === 'number' ? 150 : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-11 w-full rounded-lg border border-white/10 bg-background/70 px-3 text-base text-gray-100 outline-none transition focus:border-accent-300/60 md:text-sm"
      />
    </label>
  )
}

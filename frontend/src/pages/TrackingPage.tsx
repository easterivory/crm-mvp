import {
  Activity,
  Archive,
  BarChart3,
  CalendarDays,
  Copy,
  DollarSign,
  Flame,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  TrendingUp,
  UsersRound,
  WalletCards,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { fetchBots } from '../features/bots/api'
import type { Bot } from '../features/bots/types'
import { fetchBuyerPerformance } from '../features/buyers'
import type { BuyerPerformance } from '../features/buyers'
import {
  archiveTrackingLink,
  createTrackingLink,
  createTrackingSpend,
  deleteTrackingSpend,
  fetchLinkTrackingMetrics,
  fetchManagerPerformance,
  fetchProjectTrackingMetrics,
  fetchTrackingLinks,
  fetchTrackingTargetSteps,
  fetchTrackingSpends,
  restoreTrackingLink,
  updateTrackingLink,
  updateTrackingSpend,
} from '../features/tracking/api'
import type {
  BreakdownItem,
  FunnelStepMetric,
  ManagerPerformance,
  TrackingConversionStatus,
  TrackingLink,
  TrackingLinkMetricsResponse,
  TrackingMetricSummary,
  TrackingProjectMetricsResponse,
  TrackingFunnelStepOption,
  TrackingSpend,
} from '../features/tracking/types'
import { useProjectBotSelection } from '../shared/lib'
import { Modal } from '../shared/ui'

type ActiveFilter = 'active' | 'inactive' | 'all'
type SpendMode = 'create' | 'edit'

const DEFAULT_BASE_CONVERSION_RATE = '10.0'
const DEFAULT_MIN_SAMPLE_SIZE = '500'

const zeroSummary: TrackingMetricSummary = {
  clicks: 0,
  starts: 0,
  leads: 0,
  submitted_leads: 0,
  deposits: 0,
  spend: 0,
  cr_to_lead: 0,
  cr_to_submit: 0,
  cr_to_deposit: 0,
  cpl: 0,
  cpsl: 0,
  cpd: 0,
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoIso(days: number) {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return date.toISOString().slice(0, 10)
}

function getErrorMessage(err: unknown, fallback = 'Request failed.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const messages = detail
        .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
        .filter(Boolean)
      if (messages.length > 0) {
        return messages.join(' ')
      }
    }
    if (err.response?.status === 409) {
      return 'This code already exists.'
    }
    if (err.response?.status === 422) {
      return 'Check the entered fields and try again.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Cannot reach API.'
    }
  }

  return fallback
}

function toNumber(value: string | number | null | undefined) {
  const numberValue = Number(value ?? 0)
  return Number.isFinite(numberValue) ? numberValue : 0
}

function formatNumber(value: string | number | null | undefined) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(
    toNumber(value),
  )
}

function formatMoney(value: string | number | null | undefined, currency = 'USD') {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(toNumber(value))
}

function formatPercent(value: string | number | null | undefined) {
  return `${toNumber(value).toFixed(1)}%`
}

function formatBenchmarkPercent(value: string | number | null | undefined) {
  return `${toNumber(value).toFixed(1)}%`
}

function parseBaseConversionRate(value: string) {
  if (value.trim() === '') {
    return null
  }
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > 100) {
    return null
  }
  return parsed
}

function parseMinSampleSize(value: string) {
  if (value.trim() === '') {
    return null
  }
  const parsed = Number(value)
  if (!Number.isInteger(parsed) || parsed < 1) {
    return null
  }
  return parsed
}

function conversionSampleSize(summary: TrackingMetricSummary) {
  return summary.clicks > 0 ? summary.clicks : summary.starts
}

function conversionCardClass(status: TrackingConversionStatus | undefined) {
  if (status === 'high_cr') {
    return 'border-emerald-500/25 bg-emerald-500/[0.055] shadow-lg shadow-emerald-500/5'
  }
  if (status === 'low_cr') {
    return 'border-red-500/20 bg-red-500/[0.065] shadow-card'
  }
  return 'border-white/5 bg-surface shadow-card'
}

function conversionTextClass(status: TrackingConversionStatus | undefined) {
  if (status === 'high_cr') {
    return 'text-emerald-300'
  }
  if (status === 'low_cr') {
    return 'text-red-300'
  }
  return 'text-gray-100'
}

function conversionHelperClass(status: TrackingConversionStatus | undefined) {
  if (status === 'high_cr') {
    return 'text-emerald-300'
  }
  if (status === 'low_cr') {
    return 'text-red-300'
  }
  return 'text-gray-500'
}

function conversionHelperText(
  status: TrackingConversionStatus | undefined,
  summary: TrackingMetricSummary,
  baseConversionRate: number,
  minSampleSize: number,
) {
  if (status === 'insufficient_data') {
    return `${formatNumber(conversionSampleSize(summary))}/${formatNumber(minSampleSize)} кликов`
  }
  if (status === 'low_cr') {
    return `Конверсия ниже цели ${formatBenchmarkPercent(baseConversionRate)}`
  }
  if (status === 'high_cr') {
    return `Конверсия выше цели ${formatBenchmarkPercent(baseConversionRate)}`
  }
  return ''
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    month: 'short',
    day: 'numeric',
  }).format(new Date(`${value}T00:00:00`))
}

function metricCard(label: string, value: string, helper?: string) {
  return (
    <div className="rounded-xl border border-white/5 bg-surface p-4 shadow-card">
      <p className="text-xs uppercase tracking-[0.18em] text-gray-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-white">{value}</p>
      {helper ? <p className="mt-1 text-xs text-gray-500">{helper}</p> : null}
    </div>
  )
}

function miniMetric(label: string, value: string) {
  return (
    <div className="min-w-0">
      <p className="text-xs uppercase tracking-[0.16em] text-gray-500">{label}</p>
      <p className="mt-1 truncate text-lg font-semibold text-white">{value}</p>
    </div>
  )
}

function breakdownList(items: BreakdownItem[], emptyText: string) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-white/5 bg-white/[0.03] px-4 py-5 text-sm text-gray-500">
        {emptyText}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item.key} className="rounded-xl border border-white/5 bg-white/[0.03] p-3">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="truncate font-medium text-gray-100">{item.label}</span>
            <span className="shrink-0 text-gray-400">
              {formatNumber(item.count)} · {formatPercent(item.percent)}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-accent-400"
              style={{ width: `${Math.min(toNumber(item.percent), 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function funnelList(items: FunnelStepMetric[]) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-white/5 bg-white/[0.03] px-4 py-5 text-sm text-gray-500">
        Данных по шагам воронки пока нет.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div
          key={item.step_key}
          className="flex items-center justify-between gap-3 rounded-xl border border-white/5 bg-white/[0.03] p-3 text-sm"
        >
          <span className="min-w-0">
            <span className="block truncate font-medium text-gray-100">{item.label}</span>
            <span className="text-xs text-gray-500">
              Dropoff {formatNumber(item.dropoff_count)} · {formatPercent(item.dropoff_percent)}
            </span>
          </span>
          <span className="shrink-0 text-lg font-semibold text-white">
            {formatNumber(item.count)}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function TrackingPage() {
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const [bots, setBots] = useState<Bot[]>([])
  const [links, setLinks] = useState<TrackingLink[]>([])
  const [metrics, setMetrics] = useState<TrackingProjectMetricsResponse | null>(null)
  const [managerPerformance, setManagerPerformance] = useState<ManagerPerformance[]>([])
  const [buyerPerformance, setBuyerPerformance] = useState<BuyerPerformance[]>([])
  const [dateFrom, setDateFrom] = useState(daysAgoIso(6))
  const [dateTo, setDateTo] = useState(todayIso())
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>('active')
  const [search, setSearch] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createTitle, setCreateTitle] = useState('')
  const [createBotId, setCreateBotId] = useState('')
  const [createCode, setCreateCode] = useState('')
  const [createBuyerName, setCreateBuyerName] = useState('')
  const [createAdType, setCreateAdType] = useState('')
  const [createPaymentType, setCreatePaymentType] = useState('')
  const [createInviteLink, setCreateInviteLink] = useState('')
  const [createBaseConversionRate, setCreateBaseConversionRate] = useState(
    DEFAULT_BASE_CONVERSION_RATE,
  )
  const [createMinSampleSize, setCreateMinSampleSize] = useState(
    DEFAULT_MIN_SAMPLE_SIZE,
  )
  const [createTargetStepKey, setCreateTargetStepKey] = useState('')
  const [createError, setCreateError] = useState('')
  const [isCreatingLink, setIsCreatingLink] = useState(false)
  const [mutatingLinkId, setMutatingLinkId] = useState<string | null>(null)
  const [editingLink, setEditingLink] = useState<TrackingLink | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editBuyerName, setEditBuyerName] = useState('')
  const [editAdType, setEditAdType] = useState('')
  const [editPaymentType, setEditPaymentType] = useState('')
  const [editInviteLink, setEditInviteLink] = useState('')
  const [editBaseConversionRate, setEditBaseConversionRate] = useState(
    DEFAULT_BASE_CONVERSION_RATE,
  )
  const [editMinSampleSize, setEditMinSampleSize] = useState(
    DEFAULT_MIN_SAMPLE_SIZE,
  )
  const [editTargetStepKey, setEditTargetStepKey] = useState('')
  const [targetStepsByBot, setTargetStepsByBot] = useState<Record<string, TrackingFunnelStepOption[]>>({})
  const [targetStepsLoadingBotId, setTargetStepsLoadingBotId] = useState<string | null>(null)
  const [editError, setEditError] = useState('')
  const [isUpdatingLink, setIsUpdatingLink] = useState(false)
  const [detailLink, setDetailLink] = useState<TrackingLink | null>(null)
  const [detailMetrics, setDetailMetrics] = useState<TrackingLinkMetricsResponse | null>(null)
  const [spends, setSpends] = useState<TrackingSpend[]>([])
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [spendLink, setSpendLink] = useState<TrackingLink | null>(null)
  const [spendMode, setSpendMode] = useState<SpendMode>('create')
  const [editingSpend, setEditingSpend] = useState<TrackingSpend | null>(null)
  const [spendDate, setSpendDate] = useState(todayIso())
  const [spendAmount, setSpendAmount] = useState('')
  const [spendCurrency, setSpendCurrency] = useState('USD')
  const [spendComment, setSpendComment] = useState('')
  const [spendError, setSpendError] = useState('')
  const [isSavingSpend, setIsSavingSpend] = useState(false)
  const [deletingSpendId, setDeletingSpendId] = useState<string | null>(null)

  const selectedBotIdForQuery =
    selectedBotIds.length === 1 ? selectedBotIds[0] : undefined
  const isMultiBotFallback = selectedBotIds.length > 1

  const botNameById = useMemo(
    () => new Map(bots.map((bot) => [bot.id, bot.name])),
    [bots],
  )

  const linkMetricsById = useMemo(() => {
    return new Map((metrics?.links ?? []).map((item) => [item.link_id, item]))
  }, [metrics?.links])

  const filteredLinks = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) {
      return links
    }

    return links.filter((link) => {
      return [link.code, link.title, link.buyer_name ?? '']
        .join(' ')
        .toLowerCase()
        .includes(query)
    })
  }, [links, search])

  const chartData = useMemo(() => {
    return (metrics?.daily ?? []).map((item) => ({
      date: formatShortDate(item.date),
      starts: item.starts,
      leads: item.leads,
      spend: toNumber(item.spend),
    }))
  }, [metrics?.daily])

  const detailChartData = useMemo(() => {
    return (detailMetrics?.daily ?? []).map((item) => ({
      date: formatShortDate(item.date),
      starts: item.starts,
      leads: item.leads,
      spend: toNumber(item.spend),
    }))
  }, [detailMetrics?.daily])

  const loadPageData = useCallback(async () => {
    if (!selectedProjectId) {
      setBots([])
      setLinks([])
      setMetrics(null)
      setManagerPerformance([])
      setBuyerPerformance([])
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const isActive =
        activeFilter === 'all' ? undefined : activeFilter === 'active'
      const params = {
        project_id: selectedProjectId,
        bot_id: selectedBotIdForQuery,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      }
      const [botItems, linkResponse, projectMetrics, managerItems, buyerItems] = await Promise.all([
        fetchBots(selectedProjectId),
        fetchTrackingLinks({
          project_id: selectedProjectId,
          bot_id: selectedBotIdForQuery,
          is_active: isActive,
          limit: 100,
          offset: 0,
        }),
        fetchProjectTrackingMetrics(params),
        fetchManagerPerformance({
          project_id: selectedProjectId,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        }),
        fetchBuyerPerformance(selectedProjectId, {
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          bot_id: selectedBotIdForQuery,
        }),
      ])

      setBots(botItems)
      setLinks(linkResponse.items)
      setMetrics(projectMetrics)
      setManagerPerformance(managerItems)
      setBuyerPerformance(buyerItems)
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load tracking data.'))
    } finally {
      setIsLoading(false)
    }
  }, [
    activeFilter,
    dateFrom,
    dateTo,
    selectedBotIdForQuery,
    selectedProjectId,
  ])

  const loadDetail = useCallback(
    async (link: TrackingLink) => {
      setIsDetailLoading(true)
      setDetailError('')

      try {
        const [linkMetrics, spendItems] = await Promise.all([
          fetchLinkTrackingMetrics(link.id, {
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
          }),
          fetchTrackingSpends(link.id, {
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
          }),
        ])
        setDetailMetrics(linkMetrics)
        setSpends(spendItems)
      } catch (err) {
        setDetailError(getErrorMessage(err, 'Could not load link details.'))
      } finally {
        setIsDetailLoading(false)
      }
    },
    [dateFrom, dateTo],
  )

  useEffect(() => {
    void loadPageData()
  }, [loadPageData])

  useEffect(() => {
    if (detailLink) {
      void loadDetail(detailLink)
    }
  }, [detailLink, loadDetail])

  const loadTargetSteps = useCallback(async (botId: string) => {
    if (!selectedProjectId || !botId) {
      return
    }
    if (targetStepsByBot[botId]) {
      return
    }

    setTargetStepsLoadingBotId(botId)
    try {
      const steps = await fetchTrackingTargetSteps(selectedProjectId, botId)
      setTargetStepsByBot((current) => ({ ...current, [botId]: steps }))
    } catch {
      setTargetStepsByBot((current) => ({ ...current, [botId]: [] }))
    } finally {
      setTargetStepsLoadingBotId((current) => (current === botId ? null : current))
    }
  }, [selectedProjectId, targetStepsByBot])

  const openCreateLink = () => {
    const defaultBotId =
      selectedBotIds.length === 1 && bots.some((bot) => bot.id === selectedBotIds[0])
        ? selectedBotIds[0]
        : bots[0]?.id ?? ''
    setCreateTitle('')
    setCreateBotId(defaultBotId)
    setCreateCode('')
    setCreateBuyerName('')
    setCreateAdType('')
    setCreatePaymentType('')
    setCreateInviteLink('')
    setCreateBaseConversionRate(DEFAULT_BASE_CONVERSION_RATE)
    setCreateMinSampleSize(DEFAULT_MIN_SAMPLE_SIZE)
    setCreateTargetStepKey('')
    setCreateError('')
    setIsCreateOpen(true)
    if (defaultBotId) {
      void loadTargetSteps(defaultBotId)
    }
  }

  const closeCreateLink = () => {
    if (!isCreatingLink) {
      setIsCreateOpen(false)
      setCreateError('')
    }
  }

  const handleCreateLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedProjectId || !createTitle.trim() || !createBotId || isCreatingLink) {
      return
    }
    const baseConversionRate = parseBaseConversionRate(createBaseConversionRate)
    const minSampleSize = parseMinSampleSize(createMinSampleSize)
    if (baseConversionRate === null) {
      setCreateError('Целевая конверсия должна быть числом от 0 до 100.')
      return
    }
    if (minSampleSize === null) {
      setCreateError('Минимальная выборка должна быть целым числом от 1.')
      return
    }

    setIsCreatingLink(true)
    setCreateError('')
    setNotice('')

    try {
      await createTrackingLink({
        project_id: selectedProjectId,
        bot_id: createBotId,
        title: createTitle.trim(),
        code: createCode.trim() || undefined,
        buyer_name: createBuyerName.trim() || null,
        ad_type: createAdType.trim() || null,
        payment_type: createPaymentType.trim() || null,
        invite_link: createInviteLink.trim() || null,
        base_conversion_rate: baseConversionRate,
        min_sample_size: minSampleSize,
        target_funnel_step_key: createTargetStepKey || null,
      })
      setIsCreateOpen(false)
      setNotice('Tracking link создан.')
      await loadPageData()
    } catch (err) {
      setCreateError(getErrorMessage(err, 'Could not create tracking link.'))
    } finally {
      setIsCreatingLink(false)
    }
  }

  const openEditLink = (link: TrackingLink) => {
    setEditingLink(link)
    setEditTitle(link.title)
    setEditBuyerName(link.buyer_name ?? '')
    setEditAdType(link.ad_type ?? '')
    setEditPaymentType(link.payment_type ?? '')
    setEditInviteLink(link.invite_link ?? '')
    setEditBaseConversionRate(String(link.base_conversion_rate ?? 10))
    setEditMinSampleSize(String(link.min_sample_size ?? 500))
    setEditTargetStepKey(link.target_funnel_step_key ?? '')
    setEditError('')
    void loadTargetSteps(link.bot_id)
  }

  const closeEditLink = () => {
    if (!isUpdatingLink) {
      setEditingLink(null)
      setEditError('')
    }
  }

  const handleUpdateLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!editingLink || !editTitle.trim() || isUpdatingLink) {
      return
    }

    const baseConversionRate = parseBaseConversionRate(editBaseConversionRate)
    const minSampleSize = parseMinSampleSize(editMinSampleSize)
    if (baseConversionRate === null) {
      setEditError('Целевая конверсия должна быть числом от 0 до 100.')
      return
    }
    if (minSampleSize === null) {
      setEditError('Минимальная выборка должна быть целым числом от 1.')
      return
    }

    setIsUpdatingLink(true)
    setEditError('')
    setNotice('')

    try {
      const updatedLink = await updateTrackingLink(editingLink.id, {
        title: editTitle.trim(),
        buyer_name: editBuyerName.trim() || null,
        ad_type: editAdType.trim() || null,
        payment_type: editPaymentType.trim() || null,
        invite_link: editInviteLink.trim() || null,
        base_conversion_rate: baseConversionRate,
        min_sample_size: minSampleSize,
        target_funnel_step_key: editTargetStepKey || null,
      })
      setNotice('Tracking link обновлён.')
      setEditingLink(null)
      setDetailLink((current) => (current?.id === updatedLink.id ? updatedLink : current))
      await loadPageData()
      if (detailLink?.id === updatedLink.id) {
        await loadDetail(updatedLink)
      }
    } catch (err) {
      setEditError(getErrorMessage(err, 'Could not update tracking link.'))
    } finally {
      setIsUpdatingLink(false)
    }
  }

  const handleCopy = async (link: TrackingLink) => {
    await navigator.clipboard.writeText(link.invite_link || link.code)
      setNotice(link.invite_link ? 'Invite link скопирован.' : 'Код скопирован.')
  }

  const handleArchiveToggle = async (link: TrackingLink) => {
    setMutatingLinkId(link.id)
    setError('')
    setNotice('')

    try {
      if (link.is_active) {
        await archiveTrackingLink(link.id)
        setNotice('Tracking link archived.')
      } else {
        await restoreTrackingLink(link.id)
        setNotice('Tracking link restored.')
      }
      await loadPageData()
    } catch (err) {
      setError(getErrorMessage(err, 'Could not update tracking link.'))
    } finally {
      setMutatingLinkId(null)
    }
  }

  const openDetail = (link: TrackingLink) => {
    setDetailLink(link)
    setDetailMetrics(null)
    setSpends([])
    setDetailError('')
  }

  const closeDetail = () => {
    setDetailLink(null)
    setDetailMetrics(null)
    setSpends([])
    setDetailError('')
  }

  const openSpendModal = (link: TrackingLink, spend?: TrackingSpend) => {
    setSpendLink(link)
    setSpendMode(spend ? 'edit' : 'create')
    setEditingSpend(spend ?? null)
    setSpendDate(spend?.spend_date ?? todayIso())
    setSpendAmount(spend ? String(spend.amount) : '')
    setSpendCurrency(spend?.currency ?? 'USD')
    setSpendComment(spend?.comment ?? '')
    setSpendError('')
  }

  const closeSpendModal = () => {
    if (!isSavingSpend) {
      setSpendLink(null)
      setEditingSpend(null)
      setSpendError('')
    }
  }

  const handleSaveSpend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!spendLink || isSavingSpend) {
      return
    }

    const amount = Number(spendAmount)
    if (!Number.isFinite(amount) || amount < 0) {
      setSpendError('Сумма должна быть нулём или больше.')
      return
    }

    setIsSavingSpend(true)
    setSpendError('')

    try {
      if (spendMode === 'edit' && editingSpend) {
        await updateTrackingSpend(editingSpend.id, {
          spend_date: spendDate,
          amount,
          currency: spendCurrency.trim().toUpperCase() || 'USD',
          comment: spendComment.trim() || null,
        })
      } else {
        await createTrackingSpend(spendLink.id, {
          spend_date: spendDate,
          amount,
          currency: spendCurrency.trim().toUpperCase() || 'USD',
          comment: spendComment.trim() || null,
        })
      }

      setNotice(spendMode === 'edit' ? 'Расход обновлён.' : 'Расход добавлен.')
      if (detailLink?.id === spendLink.id) {
        await loadDetail(spendLink)
      }
      await loadPageData()
      closeSpendModal()
    } catch (err) {
      setSpendError(getErrorMessage(err, 'Could not save spend.'))
    } finally {
      setIsSavingSpend(false)
    }
  }

  const handleDeleteSpend = async (spend: TrackingSpend) => {
    if (!detailLink || !window.confirm('Удалить эту запись расхода?')) {
      return
    }

    setDeletingSpendId(spend.id)
    setDetailError('')

    try {
      await deleteTrackingSpend(spend.id)
      setNotice('Расход удалён.')
      await loadDetail(detailLink)
      await loadPageData()
    } catch (err) {
      setDetailError(getErrorMessage(err, 'Could not delete spend.'))
    } finally {
      setDeletingSpendId(null)
    }
  }

  if (!selectedProjectId) {
    return (
      <section className="flex h-full min-h-0 items-center justify-center rounded-xl border border-white/5 bg-surface p-6 text-center shadow-card">
        <div>
          <BarChart3 className="mx-auto text-accent-300" size={32} />
          <h1 className="mt-4 text-xl font-semibold text-white">Выберите проект</h1>
          <p className="mt-2 max-w-md text-sm text-gray-500">
            Метрики и ссылки трекинга показываются для выбранного проекта.
          </p>
        </div>
      </section>
    )
  }

  const summary = metrics?.summary ?? zeroSummary

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0B0F19]/80 text-gray-200 shadow-card">
      <header className="shrink-0 border-b border-white/5 px-5 py-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-[0.25em] text-accent-300/70">
              Трафик
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-white">
              Трекинг
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Расходы, конверсии и аналитика ссылок для выбранного скоупа.
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-500">
                С
              </span>
              <input
                type="date"
                value={dateFrom}
                onChange={(event) => setDateFrom(event.target.value)}
                className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-500">
                По
              </span>
              <input
                type="date"
                value={dateTo}
                onChange={(event) => setDateTo(event.target.value)}
                className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
              />
            </label>
            <button
              type="button"
              onClick={() => void loadPageData()}
              title="Refresh"
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 hover:text-white"
            >
              {isLoading ? (
                <LoaderCircle size={17} className="animate-spin" />
              ) : (
                <RefreshCw size={17} />
              )}
            </button>
            <button
              type="button"
              onClick={openCreateLink}
              disabled={bots.length === 0}
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus size={17} />
              Создать ссылку
            </button>
          </div>
        </div>

        {isMultiBotFallback ? (
          <div className="mt-4 rounded-xl border border-yellow-400/20 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100">
            Фильтр по нескольким ботам будет уточнён позже. Сейчас показаны метрики проекта по всем ботам.
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

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
          {metricCard('Старты', formatNumber(summary.starts))}
          {metricCard('Лиды', formatNumber(summary.leads), `CR ${formatPercent(summary.cr_to_lead)}`)}
          {metricCard('Отправлены', formatNumber(summary.submitted_leads), `CR ${formatPercent(summary.cr_to_submit)}`)}
          {metricCard('Расход', formatMoney(summary.spend))}
          {metricCard('CPL', formatMoney(summary.cpl), `CPSL ${formatMoney(summary.cpsl)}`)}
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="rounded-xl border border-white/5 bg-surface p-4 shadow-card">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">Динамика трафика</h2>
                <p className="text-sm text-gray-500">Старты, лиды и расходы</p>
              </div>
              <Activity size={18} className="text-accent-300" />
            </div>
            <div className="h-64">
              {chartData.length === 0 ? (
                <div className="flex h-full items-center justify-center rounded-xl border border-white/5 bg-white/[0.03] text-sm text-gray-500">
                  Данных по дням пока нет.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ left: -18, right: 8, top: 12, bottom: 0 }}>
                    <defs>
                      <linearGradient id="startsGradient" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.35} />
                        <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="leadsGradient" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="5%" stopColor="#a855f7" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#a855f7" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="date" stroke="rgba(255,255,255,0.35)" tickLine={false} axisLine={false} />
                    <YAxis stroke="rgba(255,255,255,0.35)" tickLine={false} axisLine={false} />
                    <Tooltip
                      contentStyle={{
                        background: '#0B0F19',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: 12,
                        color: '#e5e7eb',
                      }}
                    />
                    <Area type="monotone" dataKey="starts" stroke="#22d3ee" fill="url(#startsGradient)" strokeWidth={2} />
                    <Area type="monotone" dataKey="leads" stroke="#a855f7" fill="url(#leadsGradient)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-white/5 bg-surface p-4 shadow-card">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-accent-300/20 bg-accent-500/10 text-accent-200">
                <TrendingUp size={18} />
              </div>
              <div>
                <p className="text-sm font-semibold text-white">Конверсия</p>
                <p className="text-xs text-gray-500">CR в лиды по проекту</p>
              </div>
            </div>
            <p className="mt-5 text-4xl font-semibold text-white">
              {formatPercent(summary.cr_to_lead)}
            </p>
            <div className="mt-5 space-y-3 text-sm">
              <div className="flex justify-between text-gray-400">
                <span>Депозиты</span>
                <span>{formatNumber(summary.deposits)}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>CPD</span>
                <span>{formatMoney(summary.cpd)}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>CR в депозит</span>
                <span>{formatPercent(summary.cr_to_deposit)}</span>
              </div>
            </div>
          </div>
        </div>

        <section className="mt-5 rounded-xl border border-white/5 bg-surface p-4 shadow-card">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <UsersRound size={18} className="text-accent-300" />
                <h2 className="font-semibold text-white">Качество менеджеров</h2>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Взятые чаты, личные подачи и валидность по обратной связи партнёра.
              </p>
            </div>
            <p className="text-xs leading-5 text-gray-500">
              Валид считается по подаче менеджера, когда партнёр вернул финальный статус.
            </p>
          </div>

          {managerPerformance.length === 0 ? (
            <div className="mt-4 rounded-xl border border-white/5 bg-white/[0.03] px-4 py-7 text-sm text-gray-500">
              В выбранном проекте пока нет менеджеров или действий за период.
            </div>
          ) : (
            <>
              <div className="mt-4 hidden overflow-x-auto lg:block">
                <table className="w-full min-w-[930px] text-left text-sm">
                  <thead className="border-b border-white/10 text-xs uppercase tracking-[0.12em] text-gray-500">
                    <tr>
                      <th className="px-3 py-3 font-semibold">Менеджер</th>
                      <th className="px-3 py-3 text-right font-semibold">Взял</th>
                      <th className="px-3 py-3 text-right font-semibold">Подал</th>
                      <th className="px-3 py-3 text-right font-semibold">Валид</th>
                      <th className="px-3 py-3 text-right font-semibold">Взял → подал</th>
                      <th className="px-3 py-3 text-right font-semibold">Подал → валид</th>
                      <th className="px-3 py-3 text-right font-semibold">Взял → валид</th>
                      <th className="px-3 py-3 text-right font-semibold">Вернул</th>
                    </tr>
                  </thead>
                  <tbody>
                    {managerPerformance.map((manager) => (
                      <tr key={manager.manager_id} className="border-b border-white/[0.06] last:border-0">
                        <td className="px-3 py-3">
                          <p className="font-medium text-gray-100">{manager.name}</p>
                          <p className="mt-0.5 text-xs text-gray-500">
                            {manager.handler_code ? `#${manager.handler_code} · ` : ''}{manager.email}
                          </p>
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatNumber(manager.chats_taken)}</td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatNumber(manager.submitted_leads)}</td>
                        <td className="px-3 py-3 text-right font-mono text-emerald-200">{formatNumber(manager.valid_leads)}</td>
                        <td className="px-3 py-3 text-right text-accent-100">{formatPercent(manager.taken_to_submitted_percent)}</td>
                        <td className="px-3 py-3 text-right text-accent-100">{formatPercent(manager.submitted_to_valid_percent)}</td>
                        <td className="px-3 py-3 text-right text-accent-100">{formatPercent(manager.taken_to_valid_percent)}</td>
                        <td className="px-3 py-3 text-right font-mono text-gray-300">{formatNumber(manager.returned_to_funnel)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 grid gap-3 lg:hidden">
                {managerPerformance.map((manager) => (
                  <article key={manager.manager_id} className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-gray-100">{manager.name}</p>
                        <p className="mt-1 truncate text-xs text-gray-500">
                          {manager.handler_code ? `#${manager.handler_code} · ` : ''}{manager.email}
                        </p>
                      </div>
                      <span className="shrink-0 text-xs text-gray-500">Вернул: {formatNumber(manager.returned_to_funnel)}</span>
                    </div>
                    <div className="mt-4 grid grid-cols-3 gap-2">
                      <div><p className="text-xs text-gray-500">Взял</p><p className="mt-1 font-mono text-gray-100">{formatNumber(manager.chats_taken)}</p></div>
                      <div><p className="text-xs text-gray-500">Подал</p><p className="mt-1 font-mono text-gray-100">{formatNumber(manager.submitted_leads)}</p></div>
                      <div><p className="text-xs text-gray-500">Валид</p><p className="mt-1 font-mono text-emerald-200">{formatNumber(manager.valid_leads)}</p></div>
                    </div>
                    <div className="mt-4 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-3 text-xs">
                      <div><p className="text-gray-500">Взял → подал</p><p className="mt-1 text-accent-100">{formatPercent(manager.taken_to_submitted_percent)}</p></div>
                      <div><p className="text-gray-500">Подал → валид</p><p className="mt-1 text-accent-100">{formatPercent(manager.submitted_to_valid_percent)}</p></div>
                      <div><p className="text-gray-500">Взял → валид</p><p className="mt-1 text-accent-100">{formatPercent(manager.taken_to_valid_percent)}</p></div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="mt-5 rounded-xl border border-white/5 bg-surface p-4 shadow-card">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <WalletCards size={18} className="text-emerald-300" />
                <h2 className="font-semibold text-white">Статистика баеров</h2>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Сводные показатели по всем ссылкам каждого баера за выбранный период.
              </p>
            </div>
            <p className="text-xs leading-5 text-gray-500">
              Количество ссылок показано целиком, остальные показатели следуют фильтру дат.
            </p>
          </div>

          {buyerPerformance.length === 0 ? (
            <div className="mt-4 rounded-xl border border-white/5 bg-white/[0.03] px-4 py-7 text-sm text-gray-500">
              Для выбранного проекта пока нет баеров с привязанными ссылками.
            </div>
          ) : (
            <>
              <div className="mt-4 hidden overflow-x-auto lg:block">
                <table className="w-full min-w-[860px] text-left text-sm">
                  <thead className="border-b border-white/10 text-xs uppercase tracking-[0.12em] text-gray-500">
                    <tr>
                      <th className="px-3 py-3 font-semibold">Баер</th>
                      <th className="px-3 py-3 text-right font-semibold">Ссылки</th>
                      <th className="px-3 py-3 text-right font-semibold">Расход</th>
                      <th className="px-3 py-3 text-right font-semibold">Клики</th>
                      <th className="px-3 py-3 text-right font-semibold">Лиды</th>
                      <th className="px-3 py-3 text-right font-semibold">CPL</th>
                      <th className="px-3 py-3 text-right font-semibold">Подано</th>
                      <th className="px-3 py-3 text-right font-semibold">CR в подачу</th>
                    </tr>
                  </thead>
                  <tbody>
                    {buyerPerformance.map((buyer) => (
                      <tr key={buyer.buyer_id} className="border-b border-white/[0.06] last:border-0">
                        <td className="px-3 py-3">
                          <p className="font-medium text-gray-100">{buyer.name}</p>
                          <p className="mt-0.5 text-xs text-gray-500">{buyer.email}</p>
                        </td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatNumber(buyer.links_count)}</td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatMoney(buyer.total_spend)}</td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatNumber(buyer.clicks)}</td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatNumber(buyer.leads)}</td>
                        <td className="px-3 py-3 text-right font-mono text-accent-100">{formatMoney(buyer.cpl)}</td>
                        <td className="px-3 py-3 text-right font-mono text-gray-200">{formatNumber(buyer.submitted_leads)}</td>
                        <td className="px-3 py-3 text-right text-emerald-200">{formatPercent(buyer.submitted_conversion_percent)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="mt-4 grid gap-3 lg:hidden">
                {buyerPerformance.map((buyer) => (
                  <article key={buyer.buyer_id} className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                    <p className="truncate font-medium text-gray-100">{buyer.name}</p>
                    <p className="mt-1 truncate text-xs text-gray-500">{buyer.email}</p>
                    <div className="mt-4 grid grid-cols-3 gap-2">
                      <div><p className="text-xs text-gray-500">Ссылки</p><p className="mt-1 font-mono text-gray-100">{formatNumber(buyer.links_count)}</p></div>
                      <div><p className="text-xs text-gray-500">Расход</p><p className="mt-1 font-mono text-gray-100">{formatMoney(buyer.total_spend)}</p></div>
                      <div><p className="text-xs text-gray-500">Клики</p><p className="mt-1 font-mono text-gray-100">{formatNumber(buyer.clicks)}</p></div>
                      <div><p className="text-xs text-gray-500">Лиды</p><p className="mt-1 font-mono text-gray-100">{formatNumber(buyer.leads)}</p></div>
                      <div><p className="text-xs text-gray-500">CPL</p><p className="mt-1 font-mono text-accent-100">{formatMoney(buyer.cpl)}</p></div>
                      <div><p className="text-xs text-gray-500">Подано</p><p className="mt-1 font-mono text-gray-100">{formatNumber(buyer.submitted_leads)}</p></div>
                    </div>
                    <div className="mt-4 border-t border-white/[0.06] pt-3 text-xs">
                      <p className="text-gray-500">Конверсия лид → подача</p>
                      <p className="mt-1 text-emerald-200">{formatPercent(buyer.submitted_conversion_percent)}</p>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>

        <div className="mt-5 flex flex-col gap-3 rounded-xl border border-white/5 bg-surface p-4 shadow-card md:flex-row md:items-center md:justify-between">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Поиск по коду, названию или buyer"
              className="h-10 w-full rounded-xl border border-white/10 bg-white/[0.04] pl-10 pr-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/60"
            />
          </div>
          <select
            value={activeFilter}
            onChange={(event) => setActiveFilter(event.target.value as ActiveFilter)}
            className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          >
            <option value="active">Активные ссылки</option>
            <option value="inactive">Архивные ссылки</option>
            <option value="all">Все ссылки</option>
          </select>
        </div>

        {isLoading ? (
          <div className="mt-5 flex items-center justify-center rounded-xl border border-white/5 bg-surface px-4 py-16 text-sm text-gray-500">
            <LoaderCircle size={18} className="mr-2 animate-spin" />
            Загрузка трекинга
          </div>
        ) : null}

        {!isLoading && bots.length === 0 ? (
          <div className="mt-5 rounded-xl border border-white/5 bg-surface px-4 py-12 text-center text-sm text-gray-500">
            В проекте пока нет ботов. Создайте бота перед генерацией ссылок.
          </div>
        ) : null}

        {!isLoading && bots.length > 0 && filteredLinks.length === 0 ? (
          <div className="mt-5 rounded-xl border border-white/5 bg-surface px-4 py-12 text-center text-sm text-gray-500">
            Нет tracking links под текущие фильтры.
          </div>
        ) : null}

        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          {filteredLinks.map((link) => {
            const linkMetric = linkMetricsById.get(link.id)
            const linkSummary = linkMetric?.summary ?? zeroSummary
            const botLabel = botNameById.get(link.bot_id) ?? `Bot ${link.bot_id.slice(0, 8)}`
            const conversionStatus = linkMetric?.conversion_status
            const baseConversionRate =
              linkMetric?.base_conversion_rate ?? link.base_conversion_rate
            const minSampleSize = linkMetric?.min_sample_size ?? link.min_sample_size
            const conversionHelper = conversionHelperText(
              conversionStatus,
              linkSummary,
              baseConversionRate,
              minSampleSize,
            )

            return (
              <article
                key={link.id}
                className={`rounded-xl border p-4 transition ${conversionCardClass(conversionStatus)}`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-accent-300/20 bg-accent-500/10 px-2 py-1 font-mono text-xs text-accent-100">
                        {link.code}
                      </span>
                      <span className={`rounded-full px-2 py-1 text-xs ${
                        link.is_active
                          ? 'bg-emerald-500/10 text-emerald-200'
                          : 'bg-gray-500/10 text-gray-400'
                      }`}>
                        {link.is_active ? 'Активна' : 'Архив'}
                      </span>
                    </div>
                    <h3 className="mt-3 truncate text-lg font-semibold text-white">
                      {link.title}
                    </h3>
                    <p className="mt-1 truncate text-sm text-gray-500">
                      {botLabel} · {link.buyer_name || 'buyer не указан'} · {link.ad_type || 'тип рекламы не указан'} · {link.payment_type || 'оплата не указана'}
                    </p>
                    {link.target_funnel_step_key ? (
                      <p className="mt-2 inline-flex max-w-full items-center rounded-lg border border-violet-300/20 bg-violet-400/10 px-2 py-1 text-xs text-violet-100">
                        Вход: {link.target_funnel_step_title || link.target_funnel_step_key}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => openEditLink(link)}
                      title="Настроить"
                      className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleCopy(link)}
                      title="Копировать"
                      className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
                    >
                      <Copy size={15} />
                    </button>
                  </div>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-white/5 bg-white/[0.03] p-4 md:grid-cols-4">
                  {miniMetric('Старты', formatNumber(linkSummary.starts))}
                  {miniMetric('Лиды', formatNumber(linkSummary.leads))}
                  {miniMetric('Расход', formatMoney(linkSummary.spend))}
                  {miniMetric('CPL', formatMoney(linkSummary.cpl))}
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm text-gray-500">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span>CR в лид</span>
                      <span
                        className={`inline-flex items-center gap-1 font-semibold ${conversionTextClass(conversionStatus)}`}
                      >
                        {conversionStatus === 'high_cr' ? (
                          <Flame
                            size={16}
                            className="animate-pulse fill-orange-300 text-orange-300 drop-shadow-[0_0_10px_rgba(251,146,60,0.8)]"
                          />
                        ) : null}
                        {formatPercent(linkSummary.cr_to_lead)}
                      </span>
                      <span>· Отправлены</span>
                      <span className="text-gray-100">
                        {formatNumber(linkSummary.submitted_leads)}
                      </span>
                    </div>
                    {conversionHelper ? (
                      <p className={`mt-1 text-xs ${conversionHelperClass(conversionStatus)}`}>
                        {conversionHelper}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => openSpendModal(link)}
                      className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                    >
                      <DollarSign size={15} />
                      Добавить расход
                    </button>
                    <button
                      type="button"
                      onClick={() => openDetail(link)}
                      className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                    >
                      <BarChart3 size={15} />
                      Детали
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleArchiveToggle(link)}
                      disabled={mutatingLinkId === link.id}
                      className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {mutatingLinkId === link.id ? (
                        <LoaderCircle size={15} className="animate-spin" />
                      ) : link.is_active ? (
                        <Archive size={15} />
                      ) : (
                        <RotateCcw size={15} />
                      )}
                      {link.is_active ? 'Архивировать' : 'Восстановить'}
                    </button>
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </div>

      {isCreateOpen ? (
        <Modal
          title="Создать tracking link"
          description="Сгенерируйте source-ссылку для выбранного проекта."
          onClose={closeCreateLink}
          maxWidthClassName="max-w-lg"
        >
          <form className="space-y-3" onSubmit={handleCreateLink}>
            {createError ? (
              <div className="rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {createError}
              </div>
            ) : null}
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Название
              </span>
              <input
                value={createTitle}
                onChange={(event) => setCreateTitle(event.target.value)}
                required
                maxLength={255}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Таргет Инста"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Бот
              </span>
              <select
                value={createBotId}
                onChange={(event) => {
                  const botId = event.target.value
                  setCreateBotId(botId)
                  setCreateTargetStepKey('')
                  void loadTargetSteps(botId)
                }}
                required
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
              >
                <option value="" disabled>
                  Выберите бота
                </option>
                {bots.map((bot) => (
                  <option key={bot.id} value={bot.id}>
                    {bot.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Точка входа в воронку
              </span>
              <select
                value={createTargetStepKey}
                onChange={(event) => setCreateTargetStepKey(event.target.value)}
                disabled={!createBotId || targetStepsLoadingBotId === createBotId}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
              >
                <option value="">Обычный старт воронки</option>
                {(targetStepsByBot[createBotId] ?? []).map((step) => (
                  <option key={step.key} value={step.key}>
                    {step.title} · {step.block_type}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-gray-500">
                {targetStepsLoadingBotId === createBotId
                  ? 'Загружаем шаги активной воронки...'
                  : 'Выберите шаг, если трафик должен заходить не через стартовый триггер.'}
              </span>
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Код
                </span>
                <input
                  value={createCode}
                  onChange={(event) => setCreateCode(event.target.value)}
                  maxLength={100}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="optional-code"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Buyer
                </span>
                <input
                  value={createBuyerName}
                  onChange={(event) => setCreateBuyerName(event.target.value)}
                  maxLength={255}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="Имя buyer"
                />
              </label>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Тип рекламы
                </span>
                <input
                  value={createAdType}
                  onChange={(event) => setCreateAdType(event.target.value)}
                  maxLength={100}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="instagram"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Тип оплаты
                </span>
                <input
                  value={createPaymentType}
                  onChange={(event) => setCreatePaymentType(event.target.value)}
                  maxLength={100}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="cpa"
                />
              </label>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Целевая конверсия (%)
                </span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={createBaseConversionRate}
                  onChange={(event) => setCreateBaseConversionRate(event.target.value)}
                  required
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="10.0"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Минимальная выборка кликов
                </span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={createMinSampleSize}
                  onChange={(event) => setCreateMinSampleSize(event.target.value)}
                  required
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="500"
                />
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Invite link
              </span>
              <input
                value={createInviteLink}
                onChange={(event) => setCreateInviteLink(event.target.value)}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Готовый URL, необязательно"
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={closeCreateLink}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={!createTitle.trim() || !createBotId || isCreatingLink}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreatingLink ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Создать
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {editingLink ? (
        <Modal
          title="Редактировать tracking link"
          description={`Code ${editingLink.code}`}
          onClose={closeEditLink}
          maxWidthClassName="max-w-lg"
        >
          <form className="space-y-3" onSubmit={handleUpdateLink}>
            {editError ? (
              <div className="rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {editError}
              </div>
            ) : null}
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Название
              </span>
              <input
                value={editTitle}
                onChange={(event) => setEditTitle(event.target.value)}
                required
                maxLength={255}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Таргет Инста"
              />
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Buyer
                </span>
                <input
                  value={editBuyerName}
                  onChange={(event) => setEditBuyerName(event.target.value)}
                  maxLength={255}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="Имя buyer"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Тип рекламы
                </span>
                <input
                  value={editAdType}
                  onChange={(event) => setEditAdType(event.target.value)}
                  maxLength={100}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="instagram"
                />
              </label>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Тип оплаты
                </span>
                <input
                  value={editPaymentType}
                  onChange={(event) => setEditPaymentType(event.target.value)}
                  maxLength={100}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="cpa"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Invite link
                </span>
                <input
                  value={editInviteLink}
                  onChange={(event) => setEditInviteLink(event.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="Готовый URL, необязательно"
                />
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Точка входа в активную воронку
              </span>
              <select
                value={editTargetStepKey}
                onChange={(event) => setEditTargetStepKey(event.target.value)}
                disabled={targetStepsLoadingBotId === editingLink.bot_id}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
              >
                <option value="">Обычный старт воронки</option>
                {(targetStepsByBot[editingLink.bot_id] ?? []).map((step) => (
                  <option key={step.key} value={step.key}>
                    {step.title} · {step.block_type}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-gray-500">
                {targetStepsLoadingBotId === editingLink.bot_id
                  ? 'Загружаем шаги активной воронки...'
                  : 'Ссылка зайдет прямо на выбранный шаг, если активная воронка этого бота не изменилась.'}
              </span>
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Целевая конверсия (%)
                </span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={editBaseConversionRate}
                  onChange={(event) => setEditBaseConversionRate(event.target.value)}
                  required
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="10.0"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Минимальная выборка кликов
                </span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={editMinSampleSize}
                  onChange={(event) => setEditMinSampleSize(event.target.value)}
                  required
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                  placeholder="500"
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={closeEditLink}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={!editTitle.trim() || isUpdatingLink}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isUpdatingLink ? (
                  <LoaderCircle size={16} className="animate-spin" />
                ) : (
                  <Pencil size={16} />
                )}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {detailLink ? (
        <Modal
          title={detailLink.title}
          description={`Code ${detailLink.code}`}
          onClose={closeDetail}
          maxWidthClassName="max-w-6xl"
        >
          {isDetailLoading ? (
            <div className="flex items-center justify-center py-16 text-sm text-gray-500">
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Загрузка аналитики ссылки
            </div>
          ) : null}

          {detailError ? (
            <div className="mb-4 rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {detailError}
            </div>
          ) : null}

          {detailMetrics ? (
            <div className="space-y-5">
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                {metricCard('Старты', formatNumber(detailMetrics.summary.starts))}
                {metricCard('Лиды', formatNumber(detailMetrics.summary.leads))}
                {metricCard('Отправлены', formatNumber(detailMetrics.summary.submitted_leads))}
                {metricCard('Расход', formatMoney(detailMetrics.summary.spend))}
                {metricCard('CPL', formatMoney(detailMetrics.summary.cpl))}
                {metricCard('CPD', formatMoney(detailMetrics.summary.cpd))}
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="font-semibold text-white">Детализация по дням</h3>
                  <CalendarDays size={18} className="text-accent-300" />
                </div>
                <div className="h-64">
                  {detailChartData.length === 0 ? (
                    <div className="flex h-full items-center justify-center rounded-xl border border-white/5 bg-background/50 text-sm text-gray-500">
                      Данных по дням пока нет.
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={detailChartData} margin={{ left: -18, right: 8, top: 12, bottom: 0 }}>
                        <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                        <XAxis dataKey="date" stroke="rgba(255,255,255,0.35)" tickLine={false} axisLine={false} />
                        <YAxis stroke="rgba(255,255,255,0.35)" tickLine={false} axisLine={false} />
                        <Tooltip
                          contentStyle={{
                            background: '#0B0F19',
                            border: '1px solid rgba(255,255,255,0.1)',
                            borderRadius: 12,
                            color: '#e5e7eb',
                          }}
                        />
                        <Area type="monotone" dataKey="starts" stroke="#22d3ee" fill="#22d3ee22" strokeWidth={2} />
                        <Area type="monotone" dataKey="leads" stroke="#a855f7" fill="#a855f722" strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <div>
                  <h3 className="mb-3 font-semibold text-white">Шаги воронки</h3>
                  {funnelList(detailMetrics.funnel_steps)}
                </div>
                <div>
                  <h3 className="mb-3 font-semibold text-white">Возраст</h3>
                  {breakdownList(detailMetrics.age_breakdown, 'Данных по возрасту пока нет.')}
                </div>
                <div>
                  <h3 className="mb-3 font-semibold text-white">Страна</h3>
                  {breakdownList(detailMetrics.country_breakdown, 'Данных по странам пока нет.')}
                </div>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-white">Расходы</h3>
                    <p className="text-sm text-gray-500">Ручные расходы CRM по этой ссылке</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openSpendModal(detailLink)}
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                  >
                    <WalletCards size={15} />
                    Добавить расход
                  </button>
                </div>

                {spends.length === 0 ? (
                  <div className="rounded-xl border border-white/5 bg-background/50 px-4 py-5 text-sm text-gray-500">
                    Расходов пока нет.
                  </div>
                ) : (
                  <>
                    <div className="grid gap-3 md:hidden">
                      {spends.map((spend) => (
                        <article
                          key={spend.id}
                          className="rounded-xl border border-white/5 bg-background/50 p-4"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="text-xs uppercase tracking-[0.16em] text-gray-500">
                                {spend.spend_date}
                              </p>
                              <p className="mt-1 text-lg font-semibold text-white">
                                {formatMoney(spend.amount, spend.currency)}
                              </p>
                            </div>
                            <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-gray-300">
                              {spend.source}
                            </span>
                          </div>
                          <p className="mt-3 text-sm leading-6 text-gray-400">
                            {spend.comment || 'Без комментария'}
                          </p>
                          <div className="mt-4 flex justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => openSpendModal(detailLink, spend)}
                              className="rounded-lg border border-white/10 px-3 py-2 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                            >
                              Изменить
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleDeleteSpend(spend)}
                              disabled={deletingSpendId === spend.id}
                              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-white/10 text-gray-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                              aria-label="Удалить расход"
                            >
                              {deletingSpendId === spend.id ? (
                                <LoaderCircle size={14} className="animate-spin" />
                              ) : (
                                <Trash2 size={14} />
                              )}
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                    <div className="hidden overflow-x-auto rounded-xl border border-white/5 md:block">
                      <table className="min-w-[720px] w-full text-left text-sm">
                        <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-gray-500">
                          <tr>
                            <th className="px-4 py-3">Дата</th>
                            <th className="px-4 py-3">Сумма</th>
                            <th className="px-4 py-3">Источник</th>
                            <th className="px-4 py-3">Комментарий</th>
                            <th className="px-4 py-3 text-right">Действия</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                          {spends.map((spend) => (
                            <tr key={spend.id}>
                              <td className="px-4 py-3 text-gray-200">{spend.spend_date}</td>
                              <td className="px-4 py-3 font-medium text-white">
                                {formatMoney(spend.amount, spend.currency)}
                              </td>
                              <td className="px-4 py-3 text-gray-400">{spend.source}</td>
                              <td className="px-4 py-3 text-gray-400">
                                {spend.comment || 'Без комментария'}
                              </td>
                              <td className="px-4 py-3">
                                <div className="flex justify-end gap-2">
                                  <button
                                    type="button"
                                    onClick={() => openSpendModal(detailLink, spend)}
                                    className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                                  >
                                    Изменить
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void handleDeleteSpend(spend)}
                                    disabled={deletingSpendId === spend.id}
                                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-gray-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                                  >
                                    {deletingSpendId === spend.id ? (
                                      <LoaderCircle size={14} className="animate-spin" />
                                    ) : (
                                      <Trash2 size={14} />
                                    )}
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : null}
        </Modal>
      ) : null}

      {spendLink ? (
        <Modal
          title={spendMode === 'edit' ? 'Изменить расход' : 'Добавить расход'}
          description={spendLink.title}
          onClose={closeSpendModal}
          maxWidthClassName="max-w-md"
        >
          <form className="space-y-3" onSubmit={handleSaveSpend}>
            {spendError ? (
              <div className="rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {spendError}
              </div>
            ) : null}
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Дата
              </span>
              <input
                type="date"
                value={spendDate}
                onChange={(event) => setSpendDate(event.target.value)}
                required
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Сумма
              </span>
              <input
                type="number"
                min="0"
                step="0.01"
                value={spendAmount}
                onChange={(event) => setSpendAmount(event.target.value)}
                required
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="0.00"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Валюта
              </span>
              <input
                value={spendCurrency}
                onChange={(event) => setSpendCurrency(event.target.value)}
                maxLength={3}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm uppercase text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="USD"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Комментарий
              </span>
              <textarea
                value={spendComment}
                onChange={(event) => setSpendComment(event.target.value)}
                rows={3}
                className="max-h-32 w-full resize-none overflow-y-auto rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Комментарий необязателен"
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={closeSpendModal}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={!spendDate || !spendAmount || isSavingSpend}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSavingSpend ? <LoaderCircle size={16} className="animate-spin" /> : <DollarSign size={16} />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </section>
  )
}

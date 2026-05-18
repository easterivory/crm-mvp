import {
  Activity,
  Archive,
  BarChart3,
  CalendarDays,
  Copy,
  DollarSign,
  LoaderCircle,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  TrendingUp,
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
import {
  archiveTrackingLink,
  createTrackingLink,
  createTrackingSpend,
  deleteTrackingSpend,
  fetchLinkTrackingMetrics,
  fetchProjectTrackingMetrics,
  fetchTrackingLinks,
  fetchTrackingSpends,
  restoreTrackingLink,
  updateTrackingSpend,
} from '../features/tracking/api'
import type {
  BreakdownItem,
  FunnelStepMetric,
  TrackingLink,
  TrackingLinkMetricsResponse,
  TrackingMetricSummary,
  TrackingProjectMetricsResponse,
  TrackingSpend,
} from '../features/tracking/types'
import { useProjectBotSelection } from '../shared/lib'
import { Modal } from '../shared/ui'

type ActiveFilter = 'active' | 'inactive' | 'all'
type SpendMode = 'create' | 'edit'

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
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(
    toNumber(value),
  )
}

function formatMoney(value: string | number | null | undefined, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(toNumber(value))
}

function formatPercent(value: string | number | null | undefined) {
  return `${toNumber(value).toFixed(1)}%`
}

function formatShortDate(value: string) {
  return new Intl.DateTimeFormat('en-US', {
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
        No funnel step data yet.
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
  const [createError, setCreateError] = useState('')
  const [isCreatingLink, setIsCreatingLink] = useState(false)
  const [mutatingLinkId, setMutatingLinkId] = useState<string | null>(null)
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
      const [botItems, linkResponse, projectMetrics] = await Promise.all([
        fetchBots(selectedProjectId),
        fetchTrackingLinks({
          project_id: selectedProjectId,
          bot_id: selectedBotIdForQuery,
          is_active: isActive,
          limit: 100,
          offset: 0,
        }),
        fetchProjectTrackingMetrics(params),
      ])

      setBots(botItems)
      setLinks(linkResponse.items)
      setMetrics(projectMetrics)
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
    setCreateError('')
    setIsCreateOpen(true)
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
      })
      setIsCreateOpen(false)
      setNotice('Tracking link created.')
      await loadPageData()
    } catch (err) {
      setCreateError(getErrorMessage(err, 'Could not create tracking link.'))
    } finally {
      setIsCreatingLink(false)
    }
  }

  const handleCopy = async (link: TrackingLink) => {
    await navigator.clipboard.writeText(link.invite_link || link.code)
    setNotice(link.invite_link ? 'Invite link copied.' : 'Code copied.')
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
      setSpendError('Amount must be zero or greater.')
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

      setNotice(spendMode === 'edit' ? 'Spend updated.' : 'Spend added.')
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
    if (!detailLink || !window.confirm('Delete this spend entry?')) {
      return
    }

    setDeletingSpendId(spend.id)
    setDetailError('')

    try {
      await deleteTrackingSpend(spend.id)
      setNotice('Spend deleted.')
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
            Tracking metrics and traffic links are scoped by the global project selector.
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
              Traffic
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-white">
              Tracking links
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Spend, conversion and link-level analytics for the selected scope.
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-500">
                From
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
                To
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
              Create link
            </button>
          </div>
        </div>

        {isMultiBotFallback ? (
          <div className="mt-4 rounded-xl border border-yellow-400/20 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-100">
            Multiple bot filter will be refined later. Showing project-level metrics for all bots.
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
          {metricCard('Starts', formatNumber(summary.starts))}
          {metricCard('Leads', formatNumber(summary.leads), `CR ${formatPercent(summary.cr_to_lead)}`)}
          {metricCard('Submitted', formatNumber(summary.submitted_leads), `CR ${formatPercent(summary.cr_to_submit)}`)}
          {metricCard('Spend', formatMoney(summary.spend))}
          {metricCard('CPL', formatMoney(summary.cpl), `CPSL ${formatMoney(summary.cpsl)}`)}
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="rounded-xl border border-white/5 bg-surface p-4 shadow-card">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold text-white">Daily traffic</h2>
                <p className="text-sm text-gray-500">Starts, leads and spend</p>
              </div>
              <Activity size={18} className="text-accent-300" />
            </div>
            <div className="h-64">
              {chartData.length === 0 ? (
                <div className="flex h-full items-center justify-center rounded-xl border border-white/5 bg-white/[0.03] text-sm text-gray-500">
                  No daily data yet.
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
                <p className="text-sm font-semibold text-white">Conversion rate</p>
                <p className="text-xs text-gray-500">Project-level lead CR</p>
              </div>
            </div>
            <p className="mt-5 text-4xl font-semibold text-white">
              {formatPercent(summary.cr_to_lead)}
            </p>
            <div className="mt-5 space-y-3 text-sm">
              <div className="flex justify-between text-gray-400">
                <span>Deposits</span>
                <span>{formatNumber(summary.deposits)}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>CPD</span>
                <span>{formatMoney(summary.cpd)}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>CR to deposit</span>
                <span>{formatPercent(summary.cr_to_deposit)}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="mt-5 flex flex-col gap-3 rounded-xl border border-white/5 bg-surface p-4 shadow-card md:flex-row md:items-center md:justify-between">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by code, title, buyer"
              className="h-10 w-full rounded-xl border border-white/10 bg-white/[0.04] pl-10 pr-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/60"
            />
          </div>
          <select
            value={activeFilter}
            onChange={(event) => setActiveFilter(event.target.value as ActiveFilter)}
            className="h-10 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
          >
            <option value="active">Active links</option>
            <option value="inactive">Inactive links</option>
            <option value="all">All links</option>
          </select>
        </div>

        {isLoading ? (
          <div className="mt-5 flex items-center justify-center rounded-xl border border-white/5 bg-surface px-4 py-16 text-sm text-gray-500">
            <LoaderCircle size={18} className="mr-2 animate-spin" />
            Loading tracking data
          </div>
        ) : null}

        {!isLoading && bots.length === 0 ? (
          <div className="mt-5 rounded-xl border border-white/5 bg-surface px-4 py-12 text-center text-sm text-gray-500">
            No bots in this project yet. Create a bot before generating tracking links.
          </div>
        ) : null}

        {!isLoading && bots.length > 0 && filteredLinks.length === 0 ? (
          <div className="mt-5 rounded-xl border border-white/5 bg-surface px-4 py-12 text-center text-sm text-gray-500">
            No tracking links match the current filters.
          </div>
        ) : null}

        <div className="mt-5 grid gap-4 xl:grid-cols-2">
          {filteredLinks.map((link) => {
            const linkMetric = linkMetricsById.get(link.id)
            const linkSummary = linkMetric?.summary ?? zeroSummary
            const botLabel = botNameById.get(link.bot_id) ?? `Bot ${link.bot_id.slice(0, 8)}`

            return (
              <article
                key={link.id}
                className="rounded-xl border border-white/5 bg-surface p-4 shadow-card"
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
                        {link.is_active ? 'Active' : 'Archived'}
                      </span>
                    </div>
                    <h3 className="mt-3 truncate text-lg font-semibold text-white">
                      {link.title}
                    </h3>
                    <p className="mt-1 truncate text-sm text-gray-500">
                      {botLabel} · {link.buyer_name || 'No buyer'} · {link.ad_type || 'No ad type'} · {link.payment_type || 'No payment'}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleCopy(link)}
                    title="Copy"
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
                  >
                    <Copy size={15} />
                  </button>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border border-white/5 bg-white/[0.03] p-4 md:grid-cols-4">
                  {miniMetric('Starts', formatNumber(linkSummary.starts))}
                  {miniMetric('Leads', formatNumber(linkSummary.leads))}
                  {miniMetric('Spend', formatMoney(linkSummary.spend))}
                  {miniMetric('CPL', formatMoney(linkSummary.cpl))}
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm text-gray-500">
                    Lead CR <span className="text-gray-100">{formatPercent(linkSummary.cr_to_lead)}</span>
                    {' '}· Submitted <span className="text-gray-100">{formatNumber(linkSummary.submitted_leads)}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => openSpendModal(link)}
                      className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                    >
                      <DollarSign size={15} />
                      Add spend
                    </button>
                    <button
                      type="button"
                      onClick={() => openDetail(link)}
                      className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                    >
                      <BarChart3 size={15} />
                      Details
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
                      {link.is_active ? 'Archive' : 'Restore'}
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
          title="Create tracking link"
          description="Generate a source link for the selected project."
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
                Title
              </span>
              <input
                value={createTitle}
                onChange={(event) => setCreateTitle(event.target.value)}
                required
                maxLength={255}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Target Insta"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Bot
              </span>
              <select
                value={createBotId}
                onChange={(event) => setCreateBotId(event.target.value)}
                required
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
              >
                <option value="" disabled>
                  Select bot
                </option>
                {bots.map((bot) => (
                  <option key={bot.id} value={bot.id}>
                    {bot.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Code
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
                  placeholder="Buyer name"
                />
              </label>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Ad type
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
                  Payment type
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
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                Invite link
              </span>
              <input
                value={createInviteLink}
                onChange={(event) => setCreateInviteLink(event.target.value)}
                className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Optional ready URL"
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={closeCreateLink}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!createTitle.trim() || !createBotId || isCreatingLink}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreatingLink ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Create
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
              Loading link analytics
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
                {metricCard('Starts', formatNumber(detailMetrics.summary.starts))}
                {metricCard('Leads', formatNumber(detailMetrics.summary.leads))}
                {metricCard('Submitted', formatNumber(detailMetrics.summary.submitted_leads))}
                {metricCard('Spend', formatMoney(detailMetrics.summary.spend))}
                {metricCard('CPL', formatMoney(detailMetrics.summary.cpl))}
                {metricCard('CPD', formatMoney(detailMetrics.summary.cpd))}
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="font-semibold text-white">Daily detail</h3>
                  <CalendarDays size={18} className="text-accent-300" />
                </div>
                <div className="h-64">
                  {detailChartData.length === 0 ? (
                    <div className="flex h-full items-center justify-center rounded-xl border border-white/5 bg-background/50 text-sm text-gray-500">
                      No daily data yet.
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
                  <h3 className="mb-3 font-semibold text-white">Funnel steps</h3>
                  {funnelList(detailMetrics.funnel_steps)}
                </div>
                <div>
                  <h3 className="mb-3 font-semibold text-white">Age</h3>
                  {breakdownList(detailMetrics.age_breakdown, 'No age data yet.')}
                </div>
                <div>
                  <h3 className="mb-3 font-semibold text-white">Country</h3>
                  {breakdownList(detailMetrics.country_breakdown, 'No country data yet.')}
                </div>
              </div>

              <div className="rounded-xl border border-white/5 bg-white/[0.03] p-4">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-white">Spend entries</h3>
                    <p className="text-sm text-gray-500">Manual CRM spend for this link</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => openSpendModal(detailLink)}
                    className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                  >
                    <WalletCards size={15} />
                    Add spend
                  </button>
                </div>

                {spends.length === 0 ? (
                  <div className="rounded-xl border border-white/5 bg-background/50 px-4 py-5 text-sm text-gray-500">
                    Spend list is empty.
                  </div>
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-white/5">
                    <table className="min-w-[720px] w-full text-left text-sm">
                      <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-gray-500">
                        <tr>
                          <th className="px-4 py-3">Date</th>
                          <th className="px-4 py-3">Amount</th>
                          <th className="px-4 py-3">Source</th>
                          <th className="px-4 py-3">Comment</th>
                          <th className="px-4 py-3 text-right">Actions</th>
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
                              {spend.comment || 'No comment'}
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex justify-end gap-2">
                                <button
                                  type="button"
                                  onClick={() => openSpendModal(detailLink, spend)}
                                  className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-gray-200 transition hover:border-accent-300/50 hover:text-white"
                                >
                                  Edit
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
                )}
              </div>
            </div>
          ) : null}
        </Modal>
      ) : null}

      {spendLink ? (
        <Modal
          title={spendMode === 'edit' ? 'Edit spend' : 'Add spend'}
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
                Date
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
                Amount
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
                Currency
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
                Comment
              </span>
              <textarea
                value={spendComment}
                onChange={(event) => setSpendComment(event.target.value)}
                rows={3}
                className="max-h-32 w-full resize-none overflow-y-auto rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                placeholder="Optional comment"
              />
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={closeSpendModal}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!spendDate || !spendAmount || isSavingSpend}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSavingSpend ? <LoaderCircle size={16} className="animate-spin" /> : <DollarSign size={16} />}
                Save
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </section>
  )
}

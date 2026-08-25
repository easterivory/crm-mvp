import axios from 'axios'
import {
  ArrowRight,
  BadgeDollarSign,
  Calculator,
  Database,
  LoaderCircle,
  RefreshCcw,
  TrendingUp,
  WalletCards,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { fetchProjectCalculatorSnapshot } from '../features/analytics'
import type { ProjectCalculatorSnapshot } from '../features/analytics'
import { useNotificationStore, useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type ProjectFormat = 'submission' | 'gambling'
type RevenueMode = 'total' | 'events'
type CurrencyCode = 'USD' | 'EUR' | 'RUB' | 'KZT'

type NumericField =
  | 'spend'
  | 'clicks'
  | 'starts'
  | 'channelJoins'
  | 'leads'
  | 'submitted'
  | 'registrations'
  | 'firstDeposits'
  | 'redeposits'
  | 'totalRevenue'
  | 'submissionPayout'
  | 'registrationPayout'
  | 'firstDepositPayout'
  | 'redepositPayout'

type CalculatorValues = Record<NumericField, string>

type CalculatorDraft = {
  version: 1
  projectFormat: ProjectFormat
  revenueMode: RevenueMode
  currency: CurrencyCode
  dateFrom: string
  dateTo: string
  values: CalculatorValues
}

const DRAFT_KEY_PREFIX = 'crm:project-calculator:'
const CURRENCIES: CurrencyCode[] = ['USD', 'EUR', 'RUB', 'KZT']
const NUMERIC_FIELDS: NumericField[] = [
  'spend',
  'clicks',
  'starts',
  'channelJoins',
  'leads',
  'submitted',
  'registrations',
  'firstDeposits',
  'redeposits',
  'totalRevenue',
  'submissionPayout',
  'registrationPayout',
  'firstDepositPayout',
  'redepositPayout',
]

const DEFAULT_VALUES: CalculatorValues = {
  spend: '0',
  clicks: '0',
  starts: '0',
  channelJoins: '0',
  leads: '0',
  submitted: '0',
  registrations: '0',
  firstDeposits: '0',
  redeposits: '0',
  totalRevenue: '0',
  submissionPayout: '0',
  registrationPayout: '0',
  firstDepositPayout: '0',
  redepositPayout: '0',
}

function isoDateDaysAgo(days: number) {
  const value = new Date()
  value.setDate(value.getDate() - days)
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function toNumber(value: string | number | null | undefined) {
  const normalized = typeof value === 'string'
    ? value.replace(/\s/g, '').replace(',', '.')
    : value
  const parsed = Number(normalized ?? 0)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}

function safeRatio(numerator: number, denominator: number) {
  return denominator > 0 ? numerator / denominator : null
}

function formatCount(value: number) {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)
}

function formatPercent(value: number | null) {
  if (value === null) {
    return '—'
  }
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)}%`
}

function formatMoney(value: number | null, currency: CurrencyCode) {
  if (value === null) {
    return '—'
  }
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value)
}

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (error.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return 'Не удалось загрузить статистику проекта.'
}

function readDraft(projectId: string): CalculatorDraft | null {
  const raw = localStorage.getItem(`${DRAFT_KEY_PREFIX}${projectId}`)
  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as Partial<CalculatorDraft>
    const values = { ...DEFAULT_VALUES }
    if (parsed.values && typeof parsed.values === 'object') {
      for (const field of NUMERIC_FIELDS) {
        const value = parsed.values[field]
        if (typeof value === 'string') {
          values[field] = value
        }
      }
    }

    return {
      version: 1,
      projectFormat: parsed.projectFormat === 'gambling' ? 'gambling' : 'submission',
      revenueMode: parsed.revenueMode === 'events' ? 'events' : 'total',
      currency: CURRENCIES.includes(parsed.currency as CurrencyCode)
        ? parsed.currency as CurrencyCode
        : 'USD',
      dateFrom: typeof parsed.dateFrom === 'string' ? parsed.dateFrom : isoDateDaysAgo(29),
      dateTo: typeof parsed.dateTo === 'string' ? parsed.dateTo : isoDateDaysAgo(0),
      values,
    }
  } catch {
    localStorage.removeItem(`${DRAFT_KEY_PREFIX}${projectId}`)
    return null
  }
}

type NumberFieldProps = {
  label: string
  value: string
  onChange: (value: string) => void
  step?: string
  suffix?: string
}

function NumberField({ label, value, onChange, step = '1', suffix }: NumberFieldProps) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-sm font-medium text-gray-300">{label}</span>
      <span className="relative block">
        <input
          type="number"
          min="0"
          step={step}
          inputMode={step === '1' ? 'numeric' : 'decimal'}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={`h-11 w-full rounded-lg border border-white/10 bg-[#0B0F19] pl-3 text-base text-white outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-300/20 ${suffix ? 'pr-14' : 'pr-3'}`}
        />
        {suffix ? (
          <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs font-medium text-gray-500">
            {suffix}
          </span>
        ) : null}
      </span>
    </label>
  )
}

type MetricTileProps = {
  label: string
  value: string
  tone?: 'neutral' | 'positive' | 'negative' | 'accent'
  detail?: string
}

function MetricTile({ label, value, tone = 'neutral', detail }: MetricTileProps) {
  const toneClass = {
    neutral: 'text-white',
    positive: 'text-emerald-300',
    negative: 'text-rose-300',
    accent: 'text-cyan-300',
  }[tone]

  return (
    <article className="min-w-0 rounded-lg border border-white/10 bg-white/[0.025] p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{label}</p>
      <p className={`mt-2 break-words text-lg font-semibold sm:text-xl ${toneClass}`} title={value}>{value}</p>
      {detail ? <p className="mt-1 text-xs text-gray-500">{detail}</p> : null}
    </article>
  )
}

type ConversionRowProps = {
  from: string
  to: string
  value: number | null
}

function ConversionRow({ from, to, value }: ConversionRowProps) {
  const width = value === null ? 0 : Math.min(100, Math.max(0, value))
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2 text-sm text-gray-300">
          <span className="truncate">{from}</span>
          <ArrowRight size={14} className="shrink-0 text-gray-600" />
          <span className="truncate">{to}</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
          <div
            className="h-full rounded-full bg-cyan-400 transition-[width] duration-300"
            style={{ width: `${width}%` }}
          />
        </div>
      </div>
      <span className="min-w-16 text-right text-sm font-semibold text-white">
        {formatPercent(value)}
      </span>
    </div>
  )
}

export default function ProjectCalculatorPage() {
  const currentUser = useAuthStore((state) => state.user)
  const notify = useNotificationStore((state) => state.notify)
  const { selectedProjectId } = useProjectBotSelection()
  const activeProjectId = selectedProjectId ?? currentUser?.project_id ?? null

  const [values, setValues] = useState<CalculatorValues>({ ...DEFAULT_VALUES })
  const [projectFormat, setProjectFormat] = useState<ProjectFormat>('submission')
  const [revenueMode, setRevenueMode] = useState<RevenueMode>('total')
  const [currency, setCurrency] = useState<CurrencyCode>('USD')
  const [dateFrom, setDateFrom] = useState(() => isoDateDaysAgo(29))
  const [dateTo, setDateTo] = useState(() => isoDateDaysAgo(0))
  const [draftProjectId, setDraftProjectId] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<ProjectCalculatorSnapshot | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!activeProjectId) {
      setDraftProjectId(null)
      setSnapshot(null)
      return
    }

    const draft = readDraft(activeProjectId)
    setValues(draft?.values ?? { ...DEFAULT_VALUES })
    setProjectFormat(draft?.projectFormat ?? 'submission')
    setRevenueMode(draft?.revenueMode ?? 'total')
    setCurrency(draft?.currency ?? 'USD')
    setDateFrom(draft?.dateFrom ?? isoDateDaysAgo(29))
    setDateTo(draft?.dateTo ?? isoDateDaysAgo(0))
    setSnapshot(null)
    setError('')
    setDraftProjectId(activeProjectId)
  }, [activeProjectId])

  useEffect(() => {
    if (!activeProjectId || draftProjectId !== activeProjectId) {
      return
    }

    const draft: CalculatorDraft = {
      version: 1,
      projectFormat,
      revenueMode,
      currency,
      dateFrom,
      dateTo,
      values,
    }
    localStorage.setItem(`${DRAFT_KEY_PREFIX}${activeProjectId}`, JSON.stringify(draft))
  }, [
    activeProjectId,
    currency,
    dateFrom,
    dateTo,
    draftProjectId,
    projectFormat,
    revenueMode,
    values,
  ])

  const setField = useCallback((field: NumericField, value: string) => {
    setValues((current) => ({ ...current, [field]: value }))
  }, [])

  const loadStatistics = useCallback(async () => {
    if (!activeProjectId) {
      notify({
        tone: 'warning',
        title: 'Проект не выбран',
        message: 'Выберите проект в верхней панели.',
      })
      return
    }
    if (!dateFrom || !dateTo || dateFrom > dateTo) {
      notify({
        tone: 'warning',
        title: 'Проверьте период',
        message: 'Дата начала должна быть не позже даты окончания.',
      })
      return
    }

    setIsLoading(true)
    setError('')
    try {
      const result = await fetchProjectCalculatorSnapshot({
        project_id: activeProjectId,
        date_from: dateFrom,
        date_to: dateTo,
      })
      setSnapshot(result)
      setProjectFormat(result.project_format)
      setValues((current) => ({
        ...current,
        spend: String(toNumber(result.spend)),
        clicks: String(result.clicks),
        starts: String(result.starts),
        channelJoins: String(result.channel_joins),
        leads: String(result.leads),
        submitted: String(result.submitted_leads),
        registrations: String(result.registrations),
        firstDeposits: String(result.first_deposits),
        redeposits: String(result.redeposits),
      }))
      notify({
        tone: 'success',
        title: 'Статистика загружена',
        message: `${result.project_name}: ${result.date_from} — ${result.date_to}`,
      })
    } catch (requestError) {
      const message = errorMessage(requestError)
      setError(message)
      notify({ tone: 'error', title: 'Ошибка загрузки', message })
    } finally {
      setIsLoading(false)
    }
  }, [activeProjectId, dateFrom, dateTo, notify])

  const resetDraft = useCallback(() => {
    setValues({ ...DEFAULT_VALUES })
    setProjectFormat('submission')
    setRevenueMode('total')
    setCurrency('USD')
    setSnapshot(null)
    setError('')
  }, [])

  const calculations = useMemo(() => {
    const spend = toNumber(values.spend)
    const clicks = toNumber(values.clicks)
    const starts = toNumber(values.starts)
    const channelJoins = toNumber(values.channelJoins)
    const leads = toNumber(values.leads)
    const submitted = toNumber(values.submitted)
    const registrations = toNumber(values.registrations)
    const firstDeposits = toNumber(values.firstDeposits)
    const redeposits = toNumber(values.redeposits)

    const eventRevenue = projectFormat === 'submission'
      ? submitted * toNumber(values.submissionPayout)
      : registrations * toNumber(values.registrationPayout)
        + firstDeposits * toNumber(values.firstDepositPayout)
        + redeposits * toNumber(values.redepositPayout)
    const revenue = revenueMode === 'events' ? eventRevenue : toNumber(values.totalRevenue)
    const profit = revenue - spend
    const primaryCount = projectFormat === 'submission' ? submitted : firstDeposits

    return {
      spend,
      revenue,
      profit,
      roi: spend > 0 ? (profit / spend) * 100 : null,
      roas: spend > 0 ? revenue / spend : null,
      margin: revenue > 0 ? (profit / revenue) * 100 : null,
      cpc: safeRatio(spend, clicks),
      cps: safeRatio(spend, starts),
      cpl: safeRatio(spend, leads),
      cpsl: safeRatio(spend, submitted),
      cpr: safeRatio(spend, registrations),
      cpfd: safeRatio(spend, firstDeposits),
      cprd: safeRatio(spend, redeposits),
      breakEven: safeRatio(spend, primaryCount),
      revenuePerResult: safeRatio(revenue, primaryCount),
      clickToStart: safeRatio(starts * 100, clicks),
      clickToChannelJoin: safeRatio(channelJoins * 100, clicks),
      startToLead: safeRatio(leads * 100, starts),
      leadToSubmitted: safeRatio(submitted * 100, leads),
      startToRegistration: safeRatio(registrations * 100, starts),
      registrationToDeposit: safeRatio(firstDeposits * 100, registrations),
      redepositsPerDeposit: safeRatio(redeposits * 100, firstDeposits),
      primaryCount,
    }
  }, [projectFormat, revenueMode, values])

  const profitTone = calculations.profit > 0
    ? 'positive'
    : calculations.profit < 0
      ? 'negative'
      : 'neutral'

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/85 text-gray-200 shadow-card">
      <header className="shrink-0 border-b border-white/10 px-4 py-4 sm:px-5 lg:flex lg:items-end lg:justify-between lg:gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
            <Calculator size={16} />
            Экономика проекта
          </div>
          <h1 className="mt-2 text-2xl font-semibold text-white">Калькулятор математики</h1>
          <p className="mt-1 text-sm text-gray-500">План-факт по выбранному проекту.</p>
        </div>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end lg:mt-0">
          <label className="block min-w-36">
            <span className="mb-1 block text-xs font-medium text-gray-500">С</span>
            <input
              type="date"
              value={dateFrom}
              max={dateTo}
              onChange={(event) => setDateFrom(event.target.value)}
              className="h-10 w-full rounded-lg border border-white/10 bg-[#0B0F19] px-3 text-base text-white outline-none focus:border-cyan-300/60 sm:text-sm"
            />
          </label>
          <label className="block min-w-36">
            <span className="mb-1 block text-xs font-medium text-gray-500">По</span>
            <input
              type="date"
              value={dateTo}
              min={dateFrom}
              onChange={(event) => setDateTo(event.target.value)}
              className="h-10 w-full rounded-lg border border-white/10 bg-[#0B0F19] px-3 text-base text-white outline-none focus:border-cyan-300/60 sm:text-sm"
            />
          </label>
          <button
            type="button"
            onClick={() => void loadStatistics()}
            disabled={isLoading || !activeProjectId}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-[#071018] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : <Database size={16} />}
            Загрузить статистику
          </button>
          <button
            type="button"
            onClick={resetDraft}
            title="Очистить расчёт"
            aria-label="Очистить расчёт"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-gray-400 transition hover:border-white/20 hover:text-white"
          >
            <RefreshCcw size={16} />
          </button>
        </div>
      </header>

      <div className="touch-scroll min-h-0 flex-1 overflow-y-auto">
        {snapshot ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-emerald-300/15 bg-emerald-400/[0.05] px-4 py-2.5 text-xs text-emerald-100 sm:px-5">
            <span className="font-semibold">{snapshot.project_name}</span>
            <span className="text-emerald-200/60">{snapshot.date_from} — {snapshot.date_to}</span>
          </div>
        ) : null}
        {error ? (
          <div className="border-b border-rose-300/15 bg-rose-400/[0.06] px-4 py-2.5 text-sm text-rose-200 sm:px-5">
            {error}
          </div>
        ) : null}

        <div className="grid min-w-0 gap-0 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
          <div className="min-w-0 border-b border-white/10 xl:border-b-0 xl:border-r">
            <div className="border-b border-white/10 px-4 py-5 sm:px-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-white">Исходные данные</h2>
                </div>
                <div className="inline-flex w-full rounded-lg border border-white/10 bg-[#0B0F19] p-1 sm:w-auto">
                  <button
                    type="button"
                    onClick={() => setProjectFormat('submission')}
                    aria-pressed={projectFormat === 'submission'}
                    className={`h-9 flex-1 rounded-md px-4 text-sm font-medium transition sm:flex-none ${
                      projectFormat === 'submission'
                        ? 'bg-white/10 text-white'
                        : 'text-gray-500 hover:text-gray-200'
                    }`}
                  >
                    Подача
                  </button>
                  <button
                    type="button"
                    onClick={() => setProjectFormat('gambling')}
                    aria-pressed={projectFormat === 'gambling'}
                    className={`h-9 flex-1 rounded-md px-4 text-sm font-medium transition sm:flex-none ${
                      projectFormat === 'gambling'
                        ? 'bg-white/10 text-white'
                        : 'text-gray-500 hover:text-gray-200'
                    }`}
                  >
                    Gambling
                  </button>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <NumberField label="Расход" value={values.spend} step="0.01" suffix={currency} onChange={(value) => setField('spend', value)} />
                <NumberField label="Клики" value={values.clicks} onChange={(value) => setField('clicks', value)} />
                <NumberField label="Старты бота" value={values.starts} onChange={(value) => setField('starts', value)} />
                <NumberField label="Подписки на канал" value={values.channelJoins} onChange={(value) => setField('channelJoins', value)} />
                <NumberField label="Лиды" value={values.leads} onChange={(value) => setField('leads', value)} />
                {projectFormat === 'submission' ? (
                  <NumberField label="Подано лидов" value={values.submitted} onChange={(value) => setField('submitted', value)} />
                ) : null}
              </div>

              {projectFormat === 'gambling' ? (
                <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <NumberField label="Регистрации" value={values.registrations} onChange={(value) => setField('registrations', value)} />
                  <NumberField label="Первые депозиты (FD)" value={values.firstDeposits} onChange={(value) => setField('firstDeposits', value)} />
                  <NumberField label="Редепозиты (RD)" value={values.redeposits} onChange={(value) => setField('redeposits', value)} />
                </div>
              ) : null}
            </div>

            <div className="px-4 py-5 sm:px-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-white">Доход</h2>
                </div>
                <div className="flex gap-2">
                  <select
                    value={currency}
                    onChange={(event) => setCurrency(event.target.value as CurrencyCode)}
                    className="h-10 rounded-lg border border-white/10 bg-[#0B0F19] px-3 text-base text-white outline-none focus:border-cyan-300/60 sm:text-sm"
                    aria-label="Валюта расчёта"
                  >
                    {CURRENCIES.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                  <div className="inline-flex rounded-lg border border-white/10 bg-[#0B0F19] p-1">
                    <button
                      type="button"
                      onClick={() => setRevenueMode('total')}
                      aria-pressed={revenueMode === 'total'}
                      className={`h-8 rounded-md px-3 text-xs font-medium transition ${
                        revenueMode === 'total' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-200'
                      }`}
                    >
                      Итог
                    </button>
                    <button
                      type="button"
                      onClick={() => setRevenueMode('events')}
                      aria-pressed={revenueMode === 'events'}
                      className={`h-8 rounded-md px-3 text-xs font-medium transition ${
                        revenueMode === 'events' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-200'
                      }`}
                    >
                      Выплаты
                    </button>
                  </div>
                </div>
              </div>

              <div className="mt-5">
                {revenueMode === 'total' ? (
                  <div className="max-w-sm">
                    <NumberField label="Общий доход" value={values.totalRevenue} step="0.01" suffix={currency} onChange={(value) => setField('totalRevenue', value)} />
                  </div>
                ) : projectFormat === 'submission' ? (
                  <div className="max-w-sm">
                    <NumberField label="Выплата за поданного лида" value={values.submissionPayout} step="0.01" suffix={currency} onChange={(value) => setField('submissionPayout', value)} />
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <NumberField label="Выплата за регистрацию" value={values.registrationPayout} step="0.01" suffix={currency} onChange={(value) => setField('registrationPayout', value)} />
                    <NumberField label="Выплата за FD" value={values.firstDepositPayout} step="0.01" suffix={currency} onChange={(value) => setField('firstDepositPayout', value)} />
                    <NumberField label="Выплата за RD" value={values.redepositPayout} step="0.01" suffix={currency} onChange={(value) => setField('redepositPayout', value)} />
                  </div>
                )}
              </div>
            </div>
          </div>

          <aside className="min-w-0">
            <div className="border-b border-white/10 px-4 py-5 sm:px-5">
              <div className="flex items-center gap-2">
                <WalletCards size={17} className="text-cyan-300" />
                <h2 className="text-base font-semibold text-white">Финансовый результат</h2>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <MetricTile label="Доход" value={formatMoney(calculations.revenue, currency)} tone="accent" />
                <MetricTile label="Прибыль" value={formatMoney(calculations.profit, currency)} tone={profitTone} />
                <MetricTile label="ROI" value={formatPercent(calculations.roi)} detail="Прибыль к расходу" />
                <MetricTile label="ROAS" value={calculations.roas === null ? '—' : `${formatCount(calculations.roas)}x`} detail="Доход к расходу" />
                <MetricTile label="Маржа" value={formatPercent(calculations.margin)} />
                <MetricTile
                  label="Точка безубыточности"
                  value={formatMoney(calculations.breakEven, currency)}
                  detail={projectFormat === 'submission' ? 'за поданного' : 'за FD'}
                />
              </div>
            </div>

            <div className="border-b border-white/10 px-4 py-5 sm:px-5">
              <div className="flex items-center gap-2">
                <BadgeDollarSign size={17} className="text-emerald-300" />
                <h2 className="text-base font-semibold text-white">Стоимость результата</h2>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <MetricTile label="CPC" value={formatMoney(calculations.cpc, currency)} />
                <MetricTile label="Стоимость старта" value={formatMoney(calculations.cps, currency)} />
                <MetricTile label="CPL" value={formatMoney(calculations.cpl, currency)} />
                {projectFormat === 'submission' ? (
                  <MetricTile label="Стоимость подачи" value={formatMoney(calculations.cpsl, currency)} />
                ) : (
                  <>
                    <MetricTile label="CPR" value={formatMoney(calculations.cpr, currency)} />
                    <MetricTile label="CPFD" value={formatMoney(calculations.cpfd, currency)} />
                    <MetricTile label="CPRD" value={formatMoney(calculations.cprd, currency)} />
                  </>
                )}
                <MetricTile
                  label="Доход на результат"
                  value={formatMoney(calculations.revenuePerResult, currency)}
                  detail={`${formatCount(calculations.primaryCount)} ${projectFormat === 'submission' ? 'подано' : 'FD'}`}
                />
              </div>
            </div>

            <div className="px-4 py-5 sm:px-5">
              <div className="flex items-center gap-2">
                <TrendingUp size={17} className="text-amber-300" />
                <h2 className="text-base font-semibold text-white">Конверсии</h2>
              </div>
              <div className="mt-2 divide-y divide-white/[0.06]">
                <ConversionRow from="Клик" to="Старт" value={calculations.clickToStart} />
                {toNumber(values.channelJoins) > 0 ? (
                  <ConversionRow from="Клик" to="Подписка" value={calculations.clickToChannelJoin} />
                ) : null}
                <ConversionRow from="Старт" to="Лид" value={calculations.startToLead} />
                {projectFormat === 'submission' ? (
                  <ConversionRow from="Лид" to="Подача" value={calculations.leadToSubmitted} />
                ) : (
                  <>
                    <ConversionRow from="Старт" to="Регистрация" value={calculations.startToRegistration} />
                    <ConversionRow from="Регистрация" to="FD" value={calculations.registrationToDeposit} />
                    <ConversionRow from="FD" to="RD" value={calculations.redepositsPerDeposit} />
                  </>
                )}
              </div>
            </div>
          </aside>
        </div>
      </div>
    </section>
  )
}

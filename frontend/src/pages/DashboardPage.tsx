import axios from 'axios'
import { BarChart3, LoaderCircle, RefreshCcw, ShieldAlert, UsersRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { fetchBuyerPerformance } from '../features/buyers'
import type { BuyerPerformance } from '../features/buyers'
import { fetchManagerPerformance } from '../features/analytics'
import type { ManagerPerformance } from '../features/analytics'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

function getErrorMessage(err: unknown, fallback: string) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function toNumber(value: number | string | null | undefined) {
  const parsed = typeof value === 'number' ? value : Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function money(value: number | string | null | undefined) {
  return `$${toNumber(value).toFixed(2)}`
}

function percent(value: number | string | null | undefined) {
  return `${toNumber(value).toFixed(1)}%`
}

function isoDateDaysAgo(days: number) {
  const value = new Date()
  value.setDate(value.getDate() - days)
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export default function DashboardPage() {
  const currentUser = useAuthStore((state) => state.user)
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const [items, setItems] = useState<BuyerPerformance[]>([])
  const [managers, setManagers] = useState<ManagerPerformance[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [dateFrom, setDateFrom] = useState(() => isoDateDaysAgo(29))
  const [dateTo, setDateTo] = useState(() => isoDateDaysAgo(0))

  const activeProjectId = selectedProjectId ?? currentUser?.project_id ?? null
  const canViewBuyerAnalytics =
    currentUser?.role_name === 'super_admin' || currentUser?.role_name === 'admin'

  const loadData = useCallback(async () => {
    if (!activeProjectId || !canViewBuyerAnalytics) {
      setItems([])
      setManagers([])
      return
    }

    setIsLoading(true)
    setError('')
    try {
      const selectedBotId = selectedBotIds.length === 1 ? selectedBotIds[0] : undefined
      const [buyerResult, managerResult] = await Promise.allSettled([
        fetchBuyerPerformance(activeProjectId, {
          date_from: dateFrom,
          date_to: dateTo,
          bot_id: selectedBotId,
        }),
        fetchManagerPerformance({
          project_id: activeProjectId,
          date_from: dateFrom,
          date_to: dateTo,
        }),
      ])
      setItems(buyerResult.status === 'fulfilled' ? buyerResult.value : [])
      setManagers(managerResult.status === 'fulfilled' ? managerResult.value : [])

      const errors: string[] = []
      if (buyerResult.status === 'rejected') {
        errors.push(
          `Баеры: ${getErrorMessage(buyerResult.reason, 'не удалось загрузить данные.')}`,
        )
      }
      if (managerResult.status === 'rejected') {
        errors.push(
          `Менеджеры: ${getErrorMessage(managerResult.reason, 'не удалось загрузить данные.')}`,
        )
      }
      setError(errors.join(' '))
    } catch (err) {
      setItems([])
      setManagers([])
      setError(getErrorMessage(err, 'Не удалось загрузить аналитику команды.'))
    } finally {
      setIsLoading(false)
    }
  }, [activeProjectId, canViewBuyerAnalytics, dateFrom, dateTo, selectedBotIds])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const sortedItems = useMemo(
    () => [...items].sort((a, b) => toNumber(b.total_spend) - toNumber(a.total_spend)),
    [items],
  )

  const chartData = useMemo(
    () =>
      sortedItems.map((item) => ({
        name: item.name,
        spend: toNumber(item.total_spend),
        leads: item.leads,
      })),
    [sortedItems],
  )
  const buyerChartHeight = Math.min(520, Math.max(220, chartData.length * 52 + 48))

  const totals = useMemo(
    () =>
      sortedItems.reduce(
        (acc, item) => ({
          spend: acc.spend + toNumber(item.total_spend),
          clicks: acc.clicks + item.clicks,
          leads: acc.leads + item.leads,
          submitted: acc.submitted + item.submitted_leads,
        }),
        { spend: 0, clicks: 0, leads: 0, submitted: 0 },
      ),
    [sortedItems],
  )

  const managerTotals = useMemo(
    () =>
      managers.reduce(
        (acc, manager) => ({
          taken: acc.taken + manager.chats_taken,
          submitted: acc.submitted + manager.submitted_leads,
          valid: acc.valid + manager.valid_leads,
          pushed: acc.pushed + manager.funnels_pushed,
          returned: acc.returned + manager.returned_to_funnel,
        }),
        { taken: 0, submitted: 0, valid: 0, pushed: 0, returned: 0 },
      ),
    [managers],
  )

  if (!canViewBuyerAnalytics) {
    return (
      <section className="flex h-full min-h-0 items-center justify-center rounded-xl border border-white/5 bg-surface/80 p-6 text-gray-200 shadow-card">
        <div className="max-w-xl text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl border border-amber-300/25 bg-amber-400/10 text-amber-100">
            <ShieldAlert size={22} />
          </div>
          <h1 className="mt-4 text-2xl font-semibold text-white">Аналитика доступна администраторам</h1>
          <p className="mt-2 text-sm leading-6 text-gray-500">
            Данные эффективности баеров и менеджеров видят только Admin и Super Admin.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-surface/80 text-gray-200 shadow-card">
      <div className="flex shrink-0 flex-col gap-4 border-b border-white/10 px-5 py-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">
            <BarChart3 size={16} />
            Аналитика команды
          </div>
          <h1 className="mt-3 text-2xl font-semibold text-white">Эффективность команды</h1>
          <p className="mt-1 text-sm text-gray-500">
            Результаты баеров и качество обработки лидов менеджерами выбранного проекта.
          </p>
        </div>
        <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-end">
          <label className="block min-w-36">
            <span className="mb-1 block text-xs font-medium text-gray-500">С</span>
            <input
              type="date"
              value={dateFrom}
              max={dateTo}
              onChange={(event) => setDateFrom(event.target.value)}
              className="h-10 w-full rounded-lg border border-white/10 bg-background/70 px-3 text-base text-gray-100 outline-none ring-cyan-300/40 focus:ring-2 sm:text-sm"
            />
          </label>
          <label className="block min-w-36">
            <span className="mb-1 block text-xs font-medium text-gray-500">По</span>
            <input
              type="date"
              value={dateTo}
              min={dateFrom}
              onChange={(event) => setDateTo(event.target.value)}
              className="h-10 w-full rounded-lg border border-white/10 bg-background/70 px-3 text-base text-gray-100 outline-none ring-cyan-300/40 focus:ring-2 sm:text-sm"
            />
          </label>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={isLoading || !activeProjectId || !dateFrom || !dateTo}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-gray-100 transition hover:border-cyan-300/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCcw size={16} className={isLoading ? 'animate-spin' : undefined} />
            Обновить
          </button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {!activeProjectId ? (
          <div className="rounded-xl border border-white/10 bg-white/[0.02] p-5 text-sm text-gray-500">
            Выберите проект в верхнем селекторе, чтобы загрузить аналитику команды.
          </div>
        ) : null}

        {error ? (
          <div className="mb-5 rounded-xl border border-red-500/30 bg-red-950/40 px-4 py-3 text-sm text-red-100">
            {error}
          </div>
        ) : null}

        <div className="grid gap-3 md:grid-cols-4">
          <MetricCard label="Расход" value={money(totals.spend)} tone="cyan" />
          <MetricCard label="Клики" value={String(totals.clicks)} tone="zinc" />
          <MetricCard label="Лиды" value={String(totals.leads)} tone="emerald" />
          <MetricCard label="Подано" value={String(totals.submitted)} tone="violet" />
        </div>

        <div className="mt-5 overflow-x-auto rounded-xl border border-white/10 bg-white/[0.02]">
          <table className="min-w-[980px] w-full text-left text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-3">Имя баера</th>
                <th className="px-4 py-3 text-right">Расход</th>
                <th className="px-4 py-3 text-right">Клики</th>
                <th className="px-4 py-3 text-right">Лиды</th>
                <th className="px-4 py-3 text-right">CPL</th>
                <th className="px-4 py-3 text-right">Подано лидов</th>
                <th className="px-4 py-3 text-right">Конверсия в подачу</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-gray-500">
                    <LoaderCircle size={18} className="mr-2 inline animate-spin" />
                    Загрузка аналитики
                  </td>
                </tr>
              ) : sortedItems.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-gray-500">
                    По выбранному проекту пока нет баеров.
                  </td>
                </tr>
              ) : (
                sortedItems.map((item) => (
                  <tr key={item.buyer_id}>
                    <td className="px-4 py-3">
                      <div className="font-semibold text-white">{item.name}</div>
                      <div className="mt-0.5 text-xs text-gray-500">{item.email}</div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-cyan-100">
                      {money(item.total_spend)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-300">
                      {item.clicks}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-emerald-200">
                      {item.leads}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-gray-200">
                      {money(item.cpl)}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-violet-200">
                      {item.submitted_leads}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-amber-200">
                      {percent(item.submitted_conversion_percent)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-white">Показатели по баерам</h2>
              <p className="mt-1 text-xs text-gray-500">
                Результат и затраты за выбранный период.
              </p>
            </div>
          </div>
          {chartData.length === 0 ? (
            <div className="flex h-56 items-center justify-center text-sm text-gray-500">
              Нет данных для графиков.
            </div>
          ) : (
            <div className="grid divide-y divide-white/10 lg:grid-cols-2 lg:divide-x lg:divide-y-0">
              <section className="min-w-0 pb-4 lg:pb-0 lg:pr-5">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-sm font-medium text-gray-100">Лиды</h3>
                  <span className="text-xs text-gray-500">Количество</span>
                </div>
                <div style={{ height: buyerChartHeight }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={chartData}
                      layout="vertical"
                      margin={{ top: 4, right: 64, bottom: 8, left: 4 }}
                    >
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" horizontal={false} />
                      <XAxis
                        type="number"
                        allowDecimals={false}
                        stroke="#6B7280"
                        tick={{ fill: '#9CA3AF', fontSize: 12 }}
                        tickLine={false}
                        axisLine={{ stroke: 'rgba(255,255,255,0.12)' }}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={104}
                        stroke="#6B7280"
                        tick={{ fill: '#9CA3AF', fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip
                        cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                        contentStyle={{
                          background: '#0B0F19',
                          border: '1px solid rgba(255,255,255,0.12)',
                          borderRadius: 8,
                          color: '#E5E7EB',
                        }}
                        formatter={(value) => [String(value), 'Лиды']}
                      />
                      <Bar
                        dataKey="leads"
                        name="Лиды"
                        fill="#34D399"
                        maxBarSize={28}
                        radius={[0, 6, 6, 0]}
                      >
                        <LabelList
                          dataKey="leads"
                          position="right"
                          fill="#A7F3D0"
                          fontSize={12}
                        />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>

              <section className="min-w-0 pt-4 lg:pl-5 lg:pt-0">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <h3 className="text-sm font-medium text-gray-100">Расход</h3>
                  <span className="text-xs text-gray-500">USD</span>
                </div>
                <div style={{ height: buyerChartHeight }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={chartData}
                      layout="vertical"
                      margin={{ top: 4, right: 76, bottom: 8, left: 4 }}
                    >
                      <CartesianGrid stroke="rgba(255,255,255,0.08)" horizontal={false} />
                      <XAxis
                        type="number"
                        stroke="#6B7280"
                        tick={{ fill: '#9CA3AF', fontSize: 12 }}
                        tickFormatter={(value) => `$${toNumber(value).toFixed(0)}`}
                        tickLine={false}
                        axisLine={{ stroke: 'rgba(255,255,255,0.12)' }}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={104}
                        stroke="#6B7280"
                        tick={{ fill: '#9CA3AF', fontSize: 12 }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip
                        cursor={{ fill: 'rgba(255,255,255,0.04)' }}
                        contentStyle={{
                          background: '#0B0F19',
                          border: '1px solid rgba(255,255,255,0.12)',
                          borderRadius: 8,
                          color: '#E5E7EB',
                        }}
                        formatter={(value) => [money(String(value)), 'Расход']}
                      />
                      <Bar
                        dataKey="spend"
                        name="Расход"
                        fill="#22D3EE"
                        maxBarSize={28}
                        radius={[0, 6, 6, 0]}
                      >
                        <LabelList
                          dataKey="spend"
                          position="right"
                          fill="#A5F3FC"
                          fontSize={12}
                          formatter={(value) => money(String(value))}
                        />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </section>
            </div>
          )}
        </div>

        <section className="mt-5 rounded-xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <UsersRound size={18} className="text-violet-300" />
                <h2 className="font-semibold text-white">Эффективность менеджеров</h2>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                Взятые чаты, подачи, подтверждённые партнёром лиды и возвраты в воронку.
              </p>
            </div>
            <p className="max-w-md text-xs leading-5 text-gray-500">
              Валид учитывается после обратной связи партнёра по подаче конкретного менеджера.
            </p>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Взято чатов" value={String(managerTotals.taken)} tone="zinc" />
            <MetricCard label="Подано" value={String(managerTotals.submitted)} tone="violet" />
            <MetricCard label="Валидных" value={String(managerTotals.valid)} tone="emerald" />
            <MetricCard label="Доведено воронкой" value={String(managerTotals.pushed)} tone="cyan" />
          </div>

          <div className="mt-4 hidden overflow-x-auto rounded-xl border border-white/10 lg:block">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3">Менеджер</th>
                  <th className="px-4 py-3 text-right">Взял</th>
                  <th className="px-4 py-3 text-right">Подал</th>
                  <th className="px-4 py-3 text-right">Валид</th>
                  <th className="px-4 py-3 text-right">Взял → подал</th>
                  <th className="px-4 py-3 text-right">Подал → валид</th>
                  <th className="px-4 py-3 text-right">Взял → валид</th>
                  <th className="px-4 py-3 text-right">Довёл воронкой</th>
                  <th className="px-4 py-3 text-right">Вернул</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {isLoading ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-10 text-center text-gray-500">
                      <LoaderCircle size={18} className="mr-2 inline animate-spin" />
                      Загрузка аналитики
                    </td>
                  </tr>
                ) : managers.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-10 text-center text-gray-500">
                      За выбранный период нет действий менеджеров.
                    </td>
                  </tr>
                ) : (
                  managers.map((manager) => (
                    <tr key={manager.manager_id}>
                      <td className="px-4 py-3">
                        <div className="font-semibold text-white">{manager.name}</div>
                        <div className="mt-0.5 text-xs text-gray-500">
                          {manager.handler_code ? `#${manager.handler_code} · ` : ''}{manager.email}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-gray-200">{manager.chats_taken}</td>
                      <td className="px-4 py-3 text-right font-mono text-violet-200">{manager.submitted_leads}</td>
                      <td className="px-4 py-3 text-right font-mono text-emerald-200">{manager.valid_leads}</td>
                      <td className="px-4 py-3 text-right text-cyan-100">{percent(manager.taken_to_submitted_percent)}</td>
                      <td className="px-4 py-3 text-right text-cyan-100">{percent(manager.submitted_to_valid_percent)}</td>
                      <td className="px-4 py-3 text-right text-cyan-100">{percent(manager.taken_to_valid_percent)}</td>
                      <td className="px-4 py-3 text-right font-mono text-cyan-100">{manager.funnels_pushed}</td>
                      <td className="px-4 py-3 text-right font-mono text-gray-300">{manager.returned_to_funnel}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-4 grid gap-3 lg:hidden">
            {!isLoading && managers.length === 0 ? (
              <div className="rounded-xl border border-white/10 px-4 py-8 text-center text-sm text-gray-500">
                За выбранный период нет действий менеджеров.
              </div>
            ) : null}
            {managers.map((manager) => (
              <article key={manager.manager_id} className="rounded-xl border border-white/10 bg-background/40 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-white">{manager.name}</p>
                    <p className="mt-1 truncate text-xs text-gray-500">
                      {manager.handler_code ? `#${manager.handler_code} · ` : ''}{manager.email}
                    </p>
                  </div>
                  <span className="shrink-0 text-xs text-gray-500">Вернул: {manager.returned_to_funnel}</span>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 min-[420px]:grid-cols-4">
                  <CompactMetric label="Взял" value={String(manager.chats_taken)} />
                  <CompactMetric label="Подал" value={String(manager.submitted_leads)} />
                  <CompactMetric label="Валид" value={String(manager.valid_leads)} />
                  <CompactMetric label="Довёл" value={String(manager.funnels_pushed)} />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 border-t border-white/10 pt-3">
                  <CompactMetric label="Взял → подал" value={percent(manager.taken_to_submitted_percent)} />
                  <CompactMetric label="Подал → валид" value={percent(manager.submitted_to_valid_percent)} />
                  <CompactMetric label="Взял → валид" value={percent(manager.taken_to_valid_percent)} />
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  )
}

function CompactMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs leading-4 text-gray-500">{label}</div>
      <div className="mt-1 truncate font-mono text-sm text-gray-100">{value}</div>
    </div>
  )
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone: 'cyan' | 'emerald' | 'violet' | 'zinc'
}) {
  const toneClass = {
    cyan: 'text-cyan-100 border-cyan-300/15 bg-cyan-400/5',
    emerald: 'text-emerald-100 border-emerald-300/15 bg-emerald-400/5',
    violet: 'text-violet-100 border-violet-300/15 bg-violet-400/5',
    zinc: 'text-gray-100 border-white/10 bg-white/[0.02]',
  }[tone]

  return (
    <div className={`rounded-xl border p-4 ${toneClass}`}>
      <div className="text-xs uppercase tracking-[0.18em] text-gray-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </div>
  )
}

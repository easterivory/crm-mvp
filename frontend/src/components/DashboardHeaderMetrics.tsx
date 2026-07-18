import { useEffect, useState } from 'react'

import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type HeaderMetrics = {
  project_format?: 'submission' | 'gambling'
  subscribers_today: number
  conversion_today: string | number
  leads_today: number
  chats_today: number
  submitted_today: number
  submitted_percent_today: string | number
  spend_today: string | number
  cpl_today: string | number
  cost_per_submitted_today: string | number
  registrations_today: number
  deposits_today: number
  redeposits_today: number
}

function formatMoney(value: string | number) {
  const amount = Number(value || 0)
  return amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatInteger(value: number) {
  return Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

function formatPercent(value: string | number) {
  const amount = Number(value || 0)
  return `${amount.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
}

export default function DashboardHeaderMetrics() {
  const { selectedProjectId } = useProjectBotSelection()
  const user = useAuthStore((state) => state.user)
  const [metrics, setMetrics] = useState<HeaderMetrics | null>(null)

  const isAuthenticated = Boolean(user)

  useEffect(() => {
    if (!isAuthenticated || !selectedProjectId) {
      setMetrics(null)
      return
    }

    let cancelled = false
    const load = async () => {
      try {
        const { data } = await api.get<HeaderMetrics>(
          `/projects/${selectedProjectId}/dashboard-header`,
        )
        if (!cancelled) {
          setMetrics(data)
        }
      } catch {
        if (!cancelled) {
          setMetrics(null)
        }
      }
    }

    void load()
    const timer = window.setInterval(load, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [isAuthenticated, selectedProjectId])

  if (!isAuthenticated || !metrics) {
    return null
  }

  return (
    <div className="flex shrink-0 overflow-x-auto border-b border-white/5 bg-[#11182a]/95 px-3 py-2 text-sm text-gray-400 shadow-[0_1px_0_rgba(255,255,255,0.04)_inset] lg:px-6">
      <div className="flex min-w-max items-center">
        <Metric label="Подписчиков сегодня" value={formatInteger(metrics.subscribers_today)} />
        <Metric label="Лидов сегодня" value={formatInteger(metrics.leads_today)} />
        <Metric label="Конверсия" value={formatPercent(metrics.conversion_today)} valueClassName="text-orange-400" />
        {metrics.project_format === 'gambling' ? (
          <>
            <Metric label="Регистраций" value={formatInteger(metrics.registrations_today)} valueClassName="text-cyan-200" />
            <Metric label="Депозитов" value={formatInteger(metrics.deposits_today)} valueClassName="text-emerald-300" />
            <Metric label="RD" value={formatInteger(metrics.redeposits_today)} valueClassName="text-violet-200" />
          </>
        ) : (
          <>
            <Metric label="Подано сегодня" value={formatInteger(metrics.submitted_today)} valueClassName="text-emerald-400" />
            <Metric label="% поданных" value={formatPercent(metrics.submitted_percent_today)} valueClassName="text-emerald-400" />
          </>
        )}
        <Metric label="Стоимость лида/день" value={`$${formatMoney(metrics.cpl_today)}`} />
        {metrics.project_format !== 'gambling' ? (
          <Metric label="Стоимость поданного" value={`$${formatMoney(metrics.cost_per_submitted_today)}`} />
        ) : null}
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  valueClassName = 'text-white',
}: {
  label: string
  value: string | number
  valueClassName?: string
}) {
  return (
    <div className="flex shrink-0 items-baseline gap-1.5 border-r border-white/10 px-4 first:pl-0 last:border-r-0 last:pr-0">
      <span>{label}:</span>
      <span className={`font-semibold ${valueClassName}`}>{value}</span>
    </div>
  )
}

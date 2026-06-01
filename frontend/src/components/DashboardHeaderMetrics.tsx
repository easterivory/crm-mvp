import { useEffect, useState } from 'react'

import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type HeaderMetrics = {
  conversion_today: string | number
  leads_today: number
  chats_today: number
  spend_today: string | number
  cpl_today: string | number
}

function formatMoney(value: string | number) {
  const amount = Number(value || 0)
  return amount.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
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
    <div className="grid min-w-[260px] grid-cols-3 gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1 text-xs text-gray-300">
      <Metric label="Конверсия" value={formatPercent(metrics.conversion_today)} />
      <Metric label="Лиды" value={metrics.leads_today} />
      <Metric label="Кост" value={`$${formatMoney(metrics.spend_today)}`} />
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-16 rounded-lg bg-background/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className="truncate font-semibold text-white">{value}</div>
    </div>
  )
}

import { useEffect, useState } from 'react'

import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type HeaderMetrics = {
  leads_today: number
  chats_today: number
  spend_today: string | number
  cpl_today: string | number
}

function formatMoney(value: string | number) {
  const amount = Number(value || 0)
  return amount.toLocaleString('ru-RU', { maximumFractionDigits: 0 })
}

export default function DashboardHeaderMetrics() {
  const user = useAuthStore((state) => state.user)
  const { selectedProjectId } = useProjectBotSelection()
  const [metrics, setMetrics] = useState<HeaderMetrics | null>(null)

  const canView = user?.role_name === 'super_admin' || user?.role_name === 'admin'

  useEffect(() => {
    if (!canView || !selectedProjectId) {
      setMetrics(null)
      return
    }

    let cancelled = false
    const load = async () => {
      try {
        const { data } = await api.get<HeaderMetrics>(
          `/projects/${selectedProjectId}/dashboard-header`,
          { params: { project_id: selectedProjectId } },
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
  }, [canView, selectedProjectId])

  if (!canView || !metrics) {
    return null
  }

  return (
    <div className="grid grid-cols-4 gap-1 rounded-xl border border-white/10 bg-white/[0.03] p-1 text-xs text-gray-300">
      <Metric label="Лиды" value={metrics.leads_today} />
      <Metric label="Чаты" value={metrics.chats_today} />
      <Metric label="Кост" value={`$${formatMoney(metrics.spend_today)}`} />
      <Metric label="CPL" value={`$${formatMoney(metrics.cpl_today)}`} />
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

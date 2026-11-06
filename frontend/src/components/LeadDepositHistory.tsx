import { useEffect, useState } from 'react'
import { ChevronDown, LoaderCircle, RefreshCw } from 'lucide-react'
import api from '../api/client'

type Event = { id: string; event_type: 'registration' | 'deposit' | 'redeposit'; occurred_at: string; amount: string | null; currency: string | null; time_confirmed?: boolean }
type Summary = { events: Event[]; total_events: number; totals: { amount: string | null; currency: string | null; unknown_amount_count: number }[];
  automatic_tracking: boolean | null; data_complete: boolean }
const labels = { registration: 'Регистрация', deposit: 'FD', redeposit: 'RD' }

export default function LeadDepositHistory({ leadId, projectId, refreshKey }: { leadId: string; projectId: string; refreshKey: number }) {
  const [data, setData] = useState<Summary | null>(null)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => { setPage(0); setData(null) }, [leadId, projectId, refreshKey])
  useEffect(() => {
    let current = true
    setLoading(true); setError('')
    api.get<Summary>(`/leads/${leadId}/deposit-summary`, { params: { project_id: projectId, limit: 50, offset: page * 50 } })
      .then(({ data: response }) => { if (current) setData(previous => ({ ...response,
        events: page && previous ? [...new Map([...previous.events, ...response.events].map(e => [e.id, e])).values()] : response.events })) })
      .catch(() => { if (current) setError('Не удалось загрузить события') })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [leadId, projectId, refreshKey, page, retry])
  return <section aria-label="События и депозиты" className="min-w-0 space-y-3 border-b border-white/10 pb-4">
    <div className="flex items-center justify-between gap-3"><h3 className="text-sm font-medium text-gray-200">REG / FD / RD</h3>
      <button title="Обновить события" disabled={loading} onClick={() => { setPage(0); setData(null); setRetry(n => n + 1) }} className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/10 text-gray-400 disabled:opacity-40">{loading ? <LoaderCircle size={15} className="animate-spin" /> : <RefreshCw size={15} />}</button></div>
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
    {data?.automatic_tracking === false && <p className="text-xs text-amber-200">Ручные данные · могут быть неполными</p>}
    {data && data.automatic_tracking !== false && !data.data_complete && <p className="text-xs text-amber-200">Полученные события · полнота не подтверждена</p>}
    {data && !data.events.length && <p className="text-xs text-gray-500">Нет полученных событий</p>}
    <ol className="space-y-2 text-xs text-gray-300">{data?.events.map(event => <li key={event.id} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <span>{labels[event.event_type]}{event.event_type !== 'registration' ? ` · ${event.amount ?? 'сумма не передана'} ${event.currency ?? ''}` : ''}</span>
      <time className="text-gray-500" dateTime={event.occurred_at}>{event.time_confirmed === false ? 'Получено: ' : ''}{new Date(event.occurred_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}</time>
    </li>)}</ol>
    {!!data?.totals.length && <div className="space-y-1 border-t border-white/10 pt-2 text-sm text-gray-200"><p className="text-xs text-gray-400">Сумма депозитов</p>{data.totals.map((total, index) => <p key={index} className="break-words tabular-nums">{total.amount ?? 'Не передана'} {total.currency ?? 'валюта не передана'}{total.unknown_amount_count > 0 ? ` · без суммы: ${total.unknown_amount_count}` : ''}</p>)}</div>}
    {data && data.events.length < data.total_events && <button disabled={loading} title="Загрузить более ранние события" onClick={() => setPage(n => n + 1)} className="inline-flex min-h-8 w-full items-center justify-center gap-1 text-xs text-cyan-200"><ChevronDown size={14} />Ещё события</button>}
  </section>
}

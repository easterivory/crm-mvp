import { useEffect, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, Copy, RefreshCw } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import api from '../../api/client'

type Counts = { cards: number; duplicates: number; within_project: number; cross_project: number }
type Report = { summary: Counts; daily: (Counts & { date: string })[];
  sources: (Counts & { link_id: string | null; title: string | null; code: string | null })[] }
type Props = { projectId: string; dateFrom: string; dateTo: string; botId?: string; buyerId?: string; linkId?: string }
const number = (n: number) => new Intl.NumberFormat('ru-RU').format(n)
const metrics = [
  { key: 'duplicates', label: 'С пересечениями', color: '#38bdf8', hint: 'Новые карточки с более ранним совпадением по Telegram ID, телефону или username. Каждая карточка считается один раз.' },
  { key: 'within_project', label: 'Внутри проекта', color: '#fbbf24', hint: 'Есть более ранняя совпадающая карточка в этом проекте.' },
  { key: 'cross_project', label: 'С другими проектами', color: '#f472b6', hint: 'Есть более ранняя совпадающая карточка в другом доступном проекте. Может одновременно иметь совпадение внутри проекта.' },
] as const

export default function TrackingDuplicates(props: Props) {
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<{ key: string; data: Report } | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [view, setView] = useState<'sources' | 'daily'>('sources')
  const [page, setPage] = useState(0)
  const key = JSON.stringify([props.projectId, props.botId, props.buyerId, props.linkId, props.dateFrom, props.dateTo])
  const data = result?.key === key ? result.data : null
  useEffect(() => { setPage(0) }, [key, view])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setResult(null); setError('')
    void api.get<Report>('/tracking/metrics/duplicates', { signal: controller.signal, params: {
      project_id: props.projectId, bot_id: props.botId, buyer_id: props.buyerId, link_id: props.linkId,
      date_from: props.dateFrom || undefined, date_to: props.dateTo || undefined,
    } }).then(({ data }) => { if (!controller.signal.aborted) setResult({ key, data }) })
      .catch(err => {
        if (!controller.signal.aborted) setError(typeof err.response?.data?.detail === 'string'
          ? err.response.data.detail : 'Не удалось загрузить пересечения')
      })
    return () => controller.abort()
  }, [open, key, retry, props.projectId, props.botId, props.buyerId, props.linkId, props.dateFrom, props.dateTo])
  const rows = data ? view === 'sources' ? data.sources.map(row => ({ ...row, id: row.link_id ?? 'organic',
    label: row.title || 'Без рекламной ссылки', code: row.code }))
    : data.daily.map(row => ({ ...row, id: row.date, label: row.date, code: null })) : []
  return <section className="my-4 min-w-0 border-y border-white/10 py-3">
    <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}
      className="flex w-full items-center gap-2 text-left text-sm font-semibold text-gray-100">
      <Copy size={17} />Пересечения и дубли<ChevronDown size={16} className={`ml-auto transition ${open ? 'rotate-180' : ''}`} />
    </button>
    {open && <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-400">
        <span title="Период относится к дате создания карточки. Совпадения проверяются по текущим контактам с более ранними карточками.">Новые карточки за период · UTC</span>
        <button type="button" title="Обновить пересечения" aria-label="Обновить пересечения" onClick={() => setRetry(n => n + 1)}><RefreshCw size={15} /></button>
      </div>
      {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : !data ? <p role="status" className="text-sm text-gray-400">Расчёт пересечений…</p> : <>
        <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <div><dt className="text-xs text-gray-400">Новых карточек</dt><dd className="mt-1 text-xl font-semibold text-white">{number(data.summary.cards)}</dd></div>
          {metrics.map(metric => <div key={metric.key}><dt title={metric.hint} className="text-xs text-gray-400">{metric.label}</dt>
            <dd className="mt-1 text-xl font-semibold" style={{ color: metric.color }}>{number(data.summary[metric.key])}</dd></div>)}
        </dl>
        <div className="h-56 min-w-0" aria-label="Динамика пересечений по дням">
          <ResponsiveContainer width="100%" height="100%"><LineChart data={data.daily}>
            <CartesianGrid stroke="#ffffff12" vertical={false} /><XAxis dataKey="date" tick={{ fontSize: 10 }} /><YAxis allowDecimals={false} tick={{ fontSize: 10 }} />
            <Tooltip contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', borderRadius: 6 }} /><Legend wrapperStyle={{ fontSize: 11 }} />
            {metrics.map(metric => <Line key={metric.key} dataKey={metric.key} name={metric.label} stroke={metric.color} dot={false} strokeWidth={2} />)}
          </LineChart></ResponsiveContainer>
        </div>
        <div role="group" aria-label="Разбивка пересечений" className="flex gap-1">
          {(['sources', 'daily'] as const).map(value => <button type="button" key={value} aria-pressed={view === value} onClick={() => setView(value)}
            className={`border-b-2 px-3 py-2 text-sm ${view === value ? 'border-sky-400 text-white' : 'border-transparent text-gray-400'}`}>{value === 'sources' ? 'По ссылкам' : 'По дням'}</button>)}
        </div>
        <div className="overflow-x-auto"><table className="w-full text-left text-xs">
          <thead className="text-gray-400"><tr><th className="py-2 pr-4">{view === 'sources' ? 'Ссылка' : 'Дата'}</th><th className="px-2">Карточки</th>
            {metrics.map(metric => <th key={metric.key} className="px-2" title={metric.hint}>{metric.label}</th>)}</tr></thead>
          <tbody>{rows.slice(page * 25, (page + 1) * 25).map(row => <tr key={row.id} className="border-t border-white/5">
            <td className="max-w-xs break-words py-3 pr-4 text-gray-200">{row.label}{row.code && <small className="block text-gray-500">{row.code}</small>}</td>
            <td className="px-2 tabular-nums">{number(row.cards)}</td>{metrics.map(metric => <td className="px-2 tabular-nums" key={metric.key}>{number(row[metric.key])}</td>)}
          </tr>)}</tbody>
        </table></div>
        {!rows.length && <p className="text-sm text-gray-400">Нет карточек за выбранный период</p>}
        {rows.length > 25 && <div className="flex items-center justify-end gap-3 text-xs text-gray-400">
          <button type="button" aria-label="Предыдущая страница пересечений" title="Предыдущая страница" disabled={!page} onClick={() => setPage(n => n - 1)}><ChevronLeft size={18} /></button>
          {page + 1} / {Math.ceil(rows.length / 25)}
          <button type="button" aria-label="Следующая страница пересечений" title="Следующая страница" disabled={(page + 1) * 25 >= rows.length} onClick={() => setPage(n => n + 1)}><ChevronRight size={18} /></button>
        </div>}
      </>}
    </div>}
  </section>
}

import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Download, RotateCcw, Settings2, X } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import api from '../../api/client'
import type { TrackingDailyMetric, TrackingMetricSummary } from './types'
import './tracking-overview.css'

type Option = { id: string; name: string }
type Metric = { id: string; name: string; kind: 'count' | 'money' | 'tag' | 'step'; color: string }
type CustomResult = { total: number; daily: { date: string; count: number }[] }
type View = { selected: string[]; hidden: string[]; from: string; to: string; indexed: boolean; cohortFrom: string; cohortTo: string }
type Props = { projectId: string; userId: string; botId?: string; buyerId?: string; linkId?: string;
  dateFrom: string; dateTo: string; gambling: boolean; channel: boolean; summary: TrackingMetricSummary;
  daily: TrackingDailyMetric[]; refreshToken?: object; loading?: boolean }
const definitions: Metric[] = [
  { id: 'clicks', name: 'Клики', kind: 'count', color: '#eab308' },
  { id: 'channel_join_requests', name: 'Заявки в канал', kind: 'count', color: '#38bdf8' },
  { id: 'channel_joins', name: 'Подписки', kind: 'count', color: '#2dd4bf' },
  { id: 'starts', name: 'Старты в личке', kind: 'count', color: '#60a5fa' },
  { id: 'leads', name: 'Целевые лиды', kind: 'count', color: '#c084fc' },
  { id: 'submitted_leads', name: 'Поданные', kind: 'count', color: '#4ade80' },
  { id: 'registrations', name: 'Регистрации', kind: 'count', color: '#4ade80' },
  { id: 'first_deposits', name: 'ФД', kind: 'count', color: '#fb7185' },
  { id: 'redeposits', name: 'РД', kind: 'count', color: '#fbbf24' },
  { id: 'channel_leaves', name: 'Отписки', kind: 'count', color: '#f87171' },
  { id: 'spend', name: 'Расход, USD', kind: 'money', color: '#e2e8f0' },
]
const defaults = (gambling: boolean, channel: boolean): View => ({
  selected: [...(channel ? ['channel_joins'] : []), 'starts', 'leads', ...(gambling ? ['registrations', 'first_deposits', 'redeposits'] : ['submitted_leads']), 'spend'],
  hidden: [], from: 'starts', to: gambling ? 'registrations' : 'submitted_leads', indexed: false, cohortFrom: 'arrivals', cohortTo: gambling ? 'registrations' : 'submitted_leads',
})
const number = (n: number | null | undefined, digits = 0) => n == null ? '—' : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(n)
const customColor = (id: string) => {
  const colors = ['#f472b6', '#a3e635', '#22d3ee', '#fda4af', '#c4b5fd', '#fcd34d', '#6ee7b7']
  return colors[[...id].reduce((hash, c) => (hash * 31 + c.charCodeAt(0)) >>> 0, 0) % colors.length]
}
export function metricRatio(numerator: number | null, denominator: number | null): number | null {
  return numerator != null && denominator != null && denominator > 0 ? numerator / denominator * 100 : null
}

export default function TrackingOverview(props: Props) {
  const storageKey = `tracking-view:v1:${props.userId}:${props.projectId}`
  const initial = defaults(props.gambling, props.channel)
  const [view, setView] = useState<View>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null')
      if (saved && Array.isArray(saved.selected) && saved.selected.every((id: unknown) => typeof id === 'string') && saved.selected.length <= 20) {
        return { ...initial, ...saved, hidden: Array.isArray(saved.hidden) ? saved.hidden.filter((id: unknown) => typeof id === 'string') : [], from: typeof saved.from === 'string' ? saved.from : initial.from, to: typeof saved.to === 'string' ? saved.to : initial.to, indexed: saved.indexed === true }
      }
    } catch { /* Unavailable or obsolete local preferences must not block analytics. */ }
    return initial
  })
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [options, setOptions] = useState<Metric[]>([])
  const [optionError, setOptionError] = useState('')
  const [custom, setCustom] = useState<Record<string, CustomResult>>({})
  const [customErrors, setCustomErrors] = useState<Record<string, boolean>>({})
  const [query, setQuery] = useState('')
  const [retry, setRetry] = useState(0)
  const [resultsKey, setResultsKey] = useState('')
  const [cohort, setCohort] = useState<{ base: number; converted: number; percent: number | null } | null>(null)
  const [cohortError, setCohortError] = useState(false)
  const cohortKey = JSON.stringify([props.projectId, props.botId, props.buyerId, props.linkId, props.dateFrom, props.dateTo, view.cohortFrom, view.cohortTo])
  const scopeKey = JSON.stringify([props.projectId, props.botId, props.buyerId, props.linkId, props.dateFrom, props.dateTo, view.selected, view.from, view.to])
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(view)) } catch { /* Preferences are optional. */ } }, [storageKey, view])
  useEffect(() => {
    const controller = new AbortController()
    setCohort(null); setCohortError(false)
    void api.get('/tracking/metrics/cohort-conversion', { signal: controller.signal, params: {
      project_id: props.projectId, bot_id: props.botId, buyer_id: props.buyerId, link_id: props.linkId,
      date_from: props.dateFrom, date_to: props.dateTo, source: view.cohortFrom, target: view.cohortTo,
    } }).then(({ data }) => { if (!controller.signal.aborted) setCohort(data) })
      .catch(() => { if (!controller.signal.aborted) setCohortError(true) })
    return () => controller.abort()
  }, [cohortKey, retry, props.refreshToken])

  useEffect(() => {
    const controller = new AbortController()
    setOptions([]); setOptionError('')
    void (async () => {
      const tags: Option[] = []
      for (let offset = 0; ; offset += 100) {
        const { data } = await api.get('/tags', { params: { project_id: props.projectId, limit: 100, offset }, signal: controller.signal })
        tags.push(...data.items)
        if (!data.items.length || tags.length >= data.total) break
      }
      const { data: steps } = await api.get<Option[]>('/tracking/metrics/step-options', { params: { project_id: props.projectId, bot_id: props.botId }, signal: controller.signal })
      if (!controller.signal.aborted) setOptions([
        ...tags.map(t => ({ id: `tag:${t.id}`, name: `Тег: ${t.name}`, kind: 'tag' as const, color: customColor(t.id) })),
        ...steps.map(s => ({ id: `step:${s.id}`, name: `Шаг: ${s.name}`, kind: 'step' as const, color: customColor(s.id) })),
      ])
    })().catch(() => { if (!controller.signal.aborted) setOptionError('Не удалось загрузить теги и шаги') })
    return () => controller.abort()
  }, [props.projectId, props.botId, retry])

  useEffect(() => {
    const controller = new AbortController()
    setCustom({}); setCustomErrors({}); setResultsKey('')
    const ids = [...new Set([...view.selected, view.from, view.to])].filter(id => /^(tag|step):/.test(id))
    void Promise.all(ids.map(async id => {
      const [kind, value] = id.split(':')
      try {
        const { data } = await api.get<CustomResult>(`/tracking/metrics/${kind}`, { signal: controller.signal,
          params: { project_id: props.projectId, bot_id: props.botId, buyer_id: props.buyerId, link_id: props.linkId,
            date_from: props.dateFrom, date_to: props.dateTo, [`${kind}_id`]: value } })
        return { id, data }
      } catch { return { id, data: null } }
    })).then(items => {
      if (controller.signal.aborted) return
      setResultsKey(scopeKey)
      setCustom(Object.fromEntries(items.filter(x => x.data).map(x => [x.id, x.data!])))
      setCustomErrors(Object.fromEntries(items.filter(x => !x.data).map(x => [x.id, true])))
    })
    return () => controller.abort()
  }, [scopeKey, retry, props.refreshToken]) // scopeKey contains all request parameters.

  const catalogue = [...definitions, ...options]
  const cohortOptions = [{ id: 'arrivals', name: 'Все вошедшие лиды' }, ...catalogue.filter(m => m.kind === 'tag' || m.kind === 'step' || ['submitted_leads', 'registrations', 'first_deposits', 'redeposits'].includes(m.id))]
  const selected = view.selected.map(id => catalogue.find(m => m.id === id) ?? { id, name: 'Недоступный показатель', kind: 'tag' as const, color: '#9ca3af' })
  const visible = selected.filter(m => !view.hidden.includes(m.id))
  const getTotal = (id: string): number | null => {
    if (props.loading) return null
    if (id.includes(':')) return resultsKey === scopeKey ? custom[id]?.total ?? null : null
    const value = props.summary[id as keyof TrackingMetricSummary]
    return value == null ? null : Number(value)
  }
  const chart = useMemo(() => {
    const customDays = Object.fromEntries(Object.entries(custom).map(([id, data]) => [id, new Map(data.daily.map(d => [d.date, d.count]))]))
    const rows = props.daily.map(day => Object.fromEntries([['date', day.date], ...visible.map(m => [m.id,
      m.id.includes(':') ? (resultsKey === scopeKey ? customDays[m.id]?.get(day.date) ?? null : null) : Number(day[m.id as keyof TrackingDailyMetric] ?? 0)])]))
    if (!view.indexed) return rows
    const maxima = Object.fromEntries(visible.map(m => [m.id, Math.max(0, ...rows.map(row => Number(row[m.id] || 0)))]))
    return rows.map(row => Object.fromEntries(Object.entries(row).map(([id, value]) => [id, id === 'date' || value == null ? value : maxima[id] > 0 ? Number(value) / maxima[id] * 100 : 0])))
  }, [props.daily, visible.map(m => m.id).join('|'), custom, resultsKey, scopeKey, view.indexed])
  const ratio = metricRatio(getTotal(view.to), getTotal(view.from))
  function toggle(id: string) {
    setView(v => ({ ...v, selected: v.selected.includes(id) ? v.selected.filter(x => x !== id) : v.selected.length < 20 ? [...v.selected, id] : v.selected }))
  }
  function exportCsv() {
    const escape = (value: unknown) => `"${String(value ?? '').replace(/^[=+\-@]/, "'$&").replace(/"/g, '""')}"`
    const rows = [['Дата UTC', ...selected.map(m => m.name)], ...props.daily.map(day => [day.date, ...selected.map(m => m.id.includes(':') ? custom[m.id]?.daily.find(d => d.date === day.date)?.count ?? '' : day[m.id as keyof TrackingDailyMetric] ?? '')])]
    const url = URL.createObjectURL(new Blob(['\uFEFF' + rows.map(row => row.map(escape).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `tracking-${props.dateFrom}-${props.dateTo}.csv`; anchor.click(); URL.revokeObjectURL(url)
  }
  return <div className="tracking-overview">
    <div className="tracking-tools">
      <div><h2>Обзор трафика</h2><span className="tracking-muted">{props.dateFrom} — {props.dateTo} · UTC{!props.linkId && ' · Все ссылки, включая архивные'}</span></div>
      <div className="tracking-actions">
        <button type="button" onClick={exportCsv} disabled={props.loading || !props.daily.length || resultsKey !== scopeKey || Object.keys(customErrors).length > 0} title="Скачать выбранные показатели CSV" aria-label="Скачать CSV"><Download size={17} /></button>
        <button type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen(!settingsOpen)}><Settings2 size={16} />Показатели</button>
      </div>
    </div>
    {settingsOpen && <section className="tracking-config" aria-label="Настройка показателей">
      <div className="tracking-tools"><h3>Показатели · {view.selected.length}/20</h3><div className="tracking-actions">
        <button type="button" title="Восстановить стандартный вид" aria-label="Восстановить стандартный вид" onClick={() => setView(initial)}><RotateCcw size={16} /></button>
        <button type="button" title="Закрыть настройки" aria-label="Закрыть настройки" onClick={() => setSettingsOpen(false)}><X size={16} /></button></div></div>
      <input aria-label="Поиск показателя, тега или шага" placeholder="Найти показатель, тег или шаг" value={query} onChange={e => setQuery(e.target.value)} />
      <div className="tracking-options">{catalogue.filter(m => m.name.toLowerCase().includes(query.toLowerCase())).map(m => <label key={m.id}>
        <input type="checkbox" checked={view.selected.includes(m.id)} disabled={!view.selected.includes(m.id) && view.selected.length >= 20} onChange={() => toggle(m.id)} /><span>{m.name}</span>
      </label>)}</div>
      {selected.filter(m => !catalogue.some(x => x.id === m.id)).map(m => <button type="button" key={m.id} onClick={() => toggle(m.id)}>Убрать недоступный показатель</button>)}
      {optionError && <p role="alert">{optionError}. <button type="button" onClick={() => setRetry(n => n + 1)}>Повторить</button></p>}
    </section>}
    <div className="tracking-kpis">{selected.map(m => <div key={m.id} className="tracking-kpi">
      <span className="tracking-metric-name"><i style={{ background: m.color }} />{m.name}</span>
      <strong>{number(getTotal(m.id), m.kind === 'money' ? 2 : 0)}</strong>
      <span className="tracking-muted">{customErrors[m.id] ? 'Не удалось загрузить' : m.kind === 'tag' || m.kind === 'step' || m.id === 'leads' ? 'По дате входа лида' : 'События за период'}</span>
    </div>)}</div>
    {Object.keys(customErrors).length > 0 && <p role="alert" className="tracking-warning">Часть показателей недоступна. <button type="button" onClick={() => setRetry(n => n + 1)}>Повторить загрузку</button></p>}
    <div className="tracking-chart-head"><h3>Динамика</h3><label><input type="checkbox" checked={view.indexed} onChange={e => setView({ ...view, indexed: e.target.checked })} />Сравнить динамику (пик = 100)</label></div>
    <div className="tracking-legend">{selected.map(m => <label key={m.id} style={{ opacity: view.hidden.includes(m.id) ? 0.5 : 1 }}>
      <input type="checkbox" checked={!view.hidden.includes(m.id)} onChange={() => setView(v => ({ ...v, hidden: v.hidden.includes(m.id) ? v.hidden.filter(x => x !== m.id) : [...v.hidden, m.id] }))} /><i style={{ background: m.color }} />{m.name}</label>)}</div>
    <div className="tracking-chart" aria-label="Динамика выбранных показателей">
      {props.loading ? <p role="status">Загрузка статистики…</p> : !visible.length ? <p>Нет выбранных линий</p> : !chart.length ? <p>Нет данных за период</p> : <ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{ top: 12, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="rgba(255,255,255,.07)" vertical={false} />
        <XAxis dataKey="date" tickFormatter={v => String(v).slice(5).split('-').reverse().join('.')} stroke="#92979e" tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis yAxisId="count" stroke="#92979e" tickLine={false} axisLine={false} width={46} domain={view.indexed ? [0, 100] : [0, 'auto']} />
        {!view.indexed && visible.some(m => m.kind === 'money') && <YAxis yAxisId="money" orientation="right" stroke="#cbd5e1" width={54} tickFormatter={v => `$${v}`} />}
        <Tooltip contentStyle={{ background: '#202326', border: '1px solid #50565c', borderRadius: 8, color: '#fff' }} formatter={(v, name) => [number(Number(v), view.indexed ? 1 : 2), name]} />
        {visible.map(m => <Line key={m.id} dataKey={m.id} name={m.name} yAxisId={!view.indexed && m.kind === 'money' ? 'money' : 'count'} stroke={m.color} dot={false} strokeWidth={2} isAnimationActive={false} connectNulls={false} />)}
      </LineChart></ResponsiveContainer>}
    </div>
    <div className="tracking-conversion"><div><h3>Соотношение показателей</h3><span className="tracking-muted">Результат / база × 100. Не когортная конверсия: даты событий могут различаться.</span></div>
      <div className="tracking-ratio-controls"><label>База<select value={view.from} onChange={e => setView({ ...view, from: e.target.value })}>{catalogue.filter(m => m.kind !== 'money').map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label><ArrowRight size={18} />
        <label>Результат<select value={view.to} onChange={e => setView({ ...view, to: e.target.value })}>{catalogue.filter(m => m.kind !== 'money').map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
        <div className="tracking-ratio-value"><strong>{ratio == null ? '—' : `${number(ratio, 1)}%`}</strong><span>{number(getTotal(view.to))} / {number(getTotal(view.from))}</span></div></div>
    </div>
    <div className="tracking-conversion"><h3>Конверсия по одной группе лидов</h3><span className="tracking-muted">Лиды, вошедшие в выбранный период. Среди выполнивших условие базы считаем тех же лидов с результатом на текущий момент. Теги учитываются в текущем состоянии; порядок двух условий не проверяется.</span>
      <div className="tracking-ratio-controls">
        <label>База<select aria-label="База когорты" value={view.cohortFrom} onChange={e => setView({ ...view, cohortFrom: e.target.value })}>{cohortOptions.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label><ArrowRight size={18} />
        <label>Результат<select aria-label="Результат когорты" value={view.cohortTo} onChange={e => setView({ ...view, cohortTo: e.target.value })}>{cohortOptions.map(m => <option key={m.id} value={m.id}>{m.id === 'redeposits' ? 'Лиды с РД' : m.name}</option>)}</select></label>
        <div className="tracking-ratio-value"><strong>{cohort?.percent == null ? '—' : `${number(cohort.percent, 1)}%`}</strong><span>{cohort ? `${number(cohort.converted)} / ${number(cohort.base)}` : cohortError ? 'Ошибка расчёта' : 'Загрузка…'}</span></div>
      </div>{cohortError && <button type="button" onClick={() => setRetry(n => n + 1)}>Повторить расчёт</button>}
    </div>
  </div>
}

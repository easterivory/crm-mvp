import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, RotateCcw, X } from 'lucide-react'
import api from '../../api/client'

type Scope = { projectId: string; botId?: string; buyerId?: string; linkId?: string;
  dateFrom: string; dateTo: string; refreshToken?: object }
type Step = { id: string; funnel_id: string; funnel_name: string; name: string; number: number;
  title: string; version_number: number }
type Bucket = 'reached' | 'continued' | 'current' | 'waiting' | 'delayed' | 'manual' | 'stalled'
type Row = Step & Record<Bucket, number> & { conversion: number | null }
type Person = { chat_id: string; lead_id: string; name: string | null; username: string | null;
  contact_name: string | null; status: string | null; tags: string[]; link_title: string | null;
  link_code: string | null; last_message_at: string | null }
const columns: { id: Bucket; title: string }[] = [
  { id: 'reached', title: 'Дошли' }, { id: 'continued', title: 'Пошли дальше' },
  { id: 'current', title: 'Сейчас на шаге' }, { id: 'waiting', title: 'Ждём ответ' },
  { id: 'delayed', title: 'Задержка / задача' }, { id: 'manual', title: 'Пауза у менеджера' },
  { id: 'stalled', title: 'Долго нет ответа' },
]
const number = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)

export default function TrackingJourney(props: Scope) {
  const [options, setOptions] = useState<Step[]>([])
  const [funnelId, setFunnelId] = useState('')
  const [idleHours, setIdleHours] = useState(24)
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [detail, setDetail] = useState<{ step: Row; bucket: Bucket } | null>(null)
  const [offset, setOffset] = useState(0)
  const [people, setPeople] = useState<{ items: Person[]; total: number } | null>(null)
  const [peopleError, setPeopleError] = useState(false)
  const params = { project_id: props.projectId, bot_id: props.botId, buyer_id: props.buyerId,
    link_id: props.linkId, date_from: props.dateFrom, date_to: props.dateTo, funnel_id: funnelId, idle_hours: idleHours }
  const scopeKey = JSON.stringify(params)
  useEffect(() => {
    const controller = new AbortController()
    setOptions([]); setFunnelId(''); setRows([]); setError(''); setLoading(true)
    void api.get<Step[]>('/tracking/metrics/step-options', { signal: controller.signal,
      params: { project_id: props.projectId, bot_id: props.botId } })
      .then(({ data }) => { if (!controller.signal.aborted) {
        setOptions(data); setFunnelId(data[0]?.funnel_id || ''); setLoading(false)
      } })
      .catch(() => { if (!controller.signal.aborted) { setError('Не удалось загрузить воронки'); setLoading(false) } })
    return () => controller.abort()
  }, [props.projectId, props.botId, retry])
  useEffect(() => {
    setDetail(null); setOffset(0); setRows([])
    if (!funnelId) return
    const controller = new AbortController()
    setLoading(true); setError('')
    void api.get<{ items: Row[] }>('/tracking/metrics/journey', { params, signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) { setRows(data.items); setLoading(false) } })
      .catch(() => { if (!controller.signal.aborted) { setError('Не удалось загрузить прохождение воронки'); setLoading(false) } })
    return () => controller.abort()
  }, [scopeKey, retry, props.refreshToken])
  useEffect(() => {
    setPeople(null); setPeopleError(false)
    if (!detail) return
    const controller = new AbortController()
    void api.get<{ items: Person[]; total: number }>('/tracking/metrics/journey/chats', {
      params: { ...params, step_id: detail.step.id, bucket: detail.bucket, limit: 50, offset }, signal: controller.signal,
    }).then(({ data }) => { if (!controller.signal.aborted) setPeople(data) })
      .catch(() => { if (!controller.signal.aborted) setPeopleError(true) })
    return () => controller.abort()
  }, [detail, offset, scopeKey, retry, props.refreshToken])
  const funnels = [...new Map(options.map(option => [option.funnel_id, option.funnel_name])).entries()]
  return <section className="tracking-journey" aria-label="Прохождение воронки">
    <div className="tracking-journey-filters">
      <label>Воронка<select aria-label="Воронка для анализа" value={funnelId} onChange={e => setFunnelId(e.target.value)}>
        {!funnels.length && <option value="">Нет опубликованных воронок</option>}
        {funnels.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select></label>
      <label>Долго нет ответа, часов<input aria-label="Порог ожидания ответа, часов" type="number" min={1} max={8760}
        value={idleHours} onChange={e => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 1 && n <= 8760) setIdleHours(n) }} /></label>
      <button type="button" title="Обновить прохождение" aria-label="Обновить прохождение" onClick={() => setRetry(n => n + 1)}><RotateCcw size={16} /></button>
    </div>
    {error && <p role="alert" className="tracking-warning">{error}</p>}
    {loading ? <p role="status">Загрузка…</p> : !rows.length ? <p className="tracking-muted">Нет данных по воронке</p> :
      <div className="tracking-table-scroll"><table className="tracking-journey-table"><thead><tr><th>Шаг</th>
        {columns.map(column => <th key={column.id}>{column.title}</th>)}<th>Конверсия дальше</th>
      </tr></thead><tbody>{rows.map(row => <tr key={row.id}>
        <th scope="row"><strong>#{row.number} · {row.title}</strong><span className="tracking-muted">{row.funnel_name} · v{row.version_number}</span></th>
        {columns.map(column => <td key={column.id}><button type="button" disabled={!row[column.id]}
          aria-label={`${row.name}: ${column.title}, ${row[column.id]}`}
          onClick={() => { setDetail({ step: row, bucket: column.id }); setOffset(0) }}>{number(row[column.id])}</button></td>)}
        <td>{row.conversion == null ? '—' : `${number(row.conversion)}%`}</td>
      </tr>)}</tbody></table></div>}
    {detail && <section className="tracking-journey-people" aria-label="Лиды выбранного шага">
      <div className="tracking-tools"><div><h3>{detail.step.name}</h3><span className="tracking-muted">
        {columns.find(column => column.id === detail.bucket)?.title}{people && ` · ${number(people.total)} лидов`}</span></div>
        <button type="button" title="Закрыть список лидов" aria-label="Закрыть список лидов" onClick={() => setDetail(null)}><X size={16} /></button></div>
      {peopleError ? <p role="alert">Не удалось загрузить лидов</p> : !people ? <p role="status">Загрузка лидов…</p> :
        <><div className="tracking-table-scroll"><table className="tracking-journey-table"><thead><tr>
          <th>Лид</th><th>Рекламная ссылка</th><th>Статус / теги</th><th>Последнее сообщение</th><th /></tr></thead>
          <tbody>{people.items.map(person => <tr key={person.chat_id}>
            <td>{person.name || person.contact_name || person.username || 'Без имени'}{person.username && <span className="tracking-muted">@{person.username.replace(/^@/, '')}</span>}</td>
            <td>{person.link_title || 'Без рекламной ссылки'}{person.link_code && <span className="tracking-muted">{person.link_code}</span>}</td>
            <td>{person.status || '—'}<span className="tracking-muted">{person.tags.join(' · ') || 'Нет тегов'}</span></td>
            <td>{person.last_message_at ? new Date(person.last_message_at).toLocaleString('ru-RU') : '—'}</td>
            <td><a href={`/chats?chat_id=${encodeURIComponent(person.chat_id)}`} target="_blank" rel="noopener noreferrer"
              title="Открыть диалог в новой вкладке" aria-label="Открыть диалог"><ExternalLink size={17} /></a></td>
          </tr>)}</tbody></table></div>
          {!people.items.length && <p>Нет лидов в выбранной группе</p>}
          <div className="tracking-actions tracking-pagination">
            <button type="button" title="Предыдущая страница" aria-label="Предыдущая страница" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 50))}><ChevronLeft size={17} /></button>
            <span>{offset + 1}–{Math.min(offset + 50, people.total)} / {people.total}</span>
            <button type="button" title="Следующая страница" aria-label="Следующая страница" disabled={offset + 50 >= people.total} onClick={() => setOffset(n => n + 50)}><ChevronRight size={17} /></button>
          </div></>}
    </section>}
  </section>
}

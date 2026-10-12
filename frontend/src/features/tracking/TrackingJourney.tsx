import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, ExternalLink, RotateCcw, Settings2, X } from 'lucide-react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import api from '../../api/client'
import JourneyStageEditor, { type Catalogue, type Stage } from './JourneyStageEditor'

type Scope = { projectId: string; botId?: string; buyerId?: string; linkId?: string;
  dateFrom: string; dateTo: string; refreshToken?: object }
type Step = { funnel_id: string; funnel_name: string; bot_name?: string | null; bot_username?: string | null }
type Bucket = 'reached' | 'remaining' | 'stalled'
type Row = Stage & Record<Bucket, number> & { number: number; next: number | null;
  conversion: number | null; not_yet_next: number | null }
type Totals = { people: number; outcomes: number; conversion: number | null; offer_conversion: number | null; items: Row[] }
type Report = Totals & { physical_chats: number; sources_total: number; daily: (Totals & { date: string })[];
  sources: (Totals & { link_id: string | null; title: string | null; code: string | null })[] }
type Person = { chat_id: string; lead_id: string | null; name: string | null; username: string | null;
  contact_name: string | null; tags: string[]; link_title: string | null;
  link_code: string | null; last_message_at: string | null; stage_at: string }
const columns: { id: Bucket; title: string }[] = [
  { id: 'reached', title: 'Дошли' }, { id: 'remaining', title: 'Ещё не продолжили' }, { id: 'stalled', title: 'Долго нет ответа' },
]
const number = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value)
const percent = (value: number | null) => value == null ? '—' : `${number(value)}%`
const palette = ['#38bdf8', '#34d399', '#fbbf24', '#f472b6', '#a3e635', '#fb7185', '#c4b5fd', '#2dd4bf']

export default function TrackingJourney(props: Scope) {
  const [options, setOptions] = useState<Step[]>([])
  const [funnelId, setFunnelId] = useState('')
  const [loadedCatalogue, setCatalogue] = useState<(Catalogue & { scope: string }) | null>(null)
  const configScope = `${props.projectId}:${funnelId}`
  const catalogue = loadedCatalogue?.scope === configScope ? loadedCatalogue : null
  const [editing, setEditing] = useState(false)
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [granularity, setGranularity] = useState('day')
  const [chartBucket, setChartBucket] = useState<Bucket>('reached')
  const [sourceId, setSourceId] = useState('')
  const [sourceOffset, setSourceOffset] = useState(0)
  const [detail, setDetail] = useState<{ stage: Row; bucket: Bucket } | null>(null)
  const [offset, setOffset] = useState(0)
  const [people, setPeople] = useState<{ items: Person[]; total: number } | null>(null)
  const [peopleError, setPeopleError] = useState(false)
  const params = { project_id: props.projectId, bot_id: props.botId, buyer_id: props.buyerId,
    link_id: props.linkId || sourceId || undefined, date_from: props.dateFrom, date_to: props.dateTo, funnel_id: funnelId }
  const scopeKey = JSON.stringify(params)
  useEffect(() => setSourceOffset(0), [scopeKey])
  useEffect(() => {
    setOptions([]); setFunnelId(''); setCatalogue(null); setReport(null); setSourceId(''); setEditing(false)
  }, [props.projectId, props.botId])
  useEffect(() => {
    const controller = new AbortController()
    setError(''); setLoading(true)
    void api.get<Step[]>('/tracking/metrics/step-options', { signal: controller.signal,
      params: { project_id: props.projectId, bot_id: props.botId } })
      .then(({ data }) => { if (!controller.signal.aborted) { setOptions(data);
        setFunnelId(current => data.some(o => o.funnel_id === current) ? current : data[0]?.funnel_id || ''); setLoading(false) } })
      .catch(() => { if (!controller.signal.aborted) { setError('Не удалось загрузить воронки'); setLoading(false) } })
    return () => controller.abort()
  }, [props.projectId, props.botId, retry])
  useEffect(() => {
    setSourceId('')
  }, [props.projectId, funnelId])
  useEffect(() => {
    setCatalogue(null); setEditing(false)
    if (!funnelId) return
    const controller = new AbortController()
    setLoading(true); setError('')
    void api.get<Catalogue>('/tracking/journey/config', { signal: controller.signal,
      params: { project_id: props.projectId, funnel_id: funnelId } }).then(({ data }) => {
        if (!controller.signal.aborted) { setCatalogue({ ...data, scope: configScope }); setLoading(false) }
      }).catch(() => { if (!controller.signal.aborted) { setError('Не удалось загрузить настройки этапов'); setLoading(false) } })
    return () => controller.abort()
  }, [props.projectId, funnelId, retry])
  useEffect(() => {
    setDetail(null); setOffset(0); setReport(null)
    if (!funnelId || !catalogue?.config) return
    const controller = new AbortController()
    setLoading(true); setError('')
    void api.get<Report>('/tracking/metrics/stage-journey', { params: { ...params, granularity, sources_offset: sourceOffset }, signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) { setReport(data); setLoading(false) } })
      .catch(() => { if (!controller.signal.aborted) { setError('Не удалось загрузить движение по этапам'); setLoading(false) } })
    return () => controller.abort()
  }, [scopeKey, granularity, sourceOffset, catalogue, retry, props.refreshToken])
  useEffect(() => {
    setPeople(null); setPeopleError(false)
    if (!detail) return
    const controller = new AbortController()
    void api.get<{ items: Person[]; total: number }>('/tracking/metrics/stage-journey/chats', {
      params: { ...params, stage_id: detail.stage.id, bucket: detail.bucket, limit: 50, offset }, signal: controller.signal,
    }).then(({ data }) => { if (!controller.signal.aborted) setPeople(data) })
      .catch(() => { if (!controller.signal.aborted) setPeopleError(true) })
    return () => controller.abort()
  }, [detail, offset, scopeKey, retry, props.refreshToken])
  const funnels = [...new Map(options.map(option => [option.funnel_id,
    `${option.bot_name || 'Без бота'}${option.bot_username ? ` · @${option.bot_username.replace(/^@/, '')}` : ''} → ${option.funnel_name}`])).entries()]
  const chart = report?.daily.map(day => ({ date: day.date,
    ...Object.fromEntries(day.items.map(stage => [stage.id, stage[chartBucket]])) })) || []
  const outcome = report?.items[report.items.length - 1]?.name
  const selectedFunnel = options.find(option => option.funnel_id === funnelId)
  return <section className="tracking-journey" aria-label="Движение по этапам">
    <div className="tracking-journey-filters">
      <label>Воронка<select aria-label="Воронка для анализа" value={funnelId} onChange={e => setFunnelId(e.target.value)}>
        {!funnels.length && <option value="">Нет опубликованных воронок</option>}
        {funnels.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select></label>
      {sourceId && !props.linkId && <button type="button" onClick={() => setSourceId('')}><X size={16} />Все источники</button>}
      {catalogue?.can_edit && <button type="button" onClick={() => setEditing(value => !value)}><Settings2 size={16} />Настроить этапы</button>}
      <button type="button" title="Обновить статистику" aria-label="Обновить статистику" onClick={() => setRetry(n => n + 1)}><RotateCcw size={16} /></button>
    </div>
    {selectedFunnel && <div className="journey-selected-context">
      <span>{selectedFunnel.bot_name || 'Без бота'}{selectedFunnel.bot_username && ` · @${selectedFunnel.bot_username.replace(/^@/, '')}`}</span>
      <strong>{selectedFunnel.funnel_name}</strong>
    </div>}
    {editing && catalogue && <JourneyStageEditor key={`${props.projectId}:${funnelId}`} projectId={props.projectId} funnelId={funnelId}
      catalogue={catalogue} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); setRetry(n => n + 1) }} />}
    {error && <p role="alert" className="tracking-warning">{error}</p>}
    {loading ? <p role="status">Загрузка…</p> : !catalogue?.config ? <p className="tracking-muted">Этапы и итоговый тег не настроены</p> : report && <>
      <div className="journey-summary">
        <div><span>Новые люди</span><strong>{number(report.people)}</strong></div>
        <div><span>{outcome}</span><strong>{number(report.outcomes)}</strong></div>
        <div><span>Первый приход → {outcome}</span><strong>{percent(report.conversion)}</strong></div>
        {report.items.some(s => s.role === 'offer') && <div><span>Предложение → {outcome}</span><strong>{percent(report.offer_conversion)}</strong></div>}
      </div>
      <div className="tracking-journey-filters"><span className="tracking-muted">Первый приход: {props.dateFrom} — {props.dateTo} · МСК</span>
        <span className="tracking-muted">{catalogue.config.scope === 'funnel' ? 'Выбранная воронка' : 'Весь бот'}</span>
        <span className="tracking-muted">Связанные чаты: {number(report.physical_chats)}</span></div>
      {catalogue.has_legacy_tag_snapshot && <p className="tracking-warning" title="Присвоения тегов, удалённых до обновления, не восстановлены">История тегов до обновления — частичная</p>}
      <div className="tracking-table-scroll"><table className="tracking-journey-table"><thead><tr><th>Этап</th>
        {columns.map(column => <th key={column.id}>{column.title}</th>)}<th>Перешли на следующий</th><th>Конверсия дальше</th><th>Ещё не перешли, %</th>
      </tr></thead><tbody>{report.items.map(row => <tr key={row.id}>
        <th scope="row"><strong>#{row.number} · {row.name}</strong></th>
        {columns.map(column => <td key={column.id}><button type="button" disabled={!row[column.id]}
          aria-label={`${row.name}: ${column.title}, ${row[column.id]}`}
          onClick={() => { setDetail({ stage: row, bucket: column.id }); setOffset(0) }}>{number(row[column.id])}</button></td>)}
        <td>{row.next == null ? '—' : number(row.next)}</td><td>{percent(row.conversion)}</td><td>{row.conversion == null ? '—' : percent(100 - row.conversion)}</td>
      </tr>)}</tbody></table></div>
      <div className="tracking-journey-filters">
        <label>Динамика<select value={granularity} onChange={e => setGranularity(e.target.value)}><option value="day">Дни</option><option value="week">Недели</option><option value="month">Месяцы</option></select></label>
        <label>Показатель<select value={chartBucket} onChange={e => setChartBucket(e.target.value as Bucket)}>{columns.map(c => <option value={c.id} key={c.id}>{c.title}</option>)}</select></label>
      </div>
      <div className="journey-dynamics">{!chart.length ? <p>Нет данных за период</p> : <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chart} margin={{ top: 12, right: 16, bottom: 8, left: 0 }}><CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="date" tickFormatter={value => new Date(`${value}T12:00:00+03:00`).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })} />
          <YAxis allowDecimals={false} width={40} /><Tooltip /><Legend height={90} wrapperStyle={{ maxHeight: 90, overflowY: 'auto' }} />
          {report.items.map((stage, index) => <Line key={stage.id} dataKey={stage.id} name={`#${stage.number} ${stage.name}`}
            stroke={palette[index % palette.length]} strokeWidth={2} dot={chart.length < 32} isAnimationActive={false} />)}
        </LineChart></ResponsiveContainer>}</div>
      <h3>Источники</h3>
      <div className="tracking-table-scroll"><table className="tracking-journey-table"><thead><tr><th>Ссылка</th><th>Новые люди</th>
        {report.items.slice(1).map(s => <th key={s.id}>#{s.number} {s.name}</th>)}<th>Первый приход → итог</th><th>Предложение → итог</th></tr></thead>
        <tbody>{report.sources.map(source => <tr key={source.link_id || 'organic'}><th>
          {source.link_id ? <button type="button" disabled={!!props.linkId} onClick={() => setSourceId(source.link_id!)}>{source.title || source.code}</button> : 'Без рекламной ссылки'}
          {source.code && <span className="tracking-muted">{source.code}</span>}</th><td>{number(source.people)}</td>
          {source.items.slice(1).map(s => <td key={s.id}>{number(s.reached)}</td>)}<td>{percent(source.conversion)}</td><td>{percent(source.offer_conversion)}</td></tr>)}</tbody>
      </table></div>
      {report.sources_total > 50 && <div className="tracking-actions tracking-pagination">
        <button type="button" title="Предыдущие источники" aria-label="Предыдущие источники" disabled={!sourceOffset} onClick={() => setSourceOffset(n => Math.max(0, n - 50))}><ChevronLeft size={17} /></button>
        <span>{sourceOffset + 1}–{Math.min(sourceOffset + 50, report.sources_total)} / {report.sources_total}</span>
        <button type="button" title="Следующие источники" aria-label="Следующие источники" disabled={sourceOffset + 50 >= report.sources_total} onClick={() => setSourceOffset(n => n + 50)}><ChevronRight size={17} /></button>
      </div>}
    </>}
    {detail && <section className="tracking-journey-people" aria-label="Лиды выбранного этапа">
      <div className="tracking-tools"><div><h3>#{detail.stage.number} · {detail.stage.name}</h3><span className="tracking-muted">
        {columns.find(column => column.id === detail.bucket)?.title}{people && ` · ${number(people.total)} людей`}</span></div>
        <button type="button" title="Закрыть список" aria-label="Закрыть список" onClick={() => setDetail(null)}><X size={16} /></button></div>
      {peopleError ? <p role="alert">Не удалось загрузить лидов</p> : !people ? <p role="status">Загрузка лидов…</p> :
        <><div className="tracking-table-scroll"><table className="tracking-journey-table"><thead><tr>
          <th>Лид</th><th>Рекламная ссылка</th><th>Текущие теги</th><th>Этап достигнут</th><th /></tr></thead>
          <tbody>{people.items.map(person => <tr key={person.chat_id}>
            <td>{person.name || person.contact_name || person.username || 'Без имени'}{person.username && <span className="tracking-muted">@{person.username.replace(/^@/, '')}</span>}</td>
            <td>{person.link_title || 'Без рекламной ссылки'}{person.link_code && <span className="tracking-muted">{person.link_code}</span>}</td>
            <td>{person.tags.join(' · ') || 'Нет тегов'}</td>
            <td>{new Date(person.stage_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}</td>
            <td><a href={`/chats?chat_id=${encodeURIComponent(person.chat_id)}`} target="_blank" rel="noopener noreferrer" title="Открыть диалог" aria-label="Открыть диалог"><ExternalLink size={17} /></a></td>
          </tr>)}</tbody></table></div>
          {!people.items.length && <p>Нет лидов в выбранной группе</p>}
          <div className="tracking-actions tracking-pagination">
            <button type="button" title="Предыдущая страница" aria-label="Предыдущая страница" disabled={!offset} onClick={() => setOffset(n => Math.max(0, n - 50))}><ChevronLeft size={17} /></button>
            <span>{people.total ? offset + 1 : 0}–{Math.min(offset + 50, people.total)} / {people.total}</span>
            <button type="button" title="Следующая страница" aria-label="Следующая страница" disabled={offset + 50 >= people.total} onClick={() => setOffset(n => n + 50)}><ChevronRight size={17} /></button>
          </div></>}
    </section>}
  </section>
}

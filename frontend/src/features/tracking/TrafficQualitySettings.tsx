import { useEffect, useState } from 'react'
import { Plus, Save, Trash2, RotateCcw, Play, RefreshCw } from 'lucide-react'
import axios from 'axios'
import api from '../../api/client'

type Option = { id: string; name: string }
type Rule = {
  id: string; name: string; enabled: boolean; destination: 'all' | 'bot' | 'channel'; bot_ids: string[]; ad_types: string[]
  expression: string; operator: 'gt' | 'lt'; threshold: number; recovery_threshold: number
  window_hours: number; maturation_hours: number; sample_metric: string; min_sample: number
  tag_ids: string[]; tag_match: 'any' | 'all'; assessed_tag_ids: string[]; assessed_status_codes: string[]; min_coverage: number
  confirmations: number; repeat_hours: number; severity: 'warning' | 'critical'
  notify_buyer: boolean; notify_admin: boolean; notify_recovery: boolean
}
type Config = { enabled: boolean; timezone: string; revision: number; rules: Rule[] }
type Overrides = { revision: number; patches: Record<string, Partial<Rule>>; rules: Rule[] }
type Result = { link_id: string; link_title: string; rule_name: string; value: number | null; sample: number | null; status: string; reason: string | null; expression: string; period_from: string; period_to: string }
type Delivery = { id: string; status: string; error: string | null; body: string; created_at: string; attempts: number }
const metricLabels: Record<string, string> = {
  leads: 'Пришедшие лиды', qualified_leads: 'Целевые лиды', submitted_leads: 'Поданные', registrations: 'Регистрации',
  first_deposits: 'ФД', redepositors: 'Лиды с РД', redeposits: 'События РД', tagged_leads: 'Лиды с выбранными тегами',
  assessed_leads: 'Оценённые лиды', coverage: 'Обработано, %', clicks: 'Клики', spend: 'Расход',
  channel_join_requests: 'Заявки в канал', channel_joins: 'Подписчики', channel_leaves: 'Отписавшиеся', funnel_starts: 'Запущенные приветки',
  registered_depositors: 'Зарегистрированные с ФД', deposited_redepositors: 'Лиды с ФД и последующим РД', approved_requests: 'Принятые заявители', request_funnel_starts: 'Заявители с запущенной приветкой',
}
const statuses: Record<string, string> = { normal: 'Норма', breach: 'Нарушение', insufficient_data: 'Недостаточно данных', configuration_error: 'Ошибка настройки', evaluation_error: 'Ошибка расчёта', sent: 'Доставлено', pending: 'В очереди', retry: 'Повтор', failed: 'Ошибка доставки', cancelled: 'Отменено', sending: 'Отправка', alert: 'Алерт', disabled: 'Отключено' }
const input = 'w-full min-w-0 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-2 text-sm text-zinc-100'
const button = 'inline-flex items-center justify-center gap-2 rounded-md border border-zinc-700 px-3 py-2 text-sm disabled:opacity-40'
const defaultConfig: Config = { enabled: false, timezone: 'Europe/Moscow', revision: 0, rules: [] }

function newRule(): Rule {
  return { id: crypto.randomUUID(), name: 'Качество лидов', enabled: true, destination: 'all', bot_ids: [], ad_types: [],
    expression: 'percent(tagged_leads, assessed_leads)', operator: 'gt', threshold: 25, recovery_threshold: 20,
    window_hours: 168, maturation_hours: 24, sample_metric: 'assessed_leads', min_sample: 40, tag_ids: [], tag_match: 'any',
    assessed_tag_ids: [], assessed_status_codes: [], min_coverage: 70, confirmations: 2, repeat_hours: 24,
    severity: 'warning', notify_buyer: true, notify_admin: true, notify_recovery: true }
}
function errorText(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((item: { msg: string }) => item.msg).join('; ')
  }
  return 'Не удалось выполнить запрос. Изменения не сохранены.'
}
function MultiSelect({ title, options, value, onChange }: { title: string; options: Option[]; value: string[]; onChange: (ids: string[]) => void }) {
  return <fieldset className="min-w-0"><legend className="mb-1 text-xs text-zinc-400">{title}</legend><div className="max-h-32 space-y-1 overflow-auto border border-zinc-800 p-2">
    {options.map(item => <label key={item.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={value.includes(item.id)} onChange={e => onChange(e.target.checked ? [...value, item.id] : value.filter(id => id !== item.id))} />{item.name}</label>)}
    {value.filter(id => !options.some(item => item.id === id)).map(id => <label key={id} className="flex gap-2 text-xs text-red-300"><input type="checkbox" checked onChange={() => onChange(value.filter(item => item !== id))} />Недоступно: {id}</label>)}
  </div></fieldset>
}

export default function TrafficQualitySettings({ projectId, linkId }: { projectId: string | null; linkId?: string }) {
  const [config, setConfig] = useState<Config>(defaultConfig)
  const [base, setBase] = useState<Config>(defaultConfig)
  const [overrideRevision, setOverrideRevision] = useState(0)
  const [tags, setTags] = useState<Option[]>([])
  const [leadStatuses, setLeadStatuses] = useState<Option[]>([])
  const [bots, setBots] = useState<Option[]>([])
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [results, setResults] = useState<Result[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(null)
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [historyOffset, setHistoryOffset] = useState<number | null>(0)
  const [checks, setChecks] = useState<Array<{ link_id: string; link_title: string; rule_id: string; status: string; checked_at: string; snapshot: Partial<Result> }>>([])
  const [audits, setAudits] = useState<Array<{ at: string; actor_id: string; entity_type: string; changes: unknown }>>([])

  useEffect(() => {
    if (!projectId) { setLoading(false); return }
    const controller = new AbortController()
    async function load() {
      setLoading(true); setLoaded(false); setError(''); setSaved(false)
      try {
        const data = (await api.get(linkId ? `/traffic-quality/links/${linkId}` : `/traffic-quality/projects/${projectId}`, { signal: controller.signal })).data
        const project = linkId ? data.project : data
        setBase(project); setConfig(linkId ? { ...project, rules: data.effective_rules } : project)
        setOverrideRevision(linkId ? data.overrides.revision : 0)
        const allTags: Option[] = []
        for (let offset = 0; ; offset += 100) {
          const page = (await api.get('/tags', { params: { project_id: projectId, limit: 100, offset }, signal: controller.signal })).data
          allTags.push(...page.items)
          if (allTags.length >= page.total || !page.items.length) break
        }
        setTags(allTags)
        const statusRows = (await api.get('/leads/statuses', { signal: controller.signal })).data
        setLeadStatuses(statusRows.map((row: { code: string; name: string }) => ({ id: row.code, name: row.name })))
        const botRows = (await api.get('/bots', { params: { project_id: projectId, limit: 100 }, signal: controller.signal })).data
        setBots((botRows.items ?? botRows).map((row: { id: string; name: string }) => ({ id: row.id, name: row.name })))
        setLoaded(true)
      } catch (err) { if (!controller.signal.aborted) setError(errorText(err)) }
      finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    return () => controller.abort()
  }, [projectId, linkId])

  function patch(id: string, changes: Partial<Rule>) {
    setSaved(false); setResults([]); setNextOffset(null)
    setConfig(current => ({ ...current, rules: current.rules.map(rule => rule.id === id ? { ...rule, ...changes } : rule) }))
  }
  function overrides(): Overrides {
    const patches: Record<string, Partial<Rule>> = {}
    for (const rule of config.rules) {
      const inherited = base.rules.find(item => item.id === rule.id)
      if (!inherited) continue
      const changes = Object.fromEntries(Object.entries(rule).filter(([key, value]) => key !== 'id' && JSON.stringify(value) !== JSON.stringify(inherited[key as keyof Rule])))
      if (Object.keys(changes).length) patches[rule.id] = changes
    }
    return { revision: overrideRevision, patches, rules: config.rules.filter(rule => !base.rules.some(item => item.id === rule.id)) }
  }
  async function save() {
    if (busy || !projectId) return
    setBusy(true); setError(''); setSaved(false)
    try {
      if (linkId) {
        const { data } = await api.put(`/traffic-quality/links/${linkId}`, overrides())
        setOverrideRevision(data.revision)
      } else {
        const { data } = await api.put(`/traffic-quality/projects/${projectId}`, config)
        setConfig(data); setBase(data)
      }
      setSaved(true)
    } catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  async function preview(offset = 0) {
    if (!projectId || busy) return
    setBusy(true); setError('')
    try {
      const { data } = await api.post(`/traffic-quality/projects/${projectId}/preview`, { config: linkId ? base : config, link_id: linkId ?? null, overrides: linkId ? overrides() : null, offset })
      setResults(current => offset ? [...current, ...data.items] : data.items); setNextOffset(data.next_offset)
    } catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  async function history(offset = 0) {
    if (!projectId || busy) return
    setBusy(true); setError('')
    try {
      const { data } = await api.get(`/traffic-quality/projects/${projectId}/history`, { params: { link_id: linkId, offset } })
      setDeliveries(current => offset ? [...current, ...data.items] : data.items); setHistoryOffset(data.next_offset)
    } catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  async function loadChecks() {
    setBusy(true); setError('')
    try {
      const { data } = await api.get(`/traffic-quality/projects/${projectId}/states`, { params: { link_id: linkId } })
      setChecks(data.items)
    } catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  async function loadAudit() {
    setBusy(true); setError('')
    try { setAudits((await api.get(`/traffic-quality/projects/${projectId}/audit`)).data) }
    catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  if (!projectId) return <p>Выберите проект</p>
  if (loading) return <p role="status">Загрузка правил…</p>
  if (!loaded && projectId) return <p role="alert" className="text-red-300">{error || 'Настройки не загружены. Откройте раздел повторно.'}</p>
  return <section className="space-y-5 border-t border-zinc-800 py-5 text-zinc-100">
    <h2 className="text-lg font-semibold">Контроль качества трафика</h2>
    {error && <div role="alert" className="whitespace-pre-wrap break-words text-sm text-red-300">{error}</div>}
    {saved && <div role="status" className="text-sm text-emerald-300">Настройки сохранены</div>}
    {!linkId ? <div className="flex flex-wrap items-center gap-4">
      <label className="flex items-center gap-2"><input type="checkbox" checked={config.enabled} onChange={e => { setSaved(false); setConfig({ ...config, enabled: e.target.checked }) }} />Новые правила включены</label>
      <label className="text-xs text-zinc-400">Часовой пояс<input className={input} value={config.timezone} onChange={e => { setSaved(false); setConfig({ ...config, timezone: e.target.value }) }} /></label>
    </div> : <p className="text-sm text-zinc-400">Правила проекта: {base.enabled ? 'включены' : 'выключены'} · {base.timezone}</p>}
    <p className="text-xs text-zinc-400">Выборка: пришедшие за период, с учётом времени на обработку. Теги и статусы — текущее состояние. При включении новые правила заменяют прежние алерты проекта.</p>
    {config.rules.map(rule => {
      const original = linkId ? base.rules.find(item => item.id === rule.id) : undefined
      const changed = original && JSON.stringify(original) !== JSON.stringify(rule)
      return <fieldset key={rule.id} disabled={busy} className="min-w-0 space-y-3 border-b border-zinc-800 pb-5">
        <div className="flex items-center gap-2"><input aria-label="Правило включено" type="checkbox" checked={rule.enabled} onChange={e => patch(rule.id, { enabled: e.target.checked })} /><input aria-label="Название правила" className={input} value={rule.name} onChange={e => patch(rule.id, { name: e.target.value })} />
          {original ? <button type="button" title="Вернуть настройки проекта" className={button} onClick={() => patch(rule.id, original)}><RotateCcw size={16} /></button> : <button type="button" title="Удалить правило" className={button} onClick={() => { setSaved(false); setConfig({ ...config, rules: config.rules.filter(item => item.id !== rule.id) }) }}><Trash2 size={16} /></button>}
        </div>
        {linkId && <div className="text-xs text-zinc-400">{original ? changed ? 'Изменено для ссылки' : 'Из проекта' : 'Только для этой ссылки'}</div>}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-zinc-400">Назначение<select className={input} value={rule.destination} onChange={e => patch(rule.id, { destination: e.target.value as Rule['destination'] })}><option value="all">Все ссылки</option><option value="bot">Бот</option><option value="channel">Канал</option></select></label>
          <label className="text-xs text-zinc-400">Показатель<select className={input} value={rule.expression} onChange={e => {
            const expression = e.target.value
            const denominator = expression.match(/, (\w+)\)/)?.[1] ?? rule.sample_metric
            const quality = expression.includes('tagged_leads')
            patch(rule.id, { expression, sample_metric: denominator, min_coverage: denominator === 'assessed_leads' ? 70 : 0,
              operator: quality ? 'gt' : 'lt', threshold: quality ? 25 : 10, recovery_threshold: quality ? 20 : 15 })
          }}>
            <option value="percent(tagged_leads, assessed_leads)">Плохие среди оценённых, %</option><option value="percent(tagged_leads, leads)">Выбранные теги среди пришедших, %</option>
            <option value="percent(submitted_leads, leads)">Пришёл → подан, %</option><option value="percent(registrations, leads)">Пришёл → регистрация, %</option>
            <option value="percent(registered_depositors, registrations)">Регистрация → ФД, %</option><option value="percent(deposited_redepositors, first_deposits)">ФД → РД, %</option><option value="percent(request_funnel_starts, channel_join_requests)">Заявка → приветка, %</option>
            <option value="percent(approved_requests, channel_join_requests)">Заявка → подписка, %</option>
            <option value={rule.expression}>Формула: {rule.expression}</option>
          </select></label>
        </div>
        <label className="block text-xs text-zinc-400">Формула<input className={input} maxLength={500} value={rule.expression} onChange={e => patch(rule.id, { expression: e.target.value })} /></label>
        <details className="text-xs text-zinc-400"><summary>Обозначения показателей</summary><dl className="grid gap-1 py-2 sm:grid-cols-2">{Object.entries(metricLabels).map(([key, label]) => <div key={key}><dt className="inline font-mono">{key}</dt><dd className="inline"> — {label}</dd></div>)}</dl><p>percent(a, b), min(a, b), max(a, b), + − * /, and, or, сравнения. Логическая формула: 1 / 0. Расход: внесённые расходы за полные дни, одна валюта.</p></details>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <label className="text-xs text-zinc-400">Нарушение<select className={input} value={rule.operator} onChange={e => patch(rule.id, { operator: e.target.value as Rule['operator'], recovery_threshold: rule.threshold })}><option value="gt">Выше порога</option><option value="lt">Ниже порога</option></select></label>
          {(['threshold', 'recovery_threshold', 'window_hours', 'maturation_hours', 'min_sample', 'min_coverage', 'confirmations', 'repeat_hours'] as const).map(key => <label key={key} className="text-xs text-zinc-400">{{ threshold: 'Порог', recovery_threshold: 'Восстановление', window_hours: 'Период, часы', maturation_hours: 'Время на обработку, часы', min_sample: 'Минимальная выборка', min_coverage: 'Минимум оценено, %', confirmations: 'Проверок подряд', repeat_hours: 'Повтор, часы' }[key]}<input type="number" min={0} step={key.includes('threshold') || key === 'min_coverage' ? 'any' : 1} className={input} value={rule[key]} onChange={e => patch(rule.id, { [key]: Number(e.target.value) })} /></label>)}
          <label className="text-xs text-zinc-400">Выборка<select className={input} value={rule.sample_metric} onChange={e => patch(rule.id, { sample_metric: e.target.value })}>{Object.entries(metricLabels).filter(([key]) => !['spend', 'coverage'].includes(key)).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label className="text-xs text-zinc-400">Важность<select className={input} value={rule.severity} onChange={e => patch(rule.id, { severity: e.target.value as Rule['severity'] })}><option value="warning">Предупреждение</option><option value="critical">Критично</option></select></label>
          <label className="text-xs text-zinc-400">Совпадение тегов<select className={input} value={rule.tag_match} onChange={e => patch(rule.id, { tag_match: e.target.value as Rule['tag_match'] })}><option value="any">Хотя бы один</option><option value="all">Все выбранные</option></select></label>
        </div>
        <div className="grid gap-3 sm:grid-cols-2"><MultiSelect title="Теги для оценки качества" options={tags} value={rule.tag_ids} onChange={tag_ids => patch(rule.id, { tag_ids })} /><MultiSelect title="Теги завершённой оценки" options={tags} value={rule.assessed_tag_ids} onChange={assessed_tag_ids => patch(rule.id, { assessed_tag_ids })} /><MultiSelect title="Статусы завершённой оценки" options={leadStatuses} value={rule.assessed_status_codes} onChange={assessed_status_codes => patch(rule.id, { assessed_status_codes })} /><MultiSelect title="Боты (пусто — все)" options={bots} value={rule.bot_ids} onChange={bot_ids => patch(rule.id, { bot_ids })} /></div>
        <label className="block text-xs text-zinc-400">Типы рекламы (через запятую; пусто — все)<input className={input} value={rule.ad_types.join(', ')} onChange={e => patch(rule.id, { ad_types: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })} /></label>
        <div className="flex flex-wrap gap-4 text-sm">{(['notify_buyer', 'notify_admin', 'notify_recovery'] as const).map(key => <label key={key} className="flex items-center gap-2"><input type="checkbox" checked={rule[key]} onChange={e => patch(rule.id, { [key]: e.target.checked })} />{{ notify_buyer: 'Баеру', notify_admin: 'Администратору', notify_recovery: 'Сообщать о восстановлении' }[key]}</label>)}</div>
      </fieldset>
    })}
    <div className="flex flex-wrap gap-2"><button type="button" className={button} disabled={busy || config.rules.length >= (linkId ? base.rules.length + 10 : 30)} onClick={() => { setSaved(false); setConfig({ ...config, rules: [...config.rules, newRule()] }) }}><Plus size={16} />Правило</button><button type="button" className={button} disabled={busy} onClick={() => void preview()}><Play size={16} />Проверить без отправки</button><button type="button" className={`${button} bg-emerald-900`} disabled={busy} onClick={() => void save()}><Save size={16} />Сохранить правила</button></div>
    {!!results.length && <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th>Ссылка / правило</th><th>Значение / выборка</th><th>Результат</th></tr></thead><tbody>{results.map((r, i) => <tr key={`${r.link_id}-${i}`} className="border-t border-zinc-800"><td className="p-2">{r.link_title}<br />{r.rule_name}<br />{new Date(r.period_from).toLocaleString()} — {new Date(r.period_to).toLocaleString()}</td><td className="p-2">{r.value?.toFixed(2) ?? '—'} / {r.sample ?? '—'}</td><td className="p-2">{statuses[r.status] ?? r.status}<br />{r.reason}</td></tr>)}</tbody></table></div>}
    {nextOffset !== null && <button type="button" className={button} disabled={busy} onClick={() => void preview(nextOffset)}>Следующие ссылки</button>}
    <div className="border-t border-zinc-800 pt-4"><button type="button" className={button} disabled={busy} onClick={() => void history()}><RefreshCw size={16} />Журнал доставки</button>
      <button type="button" className={button} disabled={busy} onClick={() => void loadChecks()}>Последние проверки</button>
      <button type="button" className={button} disabled={busy} onClick={() => void loadAudit()}>Изменения настроек</button>
      {checks.map(item => <p key={`${item.link_id}-${item.rule_id}`} className="border-b border-zinc-800 py-2 text-xs">{item.link_title} · {item.snapshot.rule_name} · {statuses[item.status] ?? item.status} · {new Date(item.checked_at).toLocaleString()}<br />{item.snapshot.reason ?? `${item.snapshot.expression ?? ''} = ${item.snapshot.value ?? '—'}`}</p>)}
      {audits.map((item, index) => <details key={index} className="border-b border-zinc-800 py-2 text-xs"><summary>{new Date(item.at).toLocaleString()} · {item.actor_id} · {item.entity_type}</summary><pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(item.changes, null, 2)}</pre></details>)}
      {deliveries.map(item => <details key={item.id} className="border-b border-zinc-800 py-3 text-xs"><summary>{new Date(item.created_at).toLocaleString()} · {statuses[item.status] ?? item.status} · попыток: {item.attempts}</summary><p className="whitespace-pre-wrap py-2">{item.body}</p>{item.error && <p className="text-red-300">{item.error}</p>}</details>)}
      {!!deliveries.length && historyOffset !== null && <button type="button" className={button} disabled={busy} onClick={() => void history(historyOffset)}>Ещё записи</button>}
    </div>
  </section>
}

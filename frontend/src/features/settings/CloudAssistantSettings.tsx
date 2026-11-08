import { Check, Copy, Eye, Link2, LoaderCircle, RefreshCw, ShieldCheck, Unplug, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import axios from 'axios'
import api from '../../api/client'

type Status = { enabled: boolean; allowed: boolean; mcp_enabled: boolean; changes_enabled: boolean; resource_url: string | null }
type Project = { id: string; name: string }
type Connection = { id: string; client_id: string; project_ids: string[]; scopes: string[]; revoked_at: string | null; last_used_at?: string | null }
type Effect = { kind: string; target_id: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> }
type Proposal = { id: string; project_id: string; status: string; plan_hash: string; expires_at: string; effects: Effect[]; result: unknown; error_code: string | null }
const base = '/assistant'
const inputClass = 'min-w-0 w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm text-zinc-100'
const buttonClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-white/15 px-3 text-sm disabled:cursor-not-allowed disabled:opacity-40'
const scopes: Record<string, string> = { 'crm.catalog.read': 'Каталог проектов и ботов', 'crm.analytics.read': 'Статистика',
  'crm.configuration.read': 'Настройки', 'crm.diagnostics.read': 'Диагностика', 'crm.leads.summary.read': 'Минимальные карточки лидов', 'crm.changes.prepare': 'Подготовка заявок на изменение' }
const statuses: Record<string, string> = { pending_approval: 'Ждёт подтверждения', applied: 'Применено', rejected: 'Отклонено', cancelled: 'Отменено', expired: 'Истёк срок', stale: 'Настройки изменились', failed: 'Ошибка применения' }
const actions: Record<string, string> = { 'offer.create_inactive': 'Создать выключенный оффер', 'offer.update_inactive': 'Изменить выключенный оффер', 'postback.create_disabled': 'Создать выключенный приём постбэков', 'postback.update_disabled': 'Изменить выключенный приём постбэков', 'funnel.assign_offer_draft': 'Выбрать оффер у черновика' }
const labels: Record<string, string> = { name: 'Название', partner_name: 'Партнёрка', url: 'Адрес оффера', postbacks_enabled: 'Использовать постбэки', is_active: 'Активен', identifier_parameter: 'Параметр персональной ссылки', offer_id: 'ID оффера', offer_name: 'Оффер', event_type: 'Событие', identifier_param: 'Параметр идентификатора', event_type_param: 'Параметр события', external_event_id_param: 'ID операции', amount_param: 'Параметр суммы', currency_param: 'Параметр валюты', occurred_at_param: 'Время события', require_event_id: 'Требовать ID операции' }
function errorText(error: unknown) {
  const code = axios.isAxiosError(error) ? error.response?.data?.detail : null
  const messages: Record<string, string> = { assistant_disabled: 'Модуль выключен на сервере.', changes_disabled: 'Применение и подготовка изменений выключены.', connection_revoked: 'Подключение отозвано.', stale_plan: 'План изменился. Подготовьте новую заявку.', interactive_approval_required: 'Подтверждение доступно только из CRM.', invalid_source_url: 'Некорректная ссылка.', invalid_arguments: 'Проверьте заполненные поля.', request_id_conflict: 'Этот идентификатор запроса уже использован.', assistant_access_denied: 'Подключение не разрешено этому аккаунту.', rate_limited: 'Слишком много запросов. Повторите позже.' }
  return typeof code === 'string' && messages[code] ? messages[code] : 'Запрос не выполнен. Обновите данные перед повторной попыткой.'
}
function flat(value: Record<string, unknown> | null): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value || {})) {
    if (key === 'secure_input_ref') continue
    if ((key === 'postback_mapping' || key === 'parameter_mapping') && item && typeof item === 'object') {
      for (const [child, v] of Object.entries(item)) result[child] = v
    } else result[key] = item
  }
  return result
}
function valueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Не задано'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (typeof value === 'object') {
    if ('host' in value) {
      const url = value as { host?: string; query_parameters?: string[] }
      return [url.host, url.query_parameters?.length ? `Параметры: ${url.query_parameters.join(', ')}` : ''].filter(Boolean).join(' · ')
    }
    return JSON.stringify(value)
  }
  return String(value)
}

export default function CloudAssistantSettings({ projectId }: { projectId: string | null }) {
  const [params, setParams] = useSearchParams()
  const authorizationQuery = params.get('assistant_authorize')
  const proposalId = params.get('assistant_proposal')
  const [status, setStatus] = useState<Status | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [proposal, setProposal] = useState<Proposal | null>(null)
  const [consent, setConsent] = useState<{ client_id: string; scopes: string[] } | null>(null)
  const [grants, setGrants] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [sourceUrl, setSourceUrl] = useState('')
  const [inputProject, setInputProject] = useState('')
  const [inputRef, setInputRef] = useState('')
  const [revealed, setRevealed] = useState<Record<string, string>>({})
  const sequence = useRef(0)
  const refresh = useCallback(async () => {
    const request = ++sequence.current
    setError(''); setRefreshing(true); setConfirmed(false); setRevealed({}); setProposal(null); setConsent(null)
    try {
      const { data: state } = await api.get<Status>(base + '/status')
      if (request !== sequence.current) return
      setStatus(state)
      if (!state.allowed) return
      const { data: p } = await api.get<Project[]>(base + '/projects')
      const { data: c } = await api.get<Connection[]>(base + '/connections')
      const q = projectId && p.some(item => item.id === projectId) ? (await api.get<Proposal[]>(base + '/proposals', { params: { project_id: projectId } })).data : []
      const selected = proposalId ? (await api.get<Proposal>(base + '/proposals/' + proposalId)).data : null
      const details = authorizationQuery ? (await api.get(base + '/authorization', { params: { query: authorizationQuery } })).data : null
      if (request !== sequence.current) return
      setProjects(p); setConnections(c); setProposals(q); setProposal(selected); setConsent(details)
      setConfirmed(false); setRevealed({})
      setInputProject(previous => p.some(item => item.id === previous) ? previous : p.find(item => item.id === projectId)?.id || p[0]?.id || '')
    } catch (err) { if (request === sequence.current) setError(errorText(err)) }
    finally { if (request === sequence.current) setRefreshing(false) }
  }, [projectId, proposalId, authorizationQuery])
  useEffect(() => { void refresh(); return () => { sequence.current++ } }, [refresh])

  const mutate = async (operation: () => Promise<unknown>) => {
    if (busy) return
    setBusy(true); setError('')
    try { await operation(); await refresh() } catch (err) { setError(errorText(err)) }
    finally { setBusy(false) }
  }
  const secureRefs = [...new Set(proposal?.effects.map(effect => effect.after.secure_input_ref).filter((ref): ref is string => typeof ref === 'string') || [])]
  const canApprove = proposal && proposal.status === 'pending_approval' && Date.parse(proposal.expires_at) > Date.now() &&
    status?.changes_enabled && confirmed && secureRefs.every(ref => revealed[ref]) && !busy && !refreshing
  const projectName = (id: string) => projects.find(p => p.id === id)?.name || id

  return <div className="min-w-0 space-y-6 text-zinc-100">
    <header className="flex items-center justify-between gap-3">
      <h2 className="text-lg font-semibold">Облачный помощник</h2>
      <button type="button" title="Обновить данные" className={buttonClass} disabled={busy || refreshing} onClick={() => void refresh()}><RefreshCw size={17} /></button>
    </header>
    {error && <p role="alert" className="break-words rounded-lg border border-red-400/30 p-3 text-sm text-red-200">{error}</p>}
    {!status ? <p role="status" className="text-sm text-zinc-400">Загрузка…</p> : !status.allowed ? <p className="text-sm text-zinc-400">{status.enabled ? 'Доступ к модулю не разрешён.' : 'Модуль выключен на сервере.'}</p> : <>
      <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-white/10 pb-4 text-sm">
        <span>Облачное подключение: {status.mcp_enabled ? 'Включено' : 'Выключено'}</span>
        <span>Изменения: {status.changes_enabled ? 'Через подтверждение' : 'Выключены'}</span>
        {status.resource_url && <span className="break-all text-zinc-400">{status.resource_url}</span>}
      </div>
      {consent && <section className="space-y-3 border-b border-white/10 pb-5">
        <h3 className="font-medium">Подключение {consent.client_id}</h3>
        <ul className="space-y-1 text-sm text-zinc-300">{consent.scopes.map(scope => <li key={scope}>{scopes[scope] || scope}</li>)}</ul>
        <div className="flex flex-wrap gap-4">{projects.map(p => <label key={p.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={grants.includes(p.id)} onChange={event => setGrants(previous => event.target.checked ? [...previous, p.id] : previous.filter(id => id !== p.id))} />{p.name}</label>)}</div>
        <p className="text-sm text-amber-200">Разрешённые данные будут передаваться в облачный чат. Изменения потребуют отдельного подтверждения в CRM.</p>
        <button type="button" className={buttonClass} disabled={!grants.length || busy || refreshing} onClick={() => void mutate(async () => {
          const { data } = await api.post(base + '/authorize', { authorization_query: authorizationQuery, project_ids: grants })
          window.location.assign(data.redirect_uri)
        })}><Link2 size={16} />Подключить выбранные проекты</button>
      </section>}
      <section className="space-y-3 border-b border-white/10 pb-5">
        <h3 className="font-medium">Подключения</h3>
        {!connections.length && <p className="text-sm text-zinc-500">Нет подключений.</p>}
        {connections.map(c => <div key={c.id} className="flex min-w-0 items-start justify-between gap-3 py-2">
          <div className="min-w-0 text-sm"><p className="break-words font-medium">{c.client_id} · {c.revoked_at ? 'Отозвано' : 'Активно'}</p>
            <p className="break-words text-zinc-400">{c.project_ids.map(projectName).join(', ')}</p>
            <p className="break-words text-zinc-500">{c.scopes.map(scope => scopes[scope] || scope).join(' · ')}</p>
            {c.last_used_at && <p className="mt-1 text-xs text-zinc-500">Последний доступ: {new Date(c.last_used_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })} МСК</p>}</div>
          {!c.revoked_at && <button type="button" title="Отозвать подключение" className={buttonClass} disabled={busy} onClick={() => {
            if (window.confirm('Отозвать доступ этого подключения?')) void mutate(() => api.post(base + '/connections/' + c.id + '/revoke'))
          }}><Unplug size={16} /></button>}
        </div>)}
      </section>
      {status.changes_enabled && <section className="space-y-3 border-b border-white/10 pb-5">
        <h3 className="font-medium">Защищённая ссылка оффера</h3>
        <div className="grid gap-3 md:grid-cols-[200px_minmax(0,1fr)_auto]">
          <select aria-label="Проект защищённой ссылки" className={inputClass} value={inputProject} onChange={e => { setInputProject(e.target.value); setInputRef('') }}>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <input aria-label="Исходная ссылка оффера" type="password" autoComplete="off" className={inputClass} value={sourceUrl} onChange={e => setSourceUrl(e.target.value)} />
          <button type="button" title="Сохранить защищённую ссылку" className={buttonClass} disabled={busy || !sourceUrl || !inputProject} onClick={() => void mutate(async () => {
            const { data } = await api.post(base + '/secure-inputs', { project_id: inputProject, value: sourceUrl }); setInputRef(data.id); setSourceUrl('')
          })}><ShieldCheck size={16} /></button>
        </div>
        {inputRef && <div className="flex min-w-0 items-center gap-2 text-sm"><code className="break-all">{inputRef}</code><button type="button" title="Скопировать ID для чата" className={buttonClass} onClick={() => void navigator.clipboard.writeText(inputRef).catch(() => setError('Не удалось скопировать ID.'))}><Copy size={15} /></button></div>}
      </section>}
      <section className="space-y-3">
        <h3 className="font-medium">Заявки · {projectId ? projectName(projectId) : 'Выберите проект'}</h3>
        {!proposals.length && <p className="text-sm text-zinc-500">Нет заявок.</p>}
        {proposals.map(p => <button key={p.id} type="button" className="flex w-full min-w-0 flex-wrap justify-between gap-2 border-b border-white/10 py-3 text-left text-sm" onClick={() => setParams({ assistant_proposal: p.id })}>
          <span className="break-all">{p.id}</span><span className="text-zinc-400">{statuses[p.status] || p.status}</span>
        </button>)}
      </section>
      {proposal && <section className="min-w-0 space-y-4 rounded-lg border border-white/20 p-4">
        <div><h3 className="font-semibold">Подтверждение · {projectName(proposal.project_id)}</h3><p className="mt-1 break-all text-xs text-zinc-500">{proposal.id}</p></div>
        <p className="text-sm">{statuses[proposal.status] || proposal.status} · до {new Date(proposal.expires_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })} МСК</p>
        {projectId && projectId !== proposal.project_id && <p className="text-sm text-amber-200">Проект заявки отличается от выбранного проекта.</p>}
        {proposal.effects.map((effect, index) => {
          const before = flat(effect.before), after = flat(effect.after)
          return <div key={index} className="min-w-0 space-y-2 border-b border-white/10 pb-4">
            <h4 className="text-sm font-medium">{index + 1}. {actions[effect.kind] || effect.kind}</h4>
            {effect.target_id && <p className="break-all text-xs text-zinc-500">ID: {effect.target_id}</p>}
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 text-xs text-zinc-500"><span>Было</span><span>Станет</span></div>
            {[...new Set([...Object.keys(before), ...Object.keys(after)])].map(key => <div key={key} className="min-w-0 text-sm">
              <p className="text-xs text-zinc-400">{labels[key] || key}</p>
              <div className="mt-1 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3"><span className="break-words [overflow-wrap:anywhere] text-zinc-500">{valueText(before[key])}</span><span className="break-words [overflow-wrap:anywhere]">{valueText(after[key])}</span></div>
            </div>)}
          </div>
        })}
        {secureRefs.map(ref => <div key={ref} className="min-w-0 space-y-2">
          <button type="button" className={buttonClass} disabled={busy} onClick={async () => {
            const request = sequence.current
            setBusy(true); setError('')
            try {
              const { data } = await api.post(base + '/secure-inputs/' + ref + '/reveal')
              if (request === sequence.current) setRevealed(previous => ({ ...previous, [ref]: data.value }))
            } catch (err) { if (request === sequence.current) setError(errorText(err)) }
            finally { setBusy(false) }
          }}><Eye size={16} />Проверить исходный адрес</button>
          {revealed[ref] && <p className="break-all rounded-lg bg-black/20 p-3 text-xs">{revealed[ref]}</p>}
        </div>)}
        <p className="text-sm text-amber-200">Без включения трафика, публикации воронки, отправки сообщений и изменения серверов.</p>
        {proposal.status === 'pending_approval' && <>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Подтверждаю показанные изменения в проекте «{projectName(proposal.project_id)}»</label>
          <div className="flex flex-wrap gap-3">
            <button type="button" className={buttonClass + ' border-emerald-400/40 text-emerald-200'} disabled={!canApprove} onClick={() => void mutate(() => api.post(base + '/proposals/' + proposal.id + '/approve-and-apply', { expected_plan_hash: proposal.plan_hash }))}>{busy ? <LoaderCircle size={16} className="animate-spin" /> : <Check size={16} />}Применить изменения</button>
            <button type="button" className={buttonClass} disabled={busy} onClick={() => void mutate(() => api.post(base + '/proposals/' + proposal.id + '/reject'))}><X size={16} />Отклонить</button>
          </div>
        </>}
        {proposal.error_code && <p className="text-sm text-red-200">Изменения не применены: {proposal.error_code}</p>}
        {proposal.status === 'applied' && <p className="break-words text-sm text-emerald-200">Результат сохранён. Настройки остаются в согласованном состоянии.</p>}
      </section>}
    </>}
  </div>
}

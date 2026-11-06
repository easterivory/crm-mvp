import axios from 'axios'
import { Check, Copy, LoaderCircle, Pencil, Plus, Save, Trash2, X } from 'lucide-react'
import { cloneElement, isValidElement, useEffect, useState } from 'react'
import api from '../../../api/client'

type Mapping = {
  identifier_param: string; event_type_param: string; external_event_id_param: string | null;
  amount_param: string | null; currency_param: string | null; occurred_at_param: string | null;
  time_format: 'iso' | 'unix_seconds' | 'unix_ms'; bind_external_id_param: string | null;
  event_aliases: Record<string, string>; require_event_id: boolean;
}
type Offer = { id: string; name: string; partner_name: string; source_url: string; postbacks_enabled: boolean;
  identifier_parameter: string | null; is_active: boolean; endpoint_id: string | null }
type OfferForm = Omit<Offer, 'id' | 'endpoint_id'> & { payout_policy_id: string | null; postback_mapping: Mapping | null }
type Terms = { rate: string; currency: string; min_deposit: string; deposit_currency: string;
  qualification_param: string | null; qualification_values: string[]; qualification_rejected_values: string[]; period: 'day' | 'week' | 'month' | 'custom';
  timezone: string; period_from: string | null; period_to: string | null; tier_mode: 'excess' | 'retroactive';
  tiers: { threshold: number; rate: string | null; bonus: string | null }[]; conditions_note: string }
type Policy = { id: string; name: string; partner_name: string; count_scope: 'offer' | 'partner_group'; version: number; terms: Terms }
type PolicyForm = Omit<Policy, 'id' | 'version'>
type FinanceRow = { policy_id: string; policy_name: string; version: number; offer_id: string | null;
  qualified_fd: number; rejected_fd: number; pending_fd: number; currency: string; estimated_commission: string;
  period_from: string; period_to_exclusive: string }
type Pending = { id: string; offer_id: string; lead_id: string; reason: string; occurred_at: string }
type Endpoint = { id: string; url: string; is_active: boolean; delivery_mode: string }

const field = 'w-full min-w-0 rounded-md border border-white/15 bg-black/20 px-3 py-2 text-sm text-gray-100 outline-none focus:border-cyan-300'
const command = 'inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-white/15 px-3 py-2 text-sm text-gray-100 hover:bg-white/5 disabled:opacity-40'
const mapping = (): Mapping => ({ identifier_param: 'sub1', event_type_param: 'event', external_event_id_param: 'transaction_id',
  amount_param: 'amount', currency_param: 'currency', occurred_at_param: 'occurred_at', time_format: 'iso',
  bind_external_id_param: 'player_id', event_aliases: {}, require_event_id: false })
const emptyOffer = (): OfferForm => ({ name: '', partner_name: '', source_url: '', postbacks_enabled: false,
  identifier_parameter: 'sub1', payout_policy_id: null, postback_mapping: mapping(), is_active: true })
const emptyPolicy = (): PolicyForm => ({ name: '', partner_name: '', count_scope: 'offer', terms: {
  rate: '0', currency: 'USD', min_deposit: '0', deposit_currency: 'USD', qualification_param: null,
  qualification_values: ['1', 'true', 'approved'], qualification_rejected_values: ['0', 'false', 'rejected', 'declined'], period: 'month', timezone: 'Europe/Moscow',
  period_from: null, period_to: null, tier_mode: 'excess', tiers: [], conditions_note: '',
} })
const qualificationReasons: Record<string, string> = {
  fd_time_not_provided: 'Партнёр не передал время FD',
  no_terms_at_fd_time: 'На дату FD не было условий выплаты',
  manual_review_required: 'Ручное событие: требуется проверка',
  deposit_amount_missing: 'Не передана сумма депозита',
  qualification_currency_mismatch: 'Валюта депозита не совпадает с валютой порога',
  qualification_not_received: 'Партнёр не передал квалификацию',
  partner_qualification_pending: 'Партнёр ещё не подтвердил квалификацию',
  additional_conditions_require_review: 'Дополнительные условия ПП требуют проверки',
}
function errorText(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(item => item.msg).join('; ')
  }
  return 'Не удалось выполнить запрос'
}
function Label({ text, children }: { text: string; children: React.ReactNode }) {
  const control = isValidElement<{ 'aria-label'?: string }>(children) && typeof children.type === 'string'
    && ['input', 'select', 'textarea'].includes(children.type) ? cloneElement(children, { 'aria-label': text }) : children
  return <label className="grid min-w-0 gap-1 text-xs text-gray-400">{text}{control}</label>
}

export default function GamblingOffersSettings({ projectId }: { projectId: string | null }) {
  const [tab, setTab] = useState<'offers' | 'policies' | 'finance'>('offers')
  const [offers, setOffers] = useState<Offer[]>([])
  const [policies, setPolicies] = useState<Policy[]>([])
  const [draft, setDraft] = useState<OfferForm | null>(null)
  const [offerId, setOfferId] = useState<string | null>(null)
  const [endpoint, setEndpoint] = useState<Endpoint | null>(null)
  const [policyDraft, setPolicyDraft] = useState<PolicyForm | null>(null)
  const [policyId, setPolicyId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [day, setDay] = useState(new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10))
  const [finance, setFinance] = useState<FinanceRow[]>([])
  const [financePolicyId, setFinancePolicyId] = useState('')
  const [unpricedFd, setUnpricedFd] = useState(0)
  const [pending, setPending] = useState<Pending[]>([])
  const [reviewReason, setReviewReason] = useState('')
  const [reviewAt, setReviewAt] = useState('')
  const params = { project_id: projectId }

  useEffect(() => {
    let active = true
    if (!projectId) return
    setLoading(true)
    Promise.all([api.get<Offer[]>('/gambling-offers', { params: { project_id: projectId } }),
      api.get<Policy[]>('/gambling-offers/payout-policies', { params: { project_id: projectId } })])
      .then(([o, p]) => { if (active) { setOffers(o.data); setPolicies(p.data) } })
      .catch(err => { if (active) setError(errorText(err)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId])

  async function loadFinance() {
    setBusy(true); setError('')
    try {
      const [report, review] = await Promise.all([api.get<{ rows: FinanceRow[]; unpriced_fd_all_time: number }>('/gambling-offers/finance', { params: { ...params, day, ...(financePolicyId ? { policy_id: financePolicyId } : {}) } }),
        api.get<Pending[]>('/gambling-offers/qualification', { params })])
      setFinance(report.data.rows); setUnpricedFd(report.data.unpriced_fd_all_time); setPending(review.data)
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  async function editOffer(id: string) {
    setBusy(true); setError('')
    try {
      const { data } = await api.get<Offer & { payout_policy_id: string | null; postback_mapping: Mapping | null; postback: Endpoint | null }>(`/gambling-offers/${id}/settings`, { params })
      setDraft({ name: data.name, partner_name: data.partner_name, source_url: data.source_url,
        postbacks_enabled: data.postbacks_enabled, identifier_parameter: data.identifier_parameter ?? 'sub1',
        payout_policy_id: data.payout_policy_id, postback_mapping: data.postback_mapping ?? mapping(), is_active: data.is_active })
      setEndpoint(data.postback); setOfferId(id)
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  async function saveOffer() {
    if (!draft || busy) return
    setBusy(true); setError('')
    try {
      const payload = { ...draft, postback_mapping: draft.postbacks_enabled ? draft.postback_mapping : null,
        identifier_parameter: draft.postbacks_enabled ? draft.identifier_parameter : null }
      const { data } = offerId ? await api.put<Offer>(`/gambling-offers/${offerId}`, payload, { params })
        : await api.post<Offer>('/gambling-offers', payload, { params })
      setOffers(previous => [...previous.filter(o => o.id !== data.id), data]); setOfferId(data.id)
      const settings = await api.get<{ postback: Endpoint | null }>(`/gambling-offers/${data.id}/settings`, { params })
      setEndpoint(settings.data.postback)
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  async function savePolicy() {
    if (!policyDraft || busy) return
    setBusy(true); setError('')
    try {
      if (policyId) await api.put(`/gambling-offers/payout-policies/${policyId}`, policyDraft, { params })
      else await api.post('/gambling-offers/payout-policies', policyDraft, { params })
      setPolicies((await api.get<Policy[]>('/gambling-offers/payout-policies', { params })).data)
      setPolicyDraft(null); setPolicyId(null)
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  async function toggleEndpoint() {
    if (!endpoint || busy || !window.confirm(endpoint.is_active ? 'Остановить приём постбэков?' : 'Включить приём постбэков этого оффера?')) return
    setBusy(true)
    try { setEndpoint((await api.patch<Endpoint>(`/postback-endpoints/${endpoint.id}`, { is_active: !endpoint.is_active }, { params })).data) }
    catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  async function review(id: string, qualified: boolean) {
    if (!reviewReason.trim() || busy || !window.confirm(qualified ? 'Подтвердить квалификацию FD?' : 'Отклонить квалификацию FD?')) return
    setBusy(true); setError('')
    try {
      await api.post(`/gambling-offers/qualification/${id}`, { qualified, reason: reviewReason,
        ...(qualified && reviewAt ? { occurred_at: new Date(reviewAt).toISOString() } : {}) }, { params })
      setPending(rows => rows.filter(r => r.id !== id)); setReviewReason(''); setReviewAt('')
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }
  function setTerms(value: Partial<Terms>) { setPolicyDraft(p => p ? { ...p, terms: { ...p.terms, ...value } } : null) }
  function setMapping(value: Partial<Mapping>) { setDraft(d => d ? { ...d, postback_mapping: { ...(d.postback_mapping ?? mapping()), ...value } } : null) }

  if (!projectId) return null
  return <section className="min-w-0 space-y-5" aria-label="Гембл-офферы">
    <div role="tablist" className="flex flex-wrap gap-2 border-b border-white/10 pb-3">
      {(['offers', 'policies', 'finance'] as const).map(key => <button type="button" role="tab" aria-selected={tab === key}
        key={key} className={`${command} ${tab === key ? 'border-emerald-300/50 bg-emerald-300/10' : ''}`} onClick={() => { setTab(key); setError('') }}>
        {{ offers: 'Офферы', policies: 'Условия выплат', finance: 'Вознаграждение' }[key]}</button>)}
    </div>
    {error && <p role="alert" className="break-words text-sm text-red-300">{error}</p>}
    {loading && <LoaderCircle className="animate-spin" size={18} />}
    {tab === 'offers' && <>
      <button className={command} onClick={() => { setDraft(emptyOffer()); setOfferId(null); setEndpoint(null) }}><Plus size={16} />Оффер</button>
      <div className="divide-y divide-white/10">
        {offers.map(o => <div key={o.id} className="flex min-w-0 items-center justify-between gap-3 py-3">
          <div className="min-w-0"><p className="break-words text-sm text-gray-100">{o.name}</p>
            <p className="break-words text-xs text-gray-400">{o.partner_name} · {o.postbacks_enabled ? 'Постбэки' : 'Обычная ссылка'} · {o.is_active ? 'Действует' : 'Отключён'}</p></div>
          <button className={command} disabled={busy} title="Редактировать оффер" onClick={() => void editOffer(o.id)}><Pencil size={16} /></button>
        </div>)}
      </div>
      {draft && <form onSubmit={e => { e.preventDefault(); void saveOffer() }} className="grid min-w-0 gap-4 border-t border-white/15 pt-4">
        <div className="grid gap-4 md:grid-cols-2">
          <Label text="Название"><input required className={field} value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></Label>
          <Label text="Партнёрская программа"><input required className={field} value={draft.partner_name} onChange={e => setDraft({ ...draft, partner_name: e.target.value })} /></Label>
        </div>
        <Label text="Исходная ссылка"><input required type="url" className={field} value={draft.source_url} onChange={e => setDraft({ ...draft, source_url: e.target.value })} /></Label>
        <div className="flex flex-wrap gap-5 text-sm text-gray-200">
          <label className="flex items-center gap-2"><input type="checkbox" checked={draft.is_active} onChange={e => setDraft({ ...draft, is_active: e.target.checked })} />Оффер действует</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={draft.postbacks_enabled} onChange={e => setDraft({ ...draft, postbacks_enabled: e.target.checked })} />Использовать постбэки</label>
        </div>
        <Label text="Условия выплаты"><select className={field} value={draft.payout_policy_id ?? ''} onChange={e => setDraft({ ...draft, payout_policy_id: e.target.value || null })}>
          <option value="">Не заданы</option>{policies.filter(p => p.partner_name.toLowerCase() === draft.partner_name.toLowerCase()).map(p => <option key={p.id} value={p.id}>{p.name} · v{p.version}</option>)}
        </select></Label>
        {draft.postbacks_enabled && <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Label text="Параметр в исходящей ссылке"><input required className={field} value={draft.identifier_parameter ?? ''} onChange={e => setDraft({ ...draft, identifier_parameter: e.target.value })} /></Label>
            {([['identifier_param', 'Идентификатор в постбэке'], ['event_type_param', 'Поле REG / FD / RD'], ['external_event_id_param', 'ID операции'],
              ['amount_param', 'Сумма депозита'], ['currency_param', 'Валюта депозита'], ['occurred_at_param', 'Время события'], ['bind_external_id_param', 'Player ID']] as const).map(([key, label]) => (
              <Label key={key} text={label}><input className={field} value={draft.postback_mapping?.[key] ?? ''} onChange={e => setMapping({ [key]: e.target.value || null })} /></Label>))}
            <Label text="Формат времени"><select className={field} value={draft.postback_mapping?.time_format ?? 'iso'} onChange={e => setMapping({ time_format: e.target.value as Mapping['time_format'] })}>
              <option value="iso">ISO с часовым поясом</option><option value="unix_seconds">Unix, секунды</option><option value="unix_ms">Unix, миллисекунды</option></select></Label>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-200"><input type="checkbox" checked={draft.postback_mapping?.require_event_id ?? false} onChange={e => setMapping({ require_event_id: e.target.checked })} />ID операции обязателен для всех событий</label>
          <fieldset className="space-y-2"><legend className="mb-2 text-xs text-gray-400">Обозначения событий ПП</legend>
            {Object.entries(draft.postback_mapping?.event_aliases ?? {}).map(([key, value], index) => <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2" key={index}>
              <input className={field} aria-label="Событие партнёра" value={key} onChange={e => { const pairs = Object.entries(draft.postback_mapping?.event_aliases ?? {}); pairs[index][0] = e.target.value; setMapping({ event_aliases: Object.fromEntries(pairs) }) }} />
              <select className={field} value={value} onChange={e => setMapping({ event_aliases: { ...draft.postback_mapping?.event_aliases, [key]: e.target.value } })}><option value="registration">REG</option><option value="deposit">FD</option><option value="redeposit">RD</option></select>
              <button type="button" className={command} title="Удалить обозначение" onClick={() => setMapping({ event_aliases: Object.fromEntries(Object.entries(draft.postback_mapping?.event_aliases ?? {}).filter(([name]) => name !== key)) })}><Trash2 size={15} /></button>
            </div>)}
            <button type="button" className={command} onClick={() => setMapping({ event_aliases: { ...draft.postback_mapping?.event_aliases, ['event_' + (Object.keys(draft.postback_mapping?.event_aliases ?? {}).length + 1)]: 'registration' } })}><Plus size={15} />Обозначение</button>
          </fieldset>
        </>}
        <div className="flex gap-2"><button className={command} disabled={busy} type="submit"><Save size={16} />Сохранить оффер</button><button className={command} type="button" title="Закрыть редактор" onClick={() => setDraft(null)}><X size={16} /></button></div>
        {endpoint && <div className="space-y-3 border-t border-white/10 pt-4">
          <Label text="Адрес приёма постбэков"><div className="flex min-w-0 gap-2"><input aria-label="Адрес приёма постбэков" readOnly className={field} value={endpoint.url} /><button type="button" className={command} title="Скопировать адрес" onClick={() => void navigator.clipboard.writeText(endpoint.url).catch(() => setError('Не удалось скопировать адрес'))}><Copy size={16} /></button></div></Label>
          <label className="flex items-center gap-2 text-sm text-gray-200"><input type="checkbox" checked={endpoint.is_active} disabled={busy} onChange={() => void toggleEndpoint()} />Приём постбэков включён</label>
        </div>}
      </form>}
    </>}
    {tab === 'policies' && <>
      <button className={command} onClick={() => { setPolicyDraft(emptyPolicy()); setPolicyId(null) }}><Plus size={16} />Условия выплаты</button>
      {policies.map(p => <div key={p.id} className="flex min-w-0 items-center justify-between gap-3 border-b border-white/10 py-3">
        <div className="min-w-0 text-sm text-gray-100"><p className="break-words">{p.name} · v{p.version}</p><p className="break-words text-xs text-gray-400">{p.partner_name} · {p.terms.rate} {p.terms.currency} / FD · {p.count_scope === 'offer' ? 'По офферу' : 'Группа офферов ПП'}</p></div>
        <button className={command} title="Новая версия условий" onClick={() => { const { id, version, ...form } = p; setPolicyId(id); setPolicyDraft(structuredClone(form)) }}><Pencil size={16} /></button>
      </div>)}
      {policyDraft && <form onSubmit={e => { e.preventDefault(); void savePolicy() }} className="grid gap-4 border-t border-white/15 pt-4">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Label text="Название условий"><input required className={field} value={policyDraft.name} onChange={e => setPolicyDraft({ ...policyDraft, name: e.target.value })} /></Label>
          <Label text="Партнёрская программа"><input required disabled={!!policyId} className={field} value={policyDraft.partner_name} onChange={e => setPolicyDraft({ ...policyDraft, partner_name: e.target.value })} /></Label>
          <Label text="Подсчёт FD"><select disabled={!!policyId} className={field} value={policyDraft.count_scope} onChange={e => setPolicyDraft({ ...policyDraft, count_scope: e.target.value as PolicyForm['count_scope'] })}><option value="offer">Отдельно по офферу</option><option value="partner_group">Все офферы с этими условиями</option></select></Label>
          {([['rate', 'Ставка за FD'], ['min_deposit', 'Минимальный депозит']] as const).map(([key, label]) => <Label key={key} text={label}><input required type="number" min="0" step="0.01" className={field} value={policyDraft.terms[key]} onChange={e => setTerms({ [key]: e.target.value })} /></Label>)}
          {([['currency', 'Валюта вознаграждения'], ['deposit_currency', 'Валюта порога депозита']] as const).map(([key, label]) => <Label key={key} text={label}><input required maxLength={10} pattern="[A-Z]{3,10}" className={field} value={policyDraft.terms[key]} onChange={e => setTerms({ [key]: e.target.value.toUpperCase() })} /></Label>)}
          <Label text="Поле квалификации от ПП"><input className={field} value={policyDraft.terms.qualification_param ?? ''} onChange={e => setTerms({ qualification_param: e.target.value || null })} /></Label>
          <Label text="Значения подтверждения, через запятую"><input className={field} value={policyDraft.terms.qualification_values.join(', ')} onChange={e => setTerms({ qualification_values: e.target.value.split(',').map(v => v.trim()) })} /></Label>
          <Label text="Значения отказа, через запятую"><input className={field} value={policyDraft.terms.qualification_rejected_values.join(', ')} onChange={e => setTerms({ qualification_rejected_values: e.target.value.split(',').map(v => v.trim()).filter(Boolean) })} /></Label>
          <Label text="Расчётный период"><select className={field} value={policyDraft.terms.period} onChange={e => setTerms({ period: e.target.value as Terms['period'] })}><option value="day">День</option><option value="week">Неделя, пн–вс</option><option value="month">Месяц</option><option value="custom">Заданные даты</option></select></Label>
          <Label text="Часовой пояс"><input className={field} value={policyDraft.terms.timezone} onChange={e => setTerms({ timezone: e.target.value })} /></Label>
          <Label text="Повышенная ставка"><select className={field} value={policyDraft.terms.tier_mode} onChange={e => setTerms({ tier_mode: e.target.value as Terms['tier_mode'] })}><option value="excess">Только сверх порога</option><option value="retroactive">Пересчёт периода по закреплённой версии</option></select></Label>
          {policyDraft.terms.period === 'custom' && <>{(['period_from', 'period_to'] as const).map((key, index) => <Label key={key} text={index ? 'Последний день' : 'Первый день'}><input required type="date" className={field} value={policyDraft.terms[key] ?? ''} onChange={e => setTerms({ [key]: e.target.value || null })} /></Label>)}</>}
        </div>
        <fieldset className="space-y-2"><legend className="mb-2 text-xs text-gray-400">Мотивационная сетка</legend>
          {policyDraft.terms.tiers.map((tier, index) => <div key={index} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] gap-2">
            <input aria-label="Порог FD" type="number" min={1} required className={field} value={tier.threshold} onChange={e => setTerms({ tiers: policyDraft.terms.tiers.map((t, i) => i === index ? { ...t, threshold: Number(e.target.value) } : t) })} />
            <select aria-label="Вид мотивации" className={field} value={tier.rate === null ? 'bonus' : 'rate'} onChange={e => setTerms({ tiers: policyDraft.terms.tiers.map((t, i) => i === index ? { ...t, rate: e.target.value === 'rate' ? '0' : null, bonus: e.target.value === 'bonus' ? '0' : null } : t) })}><option value="rate">Ставка</option><option value="bonus">Бонус</option></select>
            <input aria-label="Размер мотивации" type="number" min={0} step="0.01" required className={field} value={tier.rate ?? tier.bonus ?? '0'} onChange={e => setTerms({ tiers: policyDraft.terms.tiers.map((t, i) => i === index ? { ...t, ...(t.rate !== null ? { rate: e.target.value } : { bonus: e.target.value }) } : t) })} />
            <button type="button" className={command} title="Удалить порог" onClick={() => setTerms({ tiers: policyDraft.terms.tiers.filter((_, i) => i !== index) })}><Trash2 size={15} /></button>
          </div>)}
          <button type="button" className={command} onClick={() => setTerms({ tiers: [...policyDraft.terms.tiers, { threshold: (policyDraft.terms.tiers[policyDraft.terms.tiers.length - 1]?.threshold ?? 0) + 10, rate: '0', bonus: null }] })}><Plus size={15} />Порог</button>
        </fieldset>
        <Label text="Дополнительные условия ПП"><textarea className={field} value={policyDraft.terms.conditions_note} onChange={e => setTerms({ conditions_note: e.target.value })} /></Label>
        <div className="flex gap-2"><button disabled={busy} className={command}><Save size={16} />{policyId ? 'Сохранить новую версию' : 'Сохранить условия'}</button><button type="button" className={command} title="Закрыть редактор" onClick={() => setPolicyDraft(null)}><X size={16} /></button></div>
      </form>}
    </>}
    {tab === 'finance' && <>
      {unpricedFd > 0 && <p className="text-sm text-amber-200">FD без действовавших на дату события условий: {unpricedFd}. Вознаграждение не определено.</p>}
      <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); void loadFinance() }}>
        <Label text="Дата расчётного периода"><input required type="date" className={field} value={day} onChange={e => setDay(e.target.value)} /></Label>
        <Label text="Программа выплат"><select className={field} value={financePolicyId} onChange={e => setFinancePolicyId(e.target.value)}><option value="">Все программы</option>{policies.map(p => <option key={p.id} value={p.id}>{p.name} · {p.partner_name}</option>)}</select></Label>
        <button disabled={busy} className={command}>{busy && <LoaderCircle size={16} className="animate-spin" />}Рассчитать</button>
      </form>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm text-gray-200"><thead className="text-xs text-gray-400"><tr><th className="p-2">Условия</th><th className="p-2">Период</th><th className="p-2">Оффер</th><th className="p-2">Зачтено / проверка / отказ</th><th className="p-2">Расчётное вознаграждение</th></tr></thead><tbody>
        {finance.map((r, i) => <tr key={i} className="border-t border-white/10"><td className="p-2">{r.policy_name} · v{r.version}</td><td className="p-2">{new Date(r.period_from).toLocaleDateString('ru-RU', { timeZone: 'Europe/Moscow' })}</td><td className="p-2">{offers.find(o => o.id === r.offer_id)?.name ?? 'Группа ПП'}</td><td className="p-2">{r.qualified_fd} / {r.pending_fd} / {r.rejected_fd}</td><td className="p-2 tabular-nums">{r.estimated_commission} {r.currency}</td></tr>)}
      </tbody></table></div>
      {pending.length > 0 && <section className="space-y-3 border-t border-white/10 pt-4"><h3 className="text-sm font-semibold text-gray-200">Проверка квалификации FD</h3><Label text="Основание решения"><input className={field} maxLength={255} value={reviewReason} onChange={e => setReviewReason(e.target.value)} /></Label>
        <Label text="Уточнённое время FD"><input className={field} type="datetime-local" value={reviewAt} onChange={e => setReviewAt(e.target.value)} /></Label>
        {pending.map(r => <div key={r.id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-white/10 py-2"><div className="min-w-0 text-xs text-gray-300"><p>{offers.find(o => o.id === r.offer_id)?.name ?? r.offer_id}</p><p className="break-all">{r.lead_id}</p><p>{qualificationReasons[r.reason] ?? r.reason}</p></div><div className="flex gap-2"><button className={command} disabled={busy || !reviewReason.trim()} title="Зачесть FD" onClick={() => void review(r.id, true)}><Check size={16} /></button><button className={command} disabled={busy || !reviewReason.trim()} title="Не зачитывать FD" onClick={() => void review(r.id, false)}><X size={16} /></button></div></div>)}
      </section>}
    </>}
  </section>
}

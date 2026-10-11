import { FormEvent, useEffect, useState } from 'react'
import { Copy, LoaderCircle, Pencil, Radio, RefreshCw, RotateCcw } from 'lucide-react'
import axios from 'axios'
import api from '../../api/client'
import { Modal } from '../../shared/ui'
import { FacebookEventMappingsEditor } from '../landers/components/LandersSettings'
import { createProjectLander, fetchLanderRuntimeConfig, fetchProjectDomains, fetchProjectLanders, updateProjectLander } from '../landers/api'
import type { FacebookEventMapping, LanderRuntimeConfig, ProjectDomain, ProjectLander } from '../landers/types'
import type { TrackingLink } from './types'

type Config = { enabled: boolean; pixel_id: string; has_token: boolean; test_event_code: string | null; mappings: FacebookEventMapping[] }
type Delivery = { id: string; event_name: string; source_event: string; status: string; attempts: number; request_id: string | null; error: string | null; has_click_id: boolean; created_at: string }
const inputClass = 'w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-white'
const statusNames: Record<string, string> = { sent: 'Принято TikTok', failed: 'Ошибка', pending: 'В очереди', sending: 'Отправляется', retry: 'Повторная попытка', cancelled: 'Отключено' }

function errorText(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return 'Не удалось выполнить запрос. Попробуйте ещё раз.'
}

export default function TikTokSettings({ link, projectId }: { link: TrackingLink; projectId: string }) {
  const [open, setOpen] = useState(false)
  const [config, setConfig] = useState<Config | null>(null)
  const [runtime, setRuntime] = useState<LanderRuntimeConfig | null>(null)
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [landers, setLanders] = useState<ProjectLander[]>([])
  const [domains, setDomains] = useState<ProjectDomain[]>([])
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [slug, setSlug] = useState('')
  const [domain, setDomain] = useState('')
  const [editingLander, setEditingLander] = useState<ProjectLander | null>(null)
  const url = `/tracking/links/${link.id}/tiktok`
  const params = { project_id: projectId }

  useEffect(() => {
    if (!open) return
    let active = true
    setConfig(null); setError(''); setNotice(''); setToken(''); setEditingLander(null)
    Promise.all([api.get<Config>(url, { params }), api.get<Delivery[]>(`${url}/deliveries`, { params }),
      fetchLanderRuntimeConfig(projectId), fetchProjectLanders(projectId), fetchProjectDomains(projectId)])
      .then(([settings, log, options, pages, hosts]) => {
        if (!active) return
        setConfig(settings.data); setDeliveries(log.data); setRuntime(options)
        setLanders(pages.filter((page) => page.tracking_link_id === link.id)); setDomains(hosts)
      }).catch((e) => { if (active) setError(errorText(e)) })
    return () => { active = false }
  }, [open, link.id, projectId])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!config || busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      const { data } = await api.put<Config>(url, { ...config, ...(token.trim() ? { access_token: token.trim() } : {}) }, { params })
      setConfig(data); setToken(''); setNotice('Настройки TikTok сохранены.')
    } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }

  async function refresh() {
    setBusy(true); setError('')
    try { setDeliveries((await api.get<Delivery[]>(`${url}/deliveries`, { params })).data) }
    catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }

  async function retry(id: string) {
    setBusy(true); setError('')
    try {
      await api.post(`${url}/deliveries/${id}/retry`, {}, { params })
      setDeliveries((await api.get<Delivery[]>(`${url}/deliveries`, { params })).data)
    } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }

  async function createLander() {
    if (!slug.trim() || busy) return
    setBusy(true); setError('')
    try {
      const page = await createProjectLander(projectId, { name: `TikTok · ${link.title}`, domain_id: domain || null,
        slug: slug.trim(), tracking_link_id: link.id, type: 'default_tg_redirect', auto_redirect_enabled: false,
        utm_defaults: { utm_source: 'tiktok', utm_medium: 'paid_social' } })
      setLanders((items) => [...items, page]); setSlug(''); setNotice('Лендинг создан.')
    } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }

  async function saveLander() {
    if (!editingLander || busy) return
    setBusy(true); setError('')
    try {
      const page = await updateProjectLander(projectId, editingLander.id, {
        name: editingLander.name, description: editingLander.description, button_text: editingLander.button_text,
        badge_text: editingLander.badge_text, auto_redirect_enabled: editingLander.auto_redirect_enabled,
      })
      setLanders((items) => items.map((item) => item.id === page.id ? page : item)); setEditingLander(null)
    } catch (e) { setError(errorText(e)) } finally { setBusy(false) }
  }

  return <>
    <button type="button" onClick={() => setOpen(true)} title="Настроить события TikTok"
      className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-xs text-gray-200"><Radio size={15} />TikTok</button>
    {open && <Modal maxWidthClassName="max-w-6xl" onClose={() => { if (!busy) setOpen(false) }} title={`TikTok · ${link.title}`}>
      <div className="space-y-5">
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
        {notice && <p role="status" className="text-sm text-emerald-300">{notice}</p>}
        {!config && !error && <LoaderCircle className="animate-spin" />}
        {config && runtime && <>
          <form onSubmit={save} className="space-y-4">
            <label className="flex items-center gap-3"><input type="checkbox" checked={config.enabled} onChange={(e) => setConfig({ ...config, enabled: e.target.checked })} />Отправлять события в TikTok</label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm">Pixel ID<input className={inputClass} value={config.pixel_id} maxLength={120} required={config.enabled} onChange={(e) => setConfig({ ...config, pixel_id: e.target.value })} /></label>
              <label className="space-y-1 text-sm">Access Token<input className={inputClass} type="password" autoComplete="new-password" maxLength={4096} value={token} placeholder={config.has_token ? 'Сохранён; оставить пустым' : 'Access Token'} required={config.enabled && !config.has_token} onChange={(e) => setToken(e.target.value)} /></label>
              <label className="space-y-1 text-sm">Test Event Code<input className={inputClass} value={config.test_event_code ?? ''} maxLength={100} onChange={(e) => setConfig({ ...config, test_event_code: e.target.value || null })} /></label>
            </div>
            <FacebookEventMappingsEditor provider="TikTok" mappings={config.mappings} sourceEvents={runtime.source_events}
              statuses={runtime.lead_statuses} tags={runtime.tags} destinationType={link.destination_type}
              onChange={(mappings) => setConfig({ ...config, mappings })} />
            <datalist id="tiktok-standard-events">{['ViewContent', 'Contact', 'SubmitForm', 'CompleteRegistration', 'Subscribe', 'Purchase', 'StartTrial', 'SubmitApplication', 'Schedule', 'ApplicationApproval'].map((name) => <option key={name} value={name} />)}</datalist>
            <button type="submit" disabled={busy} className="rounded-lg bg-accent-400 px-4 py-2 text-sm font-medium text-black disabled:opacity-50">{busy ? 'Сохранение…' : 'Сохранить TikTok'}</button>
          </form>
          <section className="space-y-3 border-t border-white/10 pt-4">
            <h3 className="text-sm font-semibold">Рекламные лендинги</h3>
            {landers.map((page) => <div key={page.id} className="flex min-w-0 items-center gap-2">
              <a className="min-w-0 flex-1 break-all text-sm text-cyan-200" href={page.public_url} target="_blank" rel="noreferrer">{page.public_url}</a>
              <button type="button" title="Копировать ссылку" onClick={() => navigator.clipboard.writeText(page.public_url).then(() => setNotice('Ссылка скопирована.')).catch(() => setError('Не удалось скопировать ссылку.'))}><Copy size={16} /></button>
              <button type="button" title="Редактировать лендинг" onClick={() => setEditingLander(page)}><Pencil size={16} /></button>
            </div>)}
            {editingLander && <div className="space-y-3 border-y border-white/10 py-3">
              <label className="block space-y-1 text-sm">Название<input className={inputClass} maxLength={255} value={editingLander.name} onChange={(e) => setEditingLander({ ...editingLander, name: e.target.value })} /></label>
              <label className="block space-y-1 text-sm">Описание<textarea className={inputClass} maxLength={1000} value={editingLander.description ?? ''} onChange={(e) => setEditingLander({ ...editingLander, description: e.target.value })} /></label>
              <label className="block space-y-1 text-sm">Текст кнопки<input className={inputClass} maxLength={80} value={editingLander.button_text ?? ''} onChange={(e) => setEditingLander({ ...editingLander, button_text: e.target.value })} /></label>
              <label className="block space-y-1 text-sm">Подпись<input className={inputClass} maxLength={80} value={editingLander.badge_text ?? ''} onChange={(e) => setEditingLander({ ...editingLander, badge_text: e.target.value })} /></label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editingLander.auto_redirect_enabled} onChange={(e) => setEditingLander({ ...editingLander, auto_redirect_enabled: e.target.checked })} />Автоматически открывать Telegram</label>
              <button type="button" disabled={busy || !editingLander.name.trim()} onClick={() => void saveLander()} className="rounded-lg border border-white/10 px-3 py-2 text-sm">Сохранить лендинг</button>
            </div>}
            <div className="grid gap-2 sm:grid-cols-2">
              <select aria-label="Домен лендинга" className={inputClass} value={domain} onChange={(e) => setDomain(e.target.value)}><option value="">{runtime.technical_domain}</option>{domains.filter((d) => d.is_active).map((d) => <option key={d.id} value={d.id}>{d.domain_name}</option>)}</select>
              <input aria-label="Слаг лендинга" className={inputClass} placeholder="Слаг лендинга" value={slug} maxLength={100} onChange={(e) => setSlug(e.target.value)} />
            </div>
            <button type="button" disabled={busy || !slug.trim()} onClick={() => void createLander()} className="rounded-lg border border-white/10 px-3 py-2 text-sm disabled:opacity-50">Создать лендинг</button>
          </section>
          <section className="space-y-3 border-t border-white/10 pt-4">
            <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">Последние события</h3><button type="button" disabled={busy} title="Обновить события" onClick={() => void refresh()}><RefreshCw size={16} /></button></div>
            {!deliveries.length && <p className="text-sm text-gray-400">Событий пока нет.</p>}
            <div className="space-y-2">{deliveries.map((item) => <div key={item.id} className="flex items-start justify-between gap-2 border-b border-white/5 pb-2 text-xs">
              <div className="min-w-0"><p>{item.event_name} · {item.source_event} · {statusNames[item.status] ?? item.status}</p>
                <p className="text-gray-400">{new Date(item.created_at).toLocaleString()} · {item.has_click_id ? 'Click ID сохранён' : 'Нет рекламного Click ID'}</p>
                <p className="break-all text-gray-500">Попыток: {item.attempts}{item.request_id ? ` · Request ID: ${item.request_id}` : ''}</p>
                {item.error && <p className="break-words text-red-300">{item.error}</p>}</div>
              {['failed', 'cancelled'].includes(item.status) && <button type="button" disabled={busy} title="Повторить отправку" onClick={() => void retry(item.id)}><RotateCcw size={16} /></button>}
            </div>)}</div>
          </section>
        </>}
      </div>
    </Modal>}
  </>
}

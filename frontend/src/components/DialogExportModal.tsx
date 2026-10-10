import { useEffect, useState } from 'react'
import { Download, LoaderCircle, X } from 'lucide-react'
import api from '../api/client'
import { Modal } from '../shared/ui'

type ExportStatus = {
  id: string; status: 'queued' | 'running' | 'ready' | 'failed' | 'cancelled' | 'cancelling'
  chats: number; messages: number; size_bytes: number; error?: string
  request: { bot_id: string | null; format: string; date_from: string | null; date_to: string | null; include_contacts: boolean }
}
const labels = { queued: 'В очереди', running: 'Собираем диалоги', ready: 'Готово', failed: 'Ошибка', cancelled: 'Отменено', cancelling: 'Отменяем' }
const inputClass = 'w-full rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm text-white'
const secondaryClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-white/15 px-4 py-2 text-sm font-medium text-gray-200 hover:bg-white/5 disabled:opacity-50'
const primaryClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-accent-400 px-4 py-2 text-sm font-semibold text-black hover:bg-accent-300 disabled:opacity-50'

export default function DialogExportModal({ projectId, bots, initialBotId, onClose }: {
  projectId: string; bots: { id: string; name: string }[]; initialBotId?: string; onClose: () => void
}) {
  const storageKey = `crm:dialog-export:${projectId}`
  const [jobId, setJobId] = useState<string | null>(() => localStorage.getItem(storageKey))
  const [job, setJob] = useState<ExportStatus | null>(null)
  const [botId, setBotId] = useState(initialBotId ?? '')
  const [format, setFormat] = useState('txt')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [contacts, setContacts] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const active = Boolean(jobId && (!job || ['queued', 'running', 'cancelling'].includes(job.status)))
  useEffect(() => {
    if (!jobId) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const { data } = await api.get<ExportStatus>(`/chats/exports/${jobId}`, { params: { project_id: projectId }, signal: controller.signal })
        if (controller.signal.aborted) return
        setJob(data)
        setBotId(data.request.bot_id ?? ''); setFormat(data.request.format)
        setDateFrom(data.request.date_from ?? ''); setDateTo(data.request.date_to ?? ''); setContacts(data.request.include_contacts)
        setError('')
        if (['queued', 'running', 'cancelling'].includes(data.status)) timer = setTimeout(poll, 2000)
      } catch (err: any) {
        if (controller.signal.aborted) return
        setError(err.response?.data?.detail ?? 'Не удалось получить состояние экспорта')
        if (err.response?.status === 404 || err.response?.status === 410) {
          localStorage.removeItem(storageKey)
          setJobId(null)
        } else timer = setTimeout(poll, 5000)
      }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [jobId, projectId, storageKey])
  const create = async () => {
    setBusy(true); setError('')
    try {
      const { data } = await api.post<ExportStatus>('/chats/exports', { bot_id: botId || null, format, date_from: dateFrom || null, date_to: dateTo || null, include_contacts: contacts }, { params: { project_id: projectId } })
      localStorage.setItem(storageKey, data.id); setJob(data); setJobId(data.id)
    } catch (err: any) { setError(typeof err.response?.data?.detail === 'string' ? err.response.data.detail : 'Не удалось создать экспорт') }
    finally { setBusy(false) }
  }
  const download = async () => {
    setBusy(true); setError('')
    try {
      const { data } = await api.post(`/chats/exports/${jobId}/download`, null, { params: { project_id: projectId } })
      const anchor = document.createElement('a')
      anchor.href = `${(api.defaults.baseURL ?? '/api/v1').replace(/\/$/, '')}${data.url}`
      anchor.rel = 'noopener noreferrer'; document.body.appendChild(anchor); anchor.click(); anchor.remove()
    } catch (err: any) { setError(err.response?.data?.detail ?? 'Не удалось скачать экспорт') }
    finally { setBusy(false) }
  }
  const cancel = async () => {
    setBusy(true)
    try { const { data } = await api.delete(`/chats/exports/${jobId}`, { params: { project_id: projectId } }); setJob(data) }
    catch (err: any) { setError(err.response?.data?.detail ?? 'Не удалось отменить экспорт') }
    finally { setBusy(false) }
  }
  return <Modal title="Экспорт диалогов" onClose={onClose} maxWidthClassName="max-w-lg">
    <div className="space-y-4">
      <label className="block text-sm text-gray-300">Бот / аккаунт<select className={`${inputClass} mt-1`} value={botId} onChange={e => setBotId(e.target.value)} disabled={active || busy}><option value="">Весь проект</option>{bots.map(bot => <option key={bot.id} value={bot.id}>{bot.name}</option>)}</select></label>
      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm text-gray-300">Сообщения с (UTC)<input type="date" className={`${inputClass} mt-1`} value={dateFrom} onChange={e => setDateFrom(e.target.value)} disabled={active || busy} /></label>
        <label className="text-sm text-gray-300">По (UTC)<input type="date" className={`${inputClass} mt-1`} value={dateTo} min={dateFrom} onChange={e => setDateTo(e.target.value)} disabled={active || busy} /></label>
      </div>
      <label className="block text-sm text-gray-300">Формат<select aria-label="Формат" className={`${inputClass} mt-1`} value={format} onChange={e => setFormat(e.target.value)} disabled={active || busy}><option value="txt">TXT</option><option value="jsonl">JSONL</option></select></label>
      <label className="flex items-center gap-2 text-sm text-gray-300"><input type="checkbox" checked={contacts} onChange={e => setContacts(e.target.checked)} disabled={active || busy} />Добавить контакты и комментарий из карточки</label>
      <p className="text-xs text-amber-200/80">Переписка может содержать персональные данные. Проверьте архив перед передачей внешнему ИИ. Фото и видео в выгрузку не включаются.</p>
      {job && <div className="border-t border-white/10 pt-3 text-sm"><p className="flex items-center gap-2">{active && <LoaderCircle size={16} className="animate-spin" />}{labels[job.status]}</p><p className="mt-1 text-gray-400">Диалогов: {job.chats ?? 0} · Сообщений: {job.messages ?? 0}{job.size_bytes ? ` · ${(job.size_bytes / 1048576).toFixed(1)} МБ` : ''}</p>{job.status === 'ready' && <p className="mt-1 text-xs text-gray-500">Архив хранится 24 часа.</p>}</div>}
      {(error || job?.error) && <p role="alert" className="text-sm text-red-300">{error || job?.error}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {active ? <button className={secondaryClass} onClick={cancel} disabled={busy}><X size={16} />Отменить</button> : <button className={secondaryClass} onClick={create} disabled={busy || Boolean(dateFrom && dateTo && dateFrom > dateTo)}>{busy ? 'Подождите…' : job ? 'Новая выгрузка' : 'Создать выгрузку'}</button>}
        {job?.status === 'ready' && <button className={primaryClass} onClick={download} disabled={busy}><Download size={16} />Скачать ZIP</button>}
      </div>
    </div>
  </Modal>
}

import { Download, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import axios from 'axios'
import api from '../../api/client'

type BackupStatus = {
  status: 'queued' | 'in_progress' | 'ready' | 'failed'
  file_name: string | null
}

function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const cancel = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, 2000)
    signal.addEventListener('abort', cancel, { once: true })
    if (signal.aborted) cancel()
  })
}

export default function BackupDownloadButton() {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const controller = useRef<AbortController | null>(null)
  const pendingJob = useRef<string | null>(null)
  useEffect(() => () => controller.current?.abort(), [])

  async function download() {
    if (controller.current) return
    const request = new AbortController()
    controller.current = request
    setBusy(true)
    setMessage('Подготовка бэкапа…')
    try {
      if (!pendingJob.current) {
        const { data } = await api.post<{ job_id: string }>('/settings/global/backup/download', null, { signal: request.signal })
        pendingJob.current = data.job_id
      }
      const endpoint = `/settings/global/backup/download/${pendingJob.current}`
      for (;;) {
        const { data } = await api.get<BackupStatus>(endpoint, { signal: request.signal })
        if (data.status === 'failed') {
          pendingJob.current = null
          throw new Error('Не удалось создать бэкап. Проверьте серверные логи.')
        }
        if (data.status === 'ready' && data.file_name) {
          setMessage('Скачивание архива…')
          const response = await api.get<Blob>(`${endpoint}/file`, {
            signal: request.signal, responseType: 'blob', timeout: 0,
          })
          const url = URL.createObjectURL(response.data)
          const anchor = document.createElement('a')
          anchor.href = url
          anchor.download = data.file_name
          document.body.appendChild(anchor)
          anchor.click()
          anchor.remove()
          window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
          pendingJob.current = null
          setMessage('Архив передан браузеру для сохранения.')
          break
        }
        setMessage(data.status === 'queued' ? 'Бэкап в очереди…' : 'Создание бэкапа…')
        await pause(request.signal)
      }
    } catch (error) {
      if (!request.signal.aborted) {
        if (axios.isAxiosError(error) && [404, 410].includes(error.response?.status ?? 0)) pendingJob.current = null
        const detail = axios.isAxiosError(error) ? error.response?.data?.detail : null
        setMessage(typeof detail === 'string' ? detail : error instanceof Error && !axios.isAxiosError(error)
          ? error.message : 'Не удалось скачать бэкап. Повторите попытку.')
      }
    } finally {
      controller.current = null
      if (!request.signal.aborted) setBusy(false)
    }
  }

  return <div className="flex min-w-0 flex-col items-start gap-2">
    <button type="button" onClick={() => void download()} disabled={busy}
      className="inline-flex items-center gap-2 rounded-lg border border-cyan-400/35 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-500/10 disabled:opacity-50"
      title="Скачать резервную копию всей базы CRM на компьютер">
      {busy ? <LoaderCircle size={16} className="shrink-0 animate-spin" /> : <Download size={16} className="shrink-0" />}
      Скачать бэкап
    </button>
    {message && <span role="status" className="max-w-sm text-sm text-zinc-400">{message}</span>}
  </div>
}

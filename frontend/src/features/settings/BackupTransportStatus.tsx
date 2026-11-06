import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import api from '../../api/client'

type Status = { stage: string; host?: string; mode?: string; effective_limit_mb?: number; observed_at?: string;
  size_bytes?: number; local_created?: boolean; telegram_sent?: boolean; warning?: string }
const stages: Record<string, string> = { idle: 'Готов к работе', creating: 'Создание архива', uploading: 'Отправка архива', completed: 'Отправлен', failed: 'Ошибка', unknown: 'Нет данных worker' }
export default function BackupTransportStatus() {
  const [data, setData] = useState<Status | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const load = useCallback(async () => {
    setBusy(true); setError('')
    try { setData((await api.get<Status>('/settings/global/backup/transport')).data) }
    catch { setError('Диагностика backup-worker недоступна') } finally { setBusy(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  return <section aria-label="Доставка бэкапа" className="min-w-0 space-y-2 border-y border-zinc-800 py-3 text-xs text-zinc-400">
    <div className="flex items-center justify-between gap-3"><span className="text-zinc-200">Backup-worker · {data ? stages[data.stage] ?? data.stage : 'Загрузка'}</span><button type="button" title="Обновить доставку бэкапа" disabled={busy} onClick={() => void load()} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-zinc-700 disabled:opacity-40"><RefreshCw size={14} /></button></div>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {data?.host && <p className="break-all">{data.host} · лимит {data.effective_limit_mb} МБ</p>}
    {data?.size_bytes != null && <p>Архив: {(data.size_bytes / 1048576).toFixed(1)} МБ · локально: {data.local_created ? 'создан' : 'нет'} · Telegram: {data.telegram_sent ? 'отправлен' : 'не подтверждён'}</p>}
    {data?.observed_at && <time>{new Date(data.observed_at).toLocaleString('ru-RU')}</time>}
    {data?.warning && <p className="text-amber-200">{data.warning}</p>}
  </section>
}

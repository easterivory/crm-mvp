import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, RefreshCw, RotateCcw } from 'lucide-react'
import api from '../../api/client'

type Dispatch = { id: string; chat_id: string; kind: string; status: string; failure_count: number;
  fingerprint: string; can_retry: boolean; diagnostics: { error_type?: string; sqlstate?: string; field?: string } }

export default function RuntimeDeliveryReview({ projectId }: { projectId: string | null }) {
  const [rows, setRows] = useState<Dispatch[]>([])
  const [state, setState] = useState('review')
  const [offset, setOffset] = useState(0)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const requestSequence = useRef(0)
  const load = useCallback(async () => {
    if (!projectId) return
    const sequence = ++requestSequence.current
    setBusy(true); setError('')
    try {
      const { data } = await api.get<Dispatch[]>('/settings/runtime-dispatches', { params: { project_id: projectId, state, limit: 50, offset } })
      if (sequence === requestSequence.current) setRows(data)
    } catch { if (sequence === requestSequence.current) setError('Не удалось загрузить задания') }
    finally { if (sequence === requestSequence.current) setBusy(false) }
  }, [projectId, state, offset])
  useEffect(() => { setOffset(0); setRows([]) }, [projectId, state])
  useEffect(() => { void load(); return () => { requestSequence.current++ } }, [load])
  async function retry(row: Dispatch) {
    if (!reason.trim() || !window.confirm('Повторить одно задание без зафиксированных отправок?')) return
    setBusy(true); setError('')
    try {
      await api.post(`/settings/runtime-dispatches/${row.id}/retry`, { fingerprint: row.fingerprint, reason: reason.trim() }, { params: { project_id: projectId } })
      await load()
    } catch { setError('Повтор не разрешён или состояние чата изменилось. Обновите список.') }
    finally { setBusy(false) }
  }
  const tool = 'inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-zinc-700 text-zinc-300 disabled:opacity-40'
  return <section aria-label="Задания воронок" className="min-w-0 space-y-3 border-t border-zinc-800 pt-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="text-sm font-semibold text-zinc-100">Задания воронок</h3>
      <div className="flex gap-2"><select aria-label="Состояние заданий" value={state} onChange={e => setState(e.target.value)} className="min-w-0 rounded-md border border-zinc-700 bg-zinc-950 p-2 text-sm text-zinc-200"><option value="review">Требуют разбора</option><option value="pending">Ожидают обработки</option><option value="running">Выполняются</option></select><button className={tool} title="Обновить задания" disabled={busy} onClick={() => void load()}><RefreshCw size={16} /></button></div>
    </div>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    <label className="grid gap-1 text-xs text-zinc-400">Основание повтора<input value={reason} maxLength={500} onChange={e => setReason(e.target.value)} className="min-w-0 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100" /></label>
    <div className="max-w-full overflow-x-auto"><table className="w-full text-left text-xs text-zinc-300"><thead><tr><th className="p-2">Чат</th><th className="p-2">Задание</th><th className="p-2">Ошибка / попытки</th><th className="p-2">Повтор</th></tr></thead><tbody>{rows.map(row => <tr key={row.id} className="border-t border-zinc-800"><td className="p-2"><Link to={`/chats?chat_id=${row.chat_id}`} className="text-cyan-300">{row.chat_id.slice(0, 8)}</Link></td><td className="p-2">{row.kind}<br /><span className="text-zinc-500">{row.id.slice(0, 8)}</span></td><td className="p-2">{row.diagnostics.error_type ?? 'Нет подробностей'} {row.diagnostics.sqlstate ?? ''}<br />{row.diagnostics.field ?? ''} · {row.failure_count}</td><td className="p-2">{row.can_retry ? <button title="Повторить безопасное задание" className={tool} disabled={busy || !reason.trim()} onClick={() => void retry(row)}><RotateCcw size={15} /></button> : <span className="text-amber-200">Нужна сверка</span>}</td></tr>)}</tbody></table></div>
    {!busy && !rows.length && <p className="text-xs text-zinc-500">Заданий нет</p>}
    <div className="flex justify-end gap-2"><button title="Предыдущие задания" className={tool} disabled={busy || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 50))}><ChevronLeft size={16} /></button><button title="Следующие задания" className={tool} disabled={busy || rows.length < 50} onClick={() => setOffset(n => n + 50)}><ChevronRight size={16} /></button></div>
  </section>
}

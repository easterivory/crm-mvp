import { Clock, LoaderCircle } from 'lucide-react'
import { useState } from 'react'

import { useNotificationStore } from '../../../shared/lib'
import { setFunnelHoldMode } from '../api'

type HoldModeToggleProps = {
  funnelId: string
  versionId: string
  projectId: string
  isHoldActive: boolean
  holdMode: 'manual' | 'project_schedule'
  onToggle: () => void
}

export default function HoldModeToggle({
  funnelId,
  versionId,
  projectId,
  isHoldActive,
  holdMode,
  onToggle,
}: HoldModeToggleProps) {
  const notify = useNotificationStore((state) => state.notify)
  const [isSaving, setIsSaving] = useState(false)

  const save = async (mode: 'manual' | 'project_schedule', enabled: boolean) => {
    if (isSaving) return
    setIsSaving(true)
    try {
      await setFunnelHoldMode(funnelId, versionId, projectId, enabled, mode)
      notify({
        tone: 'success',
        message: mode === 'project_schedule' ? 'HOLD: расписание проекта выбрано.' : enabled
          ? 'Hold включён: звонки будут планироваться на завтра.'
          : 'Hold выключен: звонки будут планироваться на сегодня.',
      })
      onToggle()
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      notify({ tone: 'error', message: typeof detail === 'string' ? detail : 'Не удалось изменить Hold.' })
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex-1">
        <h3 className="text-sm font-medium text-white">Режим Hold</h3>
        <p className="text-xs text-gray-400">
          {holdMode === 'project_schedule' ? 'Расписание проекта' : isHoldActive
            ? 'Hold-ветка активна: после номера звонок планируется на завтра.'
            : 'Обычная ветка активна: после номера звонок планируется на сегодня.'}
        </p>
      </div>
      <select aria-label="Режим HOLD" value={holdMode} disabled={isSaving}
        onChange={event => void save(event.target.value as 'manual' | 'project_schedule', isHoldActive)}
        className="max-w-full rounded-md border border-white/10 bg-[#111827] px-2 py-2 text-sm text-gray-100">
        <option value="manual">Ручной</option>
        <option value="project_schedule">По расписанию проекта</option>
      </select>
      {holdMode === 'manual' && (
      <button
        type="button"
        disabled={isSaving}
        onClick={() => void save('manual', !isHoldActive)}
        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm font-medium text-gray-100 transition hover:border-accent-300/40 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSaving ? <LoaderCircle size={14} className="animate-spin" /> : <Clock size={14} />}
        {isHoldActive ? 'Hold включён' : 'Hold выключен'}
      </button>
      )}
    </div>
  )
}

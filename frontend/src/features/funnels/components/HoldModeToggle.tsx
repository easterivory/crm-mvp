import { Clock, LoaderCircle } from 'lucide-react'
import { useState } from 'react'

import { useNotificationStore } from '../../../shared/lib'
import { setFunnelHoldMode } from '../api'

type HoldModeToggleProps = {
  funnelId: string
  versionId: string
  projectId: string
  isHoldActive: boolean
  onToggle: () => void
}

export default function HoldModeToggle({
  funnelId,
  versionId,
  projectId,
  isHoldActive,
  onToggle,
}: HoldModeToggleProps) {
  const notify = useNotificationStore((state) => state.notify)
  const [isSaving, setIsSaving] = useState(false)

  const toggle = async () => {
    if (isSaving) return
    setIsSaving(true)
    try {
      await setFunnelHoldMode(funnelId, versionId, projectId, !isHoldActive)
      notify({
        tone: 'success',
        message: !isHoldActive
          ? 'Hold включён: звонки будут планироваться на завтра.'
          : 'Hold выключен: звонки будут планироваться на сегодня.',
      })
      onToggle()
    } catch {
      notify({ tone: 'error', message: 'Не удалось изменить Hold.' })
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <h3 className="text-sm font-medium text-white">Режим Hold</h3>
        <p className="text-xs text-gray-400">
          {isHoldActive
            ? 'Hold-ветка активна: после номера звонок планируется на завтра.'
            : 'Обычная ветка активна: после номера звонок планируется на сегодня.'}
        </p>
      </div>
      <button
        type="button"
        disabled={isSaving}
        onClick={toggle}
        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm font-medium text-gray-100 transition hover:border-accent-300/40 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isSaving ? <LoaderCircle size={14} className="animate-spin" /> : <Clock size={14} />}
        {isHoldActive ? 'Hold включён' : 'Hold выключен'}
      </button>
    </div>
  )
}

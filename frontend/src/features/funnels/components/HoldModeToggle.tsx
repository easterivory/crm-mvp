import { Clock } from 'lucide-react'

type HoldModeToggleProps = {
  funnelId: string
  versionId: string
  isHoldActive: boolean
  onToggle: () => void
}

export default function HoldModeToggle({
  isHoldActive,
}: HoldModeToggleProps) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <h3 className="text-sm font-medium text-white">Режим Hold</h3>
        <p className="text-xs text-gray-400">
          {isHoldActive
            ? 'Воронка приостановлена - новые лиды не обрабатываются'
            : 'Настройка Hold пока не подключена к runtime'}
        </p>
      </div>
      <button
        type="button"
        disabled
        className="inline-flex h-9 cursor-not-allowed items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm font-medium text-gray-400 opacity-80"
      >
        <Clock size={14} />
        Скоро
      </button>
    </div>
  )
}

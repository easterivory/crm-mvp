import { useState } from 'react'
import { Pause, Play } from 'lucide-react'

type HoldModeToggleProps = {
  funnelId: string
  versionId: string
  isHoldActive: boolean
  onToggle: () => void
}

export default function HoldModeToggle({
  
  
  isHoldActive,
  onToggle,
}: HoldModeToggleProps) {
  const [isLoading, setIsLoading] = useState(false)

  const handleToggle = async () => {
    setIsLoading(true)
    try {
      // TODO: Implement API call to toggle hold mode
      // await toggleHoldMode(funnelId, versionId, !isHoldActive)
      onToggle()
    } catch (error) {
      console.error('Failed to toggle hold mode:', error)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex items-center gap-3">
      <div className="flex-1">
        <h3 className="text-sm font-medium text-white">Режим Hold</h3>
        <p className="text-xs text-gray-400">
          {isHoldActive
            ? 'Воронка приостановлена - новые лиды не обрабатываются'
            : 'Воронка активна и обрабатывает новые лиды'}
        </p>
      </div>
      <button
        type="button"
        onClick={handleToggle}
        disabled={isLoading}
        className={`inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${
          isHoldActive
            ? 'border-emerald-300/20 bg-emerald-300/10 text-emerald-100 hover:border-emerald-300/40'
            : 'border-amber-300/20 bg-amber-300/10 text-amber-100 hover:border-amber-300/40'
        }`}
      >
        {isHoldActive ? (
          <>
            <Play size={14} />
            Возобновить
          </>
        ) : (
          <>
            <Pause size={14} />
            Приостановить
          </>
        )}
      </button>
    </div>
  )
}

import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from 'lucide-react'
import { useEffect } from 'react'

import { AppNotification, useNotificationStore } from '../lib/notifications'

const toneClasses: Record<AppNotification['tone'], string> = {
  success: 'border-emerald-300/25 bg-emerald-950/95 text-emerald-50',
  error: 'border-red-300/25 bg-red-950/95 text-red-50',
  info: 'border-accent-300/25 bg-[#0f172a]/95 text-accent-50',
  warning: 'border-amber-300/25 bg-amber-950/95 text-amber-50',
}

const icons = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
  warning: TriangleAlert,
}

function NotificationItem({ item }: { item: AppNotification }) {
  const dismiss = useNotificationStore((state) => state.dismiss)
  const Icon = icons[item.tone]

  useEffect(() => {
    if (item.durationMs <= 0) {
      return undefined
    }
    const timer = window.setTimeout(() => dismiss(item.id), item.durationMs)
    return () => window.clearTimeout(timer)
  }, [dismiss, item.durationMs, item.id])

  return (
    <div
      className={`pointer-events-auto flex w-full gap-3 rounded-xl border px-4 py-3 shadow-card backdrop-blur ${toneClasses[item.tone]}`}
    >
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        {item.title ? <p className="text-sm font-semibold">{item.title}</p> : null}
        <p className="break-words text-sm leading-5 opacity-90">{item.message}</p>
      </div>
      <button
        type="button"
        onClick={() => dismiss(item.id)}
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] opacity-80 transition hover:opacity-100"
        aria-label="Закрыть уведомление"
      >
        <X size={14} />
      </button>
    </div>
  )
}

export default function NotificationViewport() {
  const notifications = useNotificationStore((state) => state.notifications)

  if (notifications.length === 0) {
    return null
  }

  return (
    <div className="pointer-events-none fixed inset-x-3 bottom-3 z-[120] flex flex-col gap-2 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:w-[380px]">
      {notifications.map((item) => (
        <NotificationItem key={item.id} item={item} />
      ))}
    </div>
  )
}

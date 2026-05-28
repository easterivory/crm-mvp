import { LoaderCircle, UsersRound } from 'lucide-react'

import type { AudiencePreview } from '../types'

type AudiencePreviewCardProps = {
  preview: AudiencePreview | null
  isLoading: boolean
  isStale: boolean
  error: string
  onRefresh: () => void
}

export default function AudiencePreviewCard({
  preview,
  isLoading,
  isStale,
  error,
  onRefresh,
}: AudiencePreviewCardProps) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <UsersRound size={18} className="text-accent-200" />
          <div>
            <p className="text-sm font-semibold text-white">Аудитория</p>
            <p className="text-xs text-gray-500">
              {isLoading
                ? 'Пересчитываем...'
                : preview
                  ? `Под условия попадает: ${preview.count} лидов/чатов`
                  : 'Нужно рассчитать'}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:opacity-50"
        >
          {isLoading ? <LoaderCircle size={15} className="animate-spin" /> : null}
          Рассчитать
        </button>
      </div>

      {isStale ? (
        <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100">
          Фильтры изменились, перед отправкой нужен свежий пересчёт.
        </p>
      ) : null}
      {error ? (
        <p className="mt-3 rounded-lg border border-red-300/20 bg-red-500/10 px-3 py-2 text-xs text-red-100">
          {error}
        </p>
      ) : null}
      {preview && preview.in_funnel_count ? (
        <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs text-amber-100">
          {preview.in_funnel_count} получателей уже находится в воронке.
        </p>
      ) : null}

      {preview?.sample.length ? (
        <div className="mt-3 space-y-2">
          {preview.sample.slice(0, 5).map((item) => (
            <div
              key={item.chat_id}
              className="rounded-lg border border-white/8 bg-background/45 px-3 py-2 text-xs text-gray-400"
            >
              <span className="text-gray-200">{item.lead_name || item.username || item.chat_id}</span>
              {item.status ? <span className="ml-2 text-gray-500">· {item.status}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

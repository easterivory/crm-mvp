import { Copy, Megaphone, Pause, Play, RefreshCw, XCircle } from 'lucide-react'

import type { Broadcast, BroadcastReport } from '../types'

type BroadcastListProps = {
  broadcasts: Broadcast[]
  botLabelById: Map<string, string>
  reports: Record<string, BroadcastReport>
  onOpen: (broadcast: Broadcast) => void
  onDuplicate: (broadcast: Broadcast) => void
  onCancel: (broadcast: Broadcast) => void
  onPause: (broadcast: Broadcast) => void
  onResume: (broadcast: Broadcast) => void
  onRefreshReport: (broadcast: Broadcast) => void
}

const statusLabels: Record<string, string> = {
  draft: 'Черновик',
  audience_ready: 'Аудитория готова',
  scheduled: 'Запланирована',
  sending: 'Отправляется',
  paused: 'Пауза',
  sent: 'Отправлена',
  failed: 'Ошибка',
  cancelled: 'Отменена',
}

export default function BroadcastList({
  broadcasts,
  botLabelById,
  reports,
  onOpen,
  onDuplicate,
  onCancel,
  onPause,
  onResume,
  onRefreshReport,
}: BroadcastListProps) {
  if (broadcasts.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-white/10 p-8 text-center text-gray-500">
        Рассылок пока нет.
      </div>
    )
  }

  return (
    <div className="grid gap-3">
      {broadcasts.map((broadcast) => {
        const report = reports[broadcast.id]
        const total = report?.total_recipients || broadcast.audience_count || 0
        const done = (report?.sent ?? 0) + (report?.failed ?? 0) + (report?.skipped ?? 0)
        const progress = total ? Math.min(100, Math.round((done / total) * 100)) : 0
        return (
        <article key={broadcast.id} className="rounded-xl border border-white/8 bg-surface/90 p-4 shadow-card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <button
              type="button"
              onClick={() => onOpen(broadcast)}
              className="min-w-0 text-left"
            >
              <div className="flex items-center gap-2">
                <Megaphone size={17} className="text-accent-200" />
                <h3 className="truncate text-base font-semibold text-white">{broadcast.name}</h3>
              </div>
              <p className="mt-1 text-sm text-gray-500">
                {broadcast.bot_id ? botLabelById.get(broadcast.bot_id) ?? 'Бот' : 'Бот не выбран'} · {broadcast.audience_count} получателей
              </p>
            </button>
            <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs text-gray-300">
              {statusLabels[broadcast.status] ?? broadcast.status}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-gray-500">
            {broadcast.scheduled_at ? <span>План: {new Date(broadcast.scheduled_at).toLocaleString()}</span> : null}
            {broadcast.sent_at ? <span>Отправлено: {new Date(broadcast.sent_at).toLocaleString()}</span> : null}
            <span>Автор: {broadcast.created_by_name || 'не указан'}</span>
            <span>Создано: {new Date(broadcast.created_at).toLocaleString()}</span>
          </div>
          {report ? (
            <div className="mt-4 rounded-xl border border-white/8 bg-white/[0.03] p-3">
              <div className="mb-2 flex items-center justify-between text-xs text-gray-400">
                <span>{progress}% готово</span>
                <span>sent {report.sent} · failed {report.failed} · pending {report.pending}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/8">
                <div className="h-full bg-accent-400" style={{ width: `${progress}%` }} />
              </div>
              {report.error_examples[0] ? (
                <p className="mt-2 truncate text-xs text-red-200">{report.error_examples[0]}</p>
              ) : null}
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onOpen(broadcast)}
              className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
            >
              Открыть
            </button>
            <button
              type="button"
              onClick={() => onDuplicate(broadcast)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
            >
              <Copy size={14} />
              Дублировать
            </button>
            {['scheduled', 'sending'].includes(broadcast.status) ? (
              <button
                type="button"
                onClick={() => onCancel(broadcast)}
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/20 px-3 text-sm text-red-200 transition hover:border-red-300/40"
              >
                <XCircle size={14} />
                Отменить
              </button>
            ) : null}
            {broadcast.status === 'sending' ? (
              <button
                type="button"
                onClick={() => onPause(broadcast)}
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
              >
                <Pause size={14} />
                Пауза
              </button>
            ) : null}
            {broadcast.status === 'paused' ? (
              <button
                type="button"
                onClick={() => onResume(broadcast)}
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
              >
                <Play size={14} />
                Продолжить
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => onRefreshReport(broadcast)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
            >
              <RefreshCw size={14} />
              Обновить отчёт
            </button>
          </div>
        </article>
      )})}
    </div>
  )
}

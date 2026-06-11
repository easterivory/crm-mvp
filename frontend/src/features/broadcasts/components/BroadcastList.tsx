import {
  Check,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  Copy,
  LoaderCircle,
  Megaphone,
  Pause,
  Play,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react'
import type { ReactNode } from 'react'

import type { Broadcast, BroadcastDeliveryAnalytics, BroadcastReport } from '../types'

type BroadcastListProps = {
  broadcasts: Broadcast[]
  botLabelById: Map<string, string>
  reports: Record<string, BroadcastReport>
  detailedAnalytics: Record<string, BroadcastDeliveryAnalytics>
  expandedAnalyticsIds: Set<string>
  loadingAnalyticsIds: Set<string>
  onOpen: (broadcast: Broadcast) => void
  onDuplicate: (broadcast: Broadcast) => void
  onCancel: (broadcast: Broadcast) => void
  onPause: (broadcast: Broadcast) => void
  onResume: (broadcast: Broadcast) => void
  onDelete: (broadcast: Broadcast) => void
  onToggleDetailedAnalytics: (broadcast: Broadcast) => void
  onRefreshReport: (broadcast: Broadcast) => void
}

const statusLabels: Record<string, string> = {
  draft: 'Черновик',
  scheduled: 'Запланирована',
  processing: 'Отправляется',
  paused: 'Пауза',
  completed: 'Завершена',
  cancelled: 'Отменена',
}

function percent(value: number, total: number) {
  if (!total) return 0
  return Math.round((value / total) * 100)
}

function DeliveryIconMetric({
  title,
  value,
  icon,
  tone = 'text-gray-400',
}: {
  title: string
  value: number
  icon: ReactNode
  tone?: string
}) {
  return (
    <span
      title={title}
      className={`inline-flex h-7 min-w-12 items-center justify-center gap-1 rounded-lg border border-white/8 bg-white/[0.03] px-2 ${tone}`}
    >
      {icon}
      <span className="tabular-nums">{value}</span>
    </span>
  )
}

function AnalyticsMetric({
  label,
  value,
  total,
  showPercent = true,
}: {
  label: string
  value: number
  total: number
  showPercent?: boolean
}) {
  const ratio = percent(value, total)
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] px-3 py-2">
      <div className="text-[11px] uppercase tracking-[0.16em] text-gray-600">{label}</div>
      <div className="mt-1 flex items-end gap-2">
        <span className="text-lg font-semibold text-white">{value}</span>
        {showPercent ? <span className="pb-0.5 text-xs text-gray-500">{ratio}%</span> : null}
      </div>
    </div>
  )
}

export default function BroadcastList({
  broadcasts,
  botLabelById,
  reports,
  detailedAnalytics,
  expandedAnalyticsIds,
  loadingAnalyticsIds,
  onOpen,
  onDuplicate,
  onCancel,
  onPause,
  onResume,
  onDelete,
  onToggleDetailedAnalytics,
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
        const analytics = detailedAnalytics[broadcast.id]
        const isAnalyticsExpanded = expandedAnalyticsIds.has(broadcast.id)
        const isAnalyticsLoading = loadingAnalyticsIds.has(broadcast.id)
        const detailedTotal = analytics?.total_recipients ?? total
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
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <DeliveryIconMetric
                    title="Отправлено"
                    value={report.sent}
                    icon={<Check size={14} />}
                    tone="text-gray-300"
                  />
                  {analytics ? (
                    <DeliveryIconMetric
                      title="Прочитано"
                      value={analytics.read}
                      icon={<CheckCheck size={14} />}
                      tone="text-sky-300"
                    />
                  ) : null}
                  {report.failed ? (
                    <span title="Ошибки" className="rounded-lg border border-red-300/15 bg-red-500/10 px-2 py-1 text-red-200">
                      {report.failed}
                    </span>
                  ) : null}
                  {report.pending ? (
                    <span title="В очереди" className="rounded-lg border border-amber-300/15 bg-amber-500/10 px-2 py-1 text-amber-100">
                      {report.pending}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/8">
                <div className="h-full bg-accent-400" style={{ width: `${progress}%` }} />
              </div>
              {report.error_examples[0] ? (
                <p className="mt-2 truncate text-xs text-red-200">{report.error_examples[0]}</p>
              ) : null}
            </div>
          ) : null}
          {isAnalyticsExpanded ? (
            <div className="mt-3 rounded-xl border border-white/8 bg-white/[0.02] p-3">
              {isAnalyticsLoading ? (
                <div className="flex h-20 items-center justify-center text-sm text-gray-500">
                  <LoaderCircle size={16} className="mr-2 animate-spin" />
                  Загружаем аналитику
                </div>
              ) : analytics ? (
                <>
                  <div className="grid gap-2 sm:grid-cols-4">
                    <AnalyticsMetric label="База" value={detailedTotal} total={detailedTotal} showPercent={false} />
                    <AnalyticsMetric label="Доставлено" value={analytics.delivered} total={detailedTotal} />
                    <AnalyticsMetric label="Прочитано" value={analytics.read} total={detailedTotal} />
                    <AnalyticsMetric label="Ответили" value={analytics.replied} total={detailedTotal} />
                  </div>
                  {analytics.recipients.length > 0 ? (
                    <div className="mt-3 overflow-hidden rounded-xl border border-white/8">
                      {analytics.recipients.slice(0, 5).map((recipient) => (
                        <div
                          key={recipient.id}
                          className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 px-3 py-2 text-xs last:border-b-0"
                        >
                          <span className="min-w-0 truncate text-gray-300">
                            {recipient.lead_name || recipient.external_user_id || recipient.external_chat_id}
                          </span>
                          <span className="flex items-center gap-2 text-gray-500">
                            {recipient.status}
                            {recipient.is_read ? <CheckCheck size={14} className="text-sky-300" /> : <Check size={14} className="text-gray-500" />}
                            {recipient.replied ? <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-200">ответ</span> : null}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="py-6 text-center text-sm text-gray-500">Нет данных доставки.</div>
              )}
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
            {['scheduled', 'processing'].includes(broadcast.status) ? (
              <button
                type="button"
                onClick={() => onCancel(broadcast)}
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/20 px-3 text-sm text-red-200 transition hover:border-red-300/40"
              >
                <XCircle size={14} />
                Отменить
              </button>
            ) : null}
            {broadcast.status === 'processing' ? (
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
              onClick={() => onToggleDetailedAnalytics(broadcast)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
            >
              {isAnalyticsLoading ? (
                <LoaderCircle size={14} className="animate-spin" />
              ) : isAnalyticsExpanded ? (
                <ChevronUp size={14} />
              ) : (
                <ChevronDown size={14} />
              )}
              Доставка
            </button>
            <button
              type="button"
              onClick={() => onRefreshReport(broadcast)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
            >
              <RefreshCw size={14} />
              Обновить отчёт
            </button>
            <button
              type="button"
              onClick={() => onDelete(broadcast)}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/20 px-3 text-sm text-red-200 transition hover:border-red-300/40"
            >
              <Trash2 size={14} />
              Удалить
            </button>
          </div>
        </article>
      )})}
    </div>
  )
}

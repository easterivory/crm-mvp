import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Download,
  LoaderCircle,
  Pause,
  Play,
  Save,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  cancelBroadcast,
  createBroadcast,
  downloadBroadcastErrorsCsv,
  fetchBroadcastErrorLog,
  fetchBroadcastReport,
  pauseBroadcast,
  previewAudience,
  resumeBroadcast,
  scheduleBroadcast,
  sendBroadcastNow,
  updateBroadcast,
} from '../api'
import {
  emptyAudienceFilter,
  emptyBroadcastContent,
  type AudienceFilter,
  type AudiencePreview,
  type AudienceRule,
  type Broadcast,
  type BroadcastContent,
  type BroadcastErrorLogRow,
  type BroadcastMediaType,
  type BroadcastOption,
  type BroadcastReport,
  type BroadcastUpload,
  type ProjectSnippet,
} from '../types'
import type { ChatFilterPreset, ChatFiltersState } from '../../chats/types'
import AudienceBuilder from './AudienceBuilder'
import ContentStep from './ContentStep'
import PhonePreview from './PhonePreview'

type BroadcastWizardProps = {
  broadcast: Broadcast | null
  projectId: string
  defaultBotId: string | null
  bots: BroadcastOption[]
  tags: BroadcastOption[]
  statuses: BroadcastOption[]
  trackingLinks: BroadcastOption[]
  users: BroadcastOption[]
  funnels: BroadcastOption[]
  templates: unknown[]
  snippets: ProjectSnippet[]
  chatFilterPresets: ChatFilterPreset[]
  onSaveTemplate: (name: string, content: BroadcastContent) => Promise<void>
  onUploadMedia: (file: File, mediaType: BroadcastMediaType) => Promise<BroadcastUpload>
  onBack: () => void
  onSaved: (broadcast: Broadcast) => void
}

type StepId = 0 | 1 | 2 | 3
type ScheduleState = {
  type: 'now' | 'scheduled'
  scheduledAt: string
  timezoneMode: 'project' | 'lead_local' | 'fixed'
}

const steps = ['Контент', 'Аудитория', 'Автоматизация', 'Безопасность']
const monitorStatuses = new Set(['processing', 'paused', 'completed', 'cancelled'])

function localDateTimeToIso(value: string) {
  return value ? new Date(value).toISOString() : null
}

function isoToLocalInput(value: string | null) {
  if (!value) return ''
  const date = new Date(value)
  const offset = date.getTimezoneOffset()
  const local = new Date(date.getTime() - offset * 60_000)
  return local.toISOString().slice(0, 16)
}

function isMediaType(value: string | undefined): value is BroadcastMediaType {
  return value === 'photo' ||
    value === 'video' ||
    value === 'voice' ||
    value === 'video_note' ||
    value === 'document'
}

function contentTypeLabel(content: BroadcastContent) {
  const message = content.messages[0]
  if (!message) return 'пустой контент'
  if (message.type === 'photo') return 'фото'
  if (message.type === 'video') return 'видео'
  if (message.type === 'voice') return 'голосовое'
  if (message.type === 'video_note') return 'кружок'
  if (message.type === 'document') return 'документ'
  return 'текст'
}

function contentHasPayload(content: BroadcastContent) {
  return content.messages.some((message) => {
    if (isMediaType(message.type)) {
      return Boolean(message.media?.upload_id || message.media?.telegram_file_id)
    }
    return Boolean(message.text?.trim())
  })
}

function broadcastMetadata(content: BroadcastContent, snippetId: string | null) {
  const message = content.messages[0]
  const mediaType: 'text' | BroadcastMediaType = isMediaType(message?.type) ? message.type : 'text'
  return {
    snippet_id: snippetId,
    media_type: mediaType,
    file_id: message?.media?.source === 'telegram_file_id'
      ? message.media.telegram_file_id ?? null
      : null,
  }
}

function rule(id: string, field: string, operator: string, value: unknown): AudienceRule {
  return { id, field, operator, value }
}

function presetToAudienceFilter(preset: ChatFilterPreset): AudienceFilter {
  const filters = preset.filters_json
  const includeRules: AudienceRule[] = []

  if (filters.tagIds.length > 0) {
    if (filters.tagMode === 'all') {
      filters.tagIds.forEach((tagId) =>
        includeRules.push(rule(`preset-tag-${tagId}`, 'tag', 'in', [tagId])),
      )
    } else {
      includeRules.push(rule('preset-tags', 'tag', 'in', filters.tagIds))
    }
  }
  if (filters.leadStatuses.length > 0) {
    includeRules.push(rule('preset-statuses', 'lead_status', 'in', filters.leadStatuses))
  }
  if (filters.trackingLinkId) {
    includeRules.push(rule('preset-tracking', 'tracking_link', 'equals', filters.trackingLinkId))
  }
  if (filters.funnelState) {
    includeRules.push(rule('preset-funnel-state', 'funnel_state', 'in', [filters.funnelState]))
  }
  if (filters.hasUnansweredIncoming) {
    includeRules.push(rule('preset-unanswered', 'has_unanswered_incoming', 'equals', true))
  }
  if (filters.assignedUserId) {
    includeRules.push(rule('preset-manager', 'assigned_user', 'equals', filters.assignedUserId))
  }
  if (filters.unassigned) {
    includeRules.push(rule('preset-unassigned', 'assigned_user', 'empty', ''))
  }
  if (filters.dateFrom && filters.dateTo) {
    includeRules.push(rule('preset-date-between', 'created_at', 'between', [filters.dateFrom, filters.dateTo]))
  } else if (filters.dateFrom) {
    includeRules.push(rule('preset-date-after', 'created_at', 'after', filters.dateFrom))
  } else if (filters.dateTo) {
    includeRules.push(rule('preset-date-before', 'created_at', 'before', filters.dateTo))
  }

  return {
    include: { mode: 'all', rules: includeRules },
    exclude: { mode: 'any', rules: [] },
  }
}

function unsupportedPresetHints(filters: ChatFiltersState) {
  return [
    filters.q ? 'текстовый поиск' : '',
    filters.isRed ? 'красный SLA-флаг' : '',
    filters.quickFilter ? 'быстрый фильтр' : '',
  ].filter(Boolean)
}

export default function BroadcastWizard({
  broadcast,
  projectId,
  defaultBotId,
  bots,
  tags,
  statuses,
  trackingLinks,
  users,
  funnels,
  snippets,
  chatFilterPresets,
  onUploadMedia,
  onBack,
  onSaved,
}: BroadcastWizardProps) {
  const [step, setStep] = useState<StepId>(0)
  const [name, setName] = useState(broadcast?.name ?? 'Новая рассылка')
  const [botId, setBotId] = useState<string | null>(broadcast?.bot_id ?? defaultBotId)
  const [content, setContent] = useState<BroadcastContent>(
    broadcast?.content_json ?? emptyBroadcastContent(),
  )
  const [audienceFilter, setAudienceFilter] = useState<AudienceFilter>(
    broadcast?.audience_filter_json ?? emptyAudienceFilter(),
  )
  const [schedule, setSchedule] = useState<ScheduleState>({
    type: (broadcast?.schedule_type ?? 'now') as 'now' | 'scheduled',
    scheduledAt: isoToLocalInput(broadcast?.scheduled_at ?? null),
    timezoneMode: (broadcast?.timezone_mode ?? 'project') as 'project' | 'lead_local' | 'fixed',
  })
  const initialAction = broadcast?.content_json?.after_send_action as
    | { funnel_id?: string | null }
    | null
    | undefined
  const [triggerFunnelId, setTriggerFunnelId] = useState<string>(
    broadcast?.trigger_funnel_id ?? initialAction?.funnel_id ?? '',
  )
  const [stopOnReply, setStopOnReply] = useState(Boolean(broadcast?.stop_on_reply))
  const [snippetId, setSnippetId] = useState<string | null>(broadcast?.snippet_id ?? null)
  const [currentBroadcast, setCurrentBroadcast] = useState<Broadcast | null>(broadcast)
  const [audience, setAudience] = useState<AudiencePreview | null>(null)
  const [report, setReport] = useState<BroadcastReport | null>(null)
  const [mediaPreviewUrls, setMediaPreviewUrls] = useState<Record<string, string>>({})
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [presetHint, setPresetHint] = useState('')
  const [isAudienceLoading, setIsAudienceLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isActionLoading, setIsActionLoading] = useState(false)
  const [isAudienceStale, setIsAudienceStale] = useState(true)
  const [audienceError, setAudienceError] = useState('')
  const [error, setError] = useState('')
  const mediaPreviewUrlsRef = useRef(mediaPreviewUrls)

  const isMonitorMode = Boolean(currentBroadcast && monitorStatuses.has(currentBroadcast.status))
  const availableFunnels = useMemo(
    () => funnels.filter((funnel) => !botId || funnel.meta?.botId === botId),
    [botId, funnels],
  )
  const canGoNext =
    (step === 0 && contentHasPayload(content)) ||
    (step === 1 && Boolean(audience && audience.count > 0 && !isAudienceStale)) ||
    step === 2 ||
    step === 3

  const refreshReport = useCallback(async () => {
    if (!currentBroadcast) return
    const nextReport = await fetchBroadcastReport(currentBroadcast.id, projectId)
    setReport(nextReport)
    setCurrentBroadcast((current) =>
      current
        ? {
            ...current,
            status: nextReport.status,
            total_recipients: nextReport.total_recipients,
            sent_count: nextReport.sent_count,
            failed_count: nextReport.failed_count,
          }
        : current,
    )
  }, [currentBroadcast, projectId])

  useEffect(() => {
    if (!isMonitorMode || !currentBroadcast) return undefined
    void refreshReport()
    if (currentBroadcast.status !== 'processing' && currentBroadcast.status !== 'paused') {
      return undefined
    }
    const timer = window.setInterval(() => {
      void refreshReport()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [currentBroadcast, isMonitorMode, refreshReport])

  const refreshAudience = useCallback(async () => {
    if (!botId) {
      setAudience(null)
      setAudienceError('Выберите бота для расчёта аудитории.')
      return
    }
    setIsAudienceLoading(true)
    setAudienceError('')
    try {
      const data = await previewAudience({
        project_id: projectId,
        bot_id: botId,
        audience_filter: audienceFilter,
      })
      setAudience(data)
      setIsAudienceStale(false)
    } catch {
      setAudienceError('Не удалось рассчитать аудиторию.')
    } finally {
      setIsAudienceLoading(false)
    }
  }, [audienceFilter, botId, projectId])

  useEffect(() => {
    setIsAudienceStale(true)
  }, [audienceFilter, botId])

  useEffect(() => {
    if (step !== 1 || !botId) return undefined
    const timer = window.setTimeout(() => {
      void refreshAudience()
    }, 400)
    return () => window.clearTimeout(timer)
  }, [botId, refreshAudience, step])

  const saveDraft = async () => {
    setIsSaving(true)
    setError('')
    try {
      const metadata = broadcastMetadata(content, snippetId)
      const payload = {
        project_id: projectId,
        bot_id: botId,
        name,
        content_json: content,
        audience_filter_json: audienceFilter,
        schedule_type: schedule.type,
        scheduled_at: schedule.type === 'scheduled' ? localDateTimeToIso(schedule.scheduledAt) : null,
        timezone_mode: schedule.timezoneMode,
        ...metadata,
        trigger_funnel_id: triggerFunnelId || null,
        stop_on_reply: stopOnReply,
      }
      const saved = currentBroadcast
        ? await updateBroadcast(currentBroadcast.id, projectId, payload)
        : await createBroadcast(payload)
      setCurrentBroadcast(saved)
      onSaved(saved)
      return saved
    } catch {
      setError('Не удалось сохранить рассылку.')
      return null
    } finally {
      setIsSaving(false)
    }
  }

  const launch = async () => {
    if (isAudienceStale || !audience || audience.count === 0) {
      setError('Перед запуском нужен свежий расчёт аудитории.')
      return
    }
    setIsActionLoading(true)
    setError('')
    try {
      const saved = await saveDraft()
      if (!saved) return
      const result = schedule.type === 'scheduled'
        ? await scheduleBroadcast(saved.id, projectId, {
            scheduled_at: localDateTimeToIso(schedule.scheduledAt) ?? '',
            timezone_mode: schedule.timezoneMode,
          })
        : await sendBroadcastNow(saved.id, projectId)
      setCurrentBroadcast(result.broadcast)
      onSaved(result.broadcast)
      setReport({
        status: result.broadcast.status,
        total_recipients: result.broadcast.total_recipients ?? result.audience.count,
        sent_count: result.broadcast.sent_count ?? 0,
        failed_count: result.broadcast.failed_count ?? 0,
        pending: result.audience.count,
        sent: result.broadcast.sent_count ?? 0,
        failed: result.broadcast.failed_count ?? 0,
        skipped: 0,
        cancelled: 0,
        started_at: result.broadcast.started_at ?? null,
        finished_at: result.broadcast.sent_at,
        error_examples: [],
      })
    } catch {
      setError('Не удалось запустить рассылку.')
    } finally {
      setIsActionLoading(false)
    }
  }

  const applyPreset = (presetId: string) => {
    setSelectedPresetId(presetId)
    const preset = chatFilterPresets.find((item) => item.id === presetId)
    if (!preset) return
    setAudienceFilter(presetToAudienceFilter(preset))
    const hints = unsupportedPresetHints(preset.filters_json)
    setPresetHint(
      hints.length
        ? `Не перенесены в сегмент: ${hints.join(', ')}.`
        : '',
    )
  }

  const handleMonitorAction = async (action: 'pause' | 'resume' | 'cancel') => {
    if (!currentBroadcast) return
    setIsActionLoading(true)
    try {
      const updated =
        action === 'pause'
          ? await pauseBroadcast(currentBroadcast.id, projectId)
          : action === 'resume'
            ? await resumeBroadcast(currentBroadcast.id, projectId)
            : await cancelBroadcast(currentBroadcast.id, projectId)
      setCurrentBroadcast(updated)
      onSaved(updated)
      await refreshReport()
    } finally {
      setIsActionLoading(false)
    }
  }

  const registerMediaPreview = (uploadId: string, url: string) => {
    setMediaPreviewUrls((current) => ({ ...current, [uploadId]: url }))
  }

  useEffect(() => {
    mediaPreviewUrlsRef.current = mediaPreviewUrls
  }, [mediaPreviewUrls])

  useEffect(
    () => () => {
      Object.values(mediaPreviewUrlsRef.current).forEach((url) => window.URL.revokeObjectURL(url))
    },
    [],
  )

  if (isMonitorMode && currentBroadcast) {
    return (
      <BroadcastMonitor
        broadcast={currentBroadcast}
        projectId={projectId}
        report={report}
        isActionLoading={isActionLoading}
        onBack={onBack}
        onRefresh={() => void refreshReport()}
        onPause={() => void handleMonitorAction('pause')}
        onResume={() => void handleMonitorAction('resume')}
        onCancel={() => void handleMonitorAction('cancel')}
      />
    )
  }

  const audienceCount = audience?.count ?? 0
  const scheduleLabel = schedule.type === 'now'
    ? 'Отправить сейчас'
    : schedule.scheduledAt
      ? new Date(localDateTimeToIso(schedule.scheduledAt) ?? '').toLocaleString()
      : 'Дата не выбрана'

  return (
    <section className="grid h-full min-h-0 overflow-hidden rounded-xl border border-white/8 bg-[#0d1324]/95 shadow-card lg:grid-cols-2">
      <div className="flex min-h-0 flex-col overflow-hidden border-r border-white/8">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={onBack}
              className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 text-gray-300 transition hover:border-white/20"
            >
              <ArrowLeft size={16} />
            </button>
            <div className="min-w-0">
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-lg border border-transparent bg-transparent text-lg font-semibold text-white outline-none focus:border-white/10 focus:bg-background/40"
              />
              <p className="text-xs text-gray-500">Split-screen wizard · {steps[step]}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void saveDraft()}
            disabled={isSaving}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:opacity-50"
          >
            {isSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />}
            Черновик
          </button>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-5">
          <div className="mb-5 grid grid-cols-4 gap-2">
            {steps.map((label, index) => (
              <button
                key={label}
                type="button"
                onClick={() => setStep(index as StepId)}
                className={`rounded-xl border px-2 py-2 text-xs ${
                  step === index
                    ? 'border-accent-300/45 bg-accent-300/15 text-accent-50'
                    : 'border-white/10 bg-white/[0.03] text-gray-500'
                }`}
              >
                {index + 1}. {label}
              </button>
            ))}
          </div>

          <label className="mb-4 block">
            <span className="mb-1 block text-xs text-gray-500">Бот отправки</span>
            <select
              value={botId ?? ''}
              onChange={(event) => setBotId(event.target.value || null)}
              className="h-10 w-full rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none"
            >
              <option value="">Выберите бота</option>
              {bots.map((bot) => (
                <option key={bot.id} value={bot.id}>{bot.label}</option>
              ))}
            </select>
          </label>

          {step === 0 ? (
            <ContentStep
              content={content}
              botId={botId}
              funnels={funnels}
              snippets={snippets}
              mediaPreviewUrls={mediaPreviewUrls}
              onChange={setContent}
              onMediaPreview={registerMediaPreview}
              onSnippetSelected={setSnippetId}
              onUploadMedia={onUploadMedia}
            />
          ) : null}

          {step === 1 ? (
            <div className="space-y-4">
              <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
                <div className="flex w-full flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-[220px] flex-1">
                    <h2 className="text-sm font-semibold text-white">Сохранённые фильтры чатов</h2>
                    <p className="text-xs text-gray-500">Быстрый выбор сегмента из рабочей области операторов.</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-sm font-semibold ${
                      isAudienceStale
                        ? 'border-amber-300/25 bg-amber-400/10 text-amber-100'
                        : 'border-emerald-300/25 bg-emerald-400/10 text-emerald-100 animate-pulse'
                    }`}>
                      Получателей: {isAudienceLoading ? '...' : audienceCount}
                    </div>
                    {audience?.in_funnel_count ? (
                      <div className="shrink-0 whitespace-nowrap rounded-full border border-emerald-300/25 bg-emerald-400/10 px-3 py-1 text-sm font-semibold text-emerald-100">
                        В воронке: {audience.in_funnel_count}
                      </div>
                    ) : null}
                  </div>
                </div>
                <select
                  value={selectedPresetId}
                  onChange={(event) => applyPreset(event.target.value)}
                  className="mt-3 h-10 w-full rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none"
                >
                  <option value="">Выберите preset</option>
                  {chatFilterPresets.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.is_shared ? 'Общий · ' : ''}{preset.name}
                    </option>
                  ))}
                </select>
                {presetHint ? <p className="mt-2 text-xs text-amber-100">{presetHint}</p> : null}
              </section>

              <AudienceBuilder
                value={audienceFilter}
                tags={tags}
                statuses={statuses}
                trackingLinks={trackingLinks}
                users={users}
                bots={bots}
                funnels={funnels}
                onChange={setAudienceFilter}
              />
              <button
                type="button"
                onClick={() => void refreshAudience()}
                disabled={isAudienceLoading}
                className="inline-flex h-10 items-center gap-2 rounded-xl bg-accent-500 px-4 text-sm font-semibold text-white transition hover:bg-accent-400 disabled:opacity-50"
              >
                {isAudienceLoading ? <LoaderCircle size={16} className="animate-spin" /> : null}
                Пересчитать аудиторию
              </button>
              {audienceError ? <p className="text-sm text-red-200">{audienceError}</p> : null}
            </div>
          ) : null}

          {step === 2 ? (
            <AutomationStep
              enabled={Boolean(triggerFunnelId)}
              triggerFunnelId={triggerFunnelId}
              stopOnReply={stopOnReply}
              funnels={availableFunnels}
              onToggle={(enabled) => setTriggerFunnelId(enabled ? availableFunnels[0]?.id ?? '' : '')}
              onTriggerFunnelChange={setTriggerFunnelId}
              onStopOnReplyChange={setStopOnReply}
            />
          ) : null}

          {step === 3 ? (
            <SafetyStep
              contentType={contentTypeLabel(content)}
              audienceCount={audienceCount}
              schedule={schedule}
              scheduleLabel={scheduleLabel}
              isAudienceStale={isAudienceStale}
              isActionLoading={isActionLoading}
              onScheduleChange={setSchedule}
              onLaunch={() => void launch()}
            />
          ) : null}

          {error ? (
            <p className="mt-4 rounded-xl border border-red-300/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
              {error}
            </p>
          ) : null}
        </main>

        <footer className="flex shrink-0 items-center justify-between gap-2 border-t border-white/8 px-4 py-3">
          <button
            type="button"
            disabled={step === 0}
            onClick={() => setStep((step - 1) as StepId)}
            className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:opacity-40"
          >
            Назад
          </button>
          {step < 3 ? (
            <button
              type="button"
              disabled={!canGoNext}
              onClick={() => setStep((step + 1) as StepId)}
              className="h-9 rounded-xl bg-accent-500 px-4 text-sm font-semibold text-white transition hover:bg-accent-400 disabled:opacity-45"
            >
              Далее
            </button>
          ) : (
            <span className="text-xs text-gray-500">Для запуска удерживайте кнопку 2 секунды.</span>
          )}
        </footer>
      </div>

      <aside className="min-h-0 overflow-y-auto bg-[#080d18] p-5">
        <PhonePreview content={content} mediaPreviewUrls={mediaPreviewUrls} />
      </aside>
    </section>
  )
}

function AutomationStep({
  enabled,
  triggerFunnelId,
  stopOnReply,
  funnels,
  onToggle,
  onTriggerFunnelChange,
  onStopOnReplyChange,
}: {
  enabled: boolean
  triggerFunnelId: string
  stopOnReply: boolean
  funnels: BroadcastOption[]
  onToggle: (enabled: boolean) => void
  onTriggerFunnelChange: (value: string) => void
  onStopOnReplyChange: (value: boolean) => void
}) {
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <label className="flex items-center justify-between gap-4">
          <span>
            <span className="block text-sm font-semibold text-white">Запустить воронку после сообщения</span>
            <span className="text-xs text-gray-500">Воронка стартует после успешной отправки каждому получателю.</span>
          </span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => onToggle(event.target.checked)}
          />
        </label>
        {enabled ? (
          <select
            value={triggerFunnelId}
            onChange={(event) => onTriggerFunnelChange(event.target.value)}
            className="mt-3 h-10 w-full rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none"
          >
            <option value="">Выберите опубликованную воронку</option>
            {funnels.map((funnel) => (
              <option key={funnel.id} value={funnel.id}>{funnel.label}</option>
            ))}
          </select>
        ) : null}
      </section>
      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <label className="flex items-center justify-between gap-4">
          <span>
            <span className="block text-sm font-semibold text-white">Останавливать кампанию при первом ответе клиента</span>
            <span className="text-xs text-gray-500">Флаг сохраняется в рассылке для worker/runtime контроля.</span>
          </span>
          <input
            type="checkbox"
            checked={stopOnReply}
            onChange={(event) => onStopOnReplyChange(event.target.checked)}
          />
        </label>
      </section>
    </div>
  )
}

function SafetyStep({
  contentType,
  audienceCount,
  schedule,
  scheduleLabel,
  isAudienceStale,
  isActionLoading,
  onScheduleChange,
  onLaunch,
}: {
  contentType: string
  audienceCount: number
  schedule: ScheduleState
  scheduleLabel: string
  isAudienceStale: boolean
  isActionLoading: boolean
  onScheduleChange: (value: ScheduleState) => void
  onLaunch: () => void
}) {
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <h2 className="text-sm font-semibold text-white">Время отправки</h2>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => onScheduleChange({ ...schedule, type: 'now' })}
            className={`h-10 rounded-xl border text-sm ${
              schedule.type === 'now'
                ? 'border-accent-300/45 bg-accent-300/15 text-accent-50'
                : 'border-white/10 text-gray-300'
            }`}
          >
            Отправить сейчас
          </button>
          <button
            type="button"
            onClick={() => onScheduleChange({ ...schedule, type: 'scheduled' })}
            className={`h-10 rounded-xl border text-sm ${
              schedule.type === 'scheduled'
                ? 'border-accent-300/45 bg-accent-300/15 text-accent-50'
                : 'border-white/10 text-gray-300'
            }`}
          >
            Запланировать
          </button>
        </div>
        {schedule.type === 'scheduled' ? (
          <input
            type="datetime-local"
            value={schedule.scheduledAt}
            onChange={(event) => onScheduleChange({ ...schedule, scheduledAt: event.target.value })}
            className="mt-3 h-10 w-full rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none"
          />
        ) : null}
      </section>

      <section className="rounded-xl border border-amber-300/25 bg-amber-400/10 p-4">
        <div className="flex gap-3">
          <ShieldAlert className="mt-0.5 shrink-0 text-amber-100" size={22} />
          <div>
            <h2 className="text-base font-semibold text-amber-50">Внимание</h2>
            <p className="mt-1 text-sm text-amber-50/85">
              Вы отправляете {contentType} на {audienceCount} человек. Режим: {scheduleLabel}.
            </p>
            {isAudienceStale ? (
              <p className="mt-2 text-sm text-red-100">Аудитория устарела, пересчитайте её перед запуском.</p>
            ) : null}
          </div>
        </div>
      </section>

      <HoldToLaunchButton
        disabled={isActionLoading || audienceCount === 0 || isAudienceStale || (schedule.type === 'scheduled' && !schedule.scheduledAt)}
        loading={isActionLoading}
        onComplete={onLaunch}
      />
    </div>
  )
}

function HoldToLaunchButton({
  disabled,
  loading,
  onComplete,
}: {
  disabled: boolean
  loading: boolean
  onComplete: () => void
}) {
  const [progress, setProgress] = useState(0)
  const startRef = useRef<number | null>(null)
  const frameRef = useRef<number | null>(null)

  const stop = () => {
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
    startRef.current = null
    setProgress(0)
  }

  const tick = () => {
    if (startRef.current === null) return
    const next = Math.min(1, (Date.now() - startRef.current) / 2000)
    setProgress(next)
    if (next >= 1) {
      stop()
      onComplete()
      return
    }
    frameRef.current = window.requestAnimationFrame(tick)
  }

  const start = () => {
    if (disabled || loading || startRef.current !== null) return
    startRef.current = Date.now()
    frameRef.current = window.requestAnimationFrame(tick)
  }

  return (
    <button
      type="button"
      disabled={disabled}
      onMouseDown={start}
      onMouseUp={stop}
      onMouseLeave={stop}
      onTouchStart={start}
      onTouchEnd={stop}
      className="relative h-14 w-full overflow-hidden rounded-2xl border border-emerald-300/20 bg-emerald-500/15 text-sm font-semibold text-emerald-50 transition disabled:cursor-not-allowed disabled:opacity-45"
    >
      <span
        className="absolute inset-y-0 left-0 bg-emerald-400/40"
        style={{ width: `${Math.round(progress * 100)}%` }}
      />
      <span className="relative inline-flex items-center gap-2">
        {loading ? <LoaderCircle size={17} className="animate-spin" /> : <CheckCircle2 size={17} />}
        Удерживайте 2 секунды для запуска
      </span>
    </button>
  )
}

function BroadcastMonitor({
  broadcast,
  projectId,
  report,
  isActionLoading,
  onBack,
  onRefresh,
  onPause,
  onResume,
  onCancel,
}: {
  broadcast: Broadcast
  projectId: string
  report: BroadcastReport | null
  isActionLoading: boolean
  onBack: () => void
  onRefresh: () => void
  onPause: () => void
  onResume: () => void
  onCancel: () => void
}) {
  const [errorLog, setErrorLog] = useState<BroadcastErrorLogRow[]>([])
  const [isErrorLogLoading, setIsErrorLogLoading] = useState(false)
  const total = report?.total_recipients || broadcast.total_recipients || broadcast.audience_count || 0
  const sent = report?.sent_count ?? broadcast.sent_count ?? 0
  const failed = report?.failed_count ?? broadcast.failed_count ?? 0
  const done = sent + failed
  const progress = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0

  const loadErrorLog = useCallback(async () => {
    setIsErrorLogLoading(true)
    try {
      setErrorLog(await fetchBroadcastErrorLog(broadcast.id, projectId))
    } catch {
      setErrorLog([])
    } finally {
      setIsErrorLogLoading(false)
    }
  }, [broadcast.id, projectId])

  useEffect(() => {
    void loadErrorLog()
  }, [loadErrorLog])

  const handleRefresh = () => {
    onRefresh()
    void loadErrorLog()
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/8 bg-[#0d1324]/95 shadow-card">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/8 px-5 py-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 text-gray-300"
          >
            <ArrowLeft size={16} />
          </button>
          <div>
            <p className="text-xs uppercase tracking-[0.24em] text-accent-200/70">Broadcast report</p>
            <h1 className="mt-1 text-xl font-semibold text-white">{broadcast.name}</h1>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-100"
          >
            Обновить
          </button>
          <button
            type="button"
            onClick={() => void downloadBroadcastErrorsCsv(broadcast.id, projectId)}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100"
          >
            <Download size={15} />
            Скачать лог ошибок CSV
          </button>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-5">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm text-gray-500">Статус: {report?.status ?? broadcast.status}</p>
              <p className="mt-2 text-4xl font-semibold text-white">{progress}%</p>
            </div>
            <div className="text-right text-sm text-gray-400">
              {done} из {total} получателей обработано
            </div>
          </div>
          <div className="mt-5 h-4 overflow-hidden rounded-full bg-white/8">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-sky-400 to-accent-400 transition-all duration-700"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-emerald-300/15 bg-emerald-400/10 p-5">
            <p className="text-sm text-emerald-100/80">Успешно отправлено</p>
            <p className="mt-2 text-3xl font-semibold text-emerald-100">{sent}</p>
          </div>
          <div className="rounded-2xl border border-red-300/15 bg-red-400/10 p-5">
            <p className="text-sm text-red-100/80">Ошибки доставки</p>
            <p className="mt-2 text-3xl font-semibold text-red-100">{failed}</p>
          </div>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="rounded-2xl border border-white/8 bg-white/[0.03] p-5">
            <h2 className="text-sm font-semibold text-white">Содержимое рассылки</h2>
            <div className="mt-4">
              <PhonePreview content={broadcast.content_json} mediaPreviewUrls={{}} />
            </div>
          </section>

          <section className="rounded-2xl border border-red-300/15 bg-red-400/10 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-red-100">Лог ошибок в CRM</h2>
                <p className="mt-1 text-xs text-red-100/65">Полный список доступен без выгрузки CSV.</p>
              </div>
              {isErrorLogLoading ? (
                <LoaderCircle size={16} className="animate-spin text-red-100" />
              ) : (
                <span className="rounded-full border border-red-200/20 bg-red-500/15 px-2 py-1 text-xs text-red-100">
                  {errorLog.length}
                </span>
              )}
            </div>
            {errorLog.length > 0 ? (
              <div className="mt-4 max-h-96 overflow-y-auto rounded-xl border border-red-200/10 bg-black/10">
                {errorLog.map((row) => (
                  <div key={row.id} className="border-b border-red-200/10 px-3 py-2 text-xs last:border-b-0">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-red-50">
                      <span className="min-w-0 truncate">
                        {row.lead_name || row.external_user_id || row.external_chat_id}
                      </span>
                      <span className="text-red-100/70">{row.status} · попыток: {row.attempts}</span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap break-words leading-5 text-red-100/75">
                      {row.error}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm text-red-100/70">Ошибок доставки нет.</p>
            )}
          </section>
        </div>

        {report?.error_examples.length ? (
          <div className="mt-4 rounded-2xl border border-red-300/15 bg-red-400/10 p-5">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-100">
              <AlertTriangle size={16} />
              Последние ошибки
            </div>
            <div className="space-y-1 text-sm text-red-100/80">
              {report.error_examples.map((error, index) => (
                <p key={`${error}-${index}`} className="truncate">{error}</p>
              ))}
            </div>
          </div>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-2">
          {broadcast.status === 'processing' ? (
            <>
              <button
                type="button"
                disabled={isActionLoading}
                onClick={onPause}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-amber-300/25 bg-amber-400/10 px-4 text-sm font-semibold text-amber-100"
              >
                <Pause size={16} />
                Пауза
              </button>
              <button
                type="button"
                disabled={isActionLoading}
                onClick={onCancel}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-red-300/25 bg-red-400/10 px-4 text-sm font-semibold text-red-100"
              >
                <XCircle size={16} />
                Отменить
              </button>
            </>
          ) : null}
          {broadcast.status === 'paused' ? (
            <>
              <button
                type="button"
                disabled={isActionLoading}
                onClick={onResume}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-emerald-300/25 bg-emerald-400/10 px-4 text-sm font-semibold text-emerald-100"
              >
                <Play size={16} />
                Продолжить
              </button>
              <button
                type="button"
                disabled={isActionLoading}
                onClick={onCancel}
                className="inline-flex h-10 items-center gap-2 rounded-xl border border-red-300/25 bg-red-400/10 px-4 text-sm font-semibold text-red-100"
              >
                <XCircle size={16} />
                Отменить
              </button>
            </>
          ) : null}
          {broadcast.status === 'scheduled' ? (
            <span className="inline-flex h-10 items-center gap-2 rounded-xl border border-sky-300/20 bg-sky-400/10 px-4 text-sm text-sky-100">
              <CalendarClock size={16} />
              Запланирована
            </span>
          ) : null}
        </div>
      </main>
    </section>
  )
}

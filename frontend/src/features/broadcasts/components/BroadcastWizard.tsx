import { ArrowLeft, LoaderCircle, Save } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  createBroadcast,
  previewAudience,
  scheduleBroadcast,
  sendBroadcastNow,
  updateBroadcast,
} from '../api'
import {
  emptyAudienceFilter,
  emptyBroadcastContent,
  type AudienceFilter,
  type AudiencePreview,
  type Broadcast,
  type BroadcastContent,
  type BroadcastOption,
  type BroadcastTemplate,
} from '../types'
import AudienceBuilder from './AudienceBuilder'
import AudiencePreviewCard from './AudiencePreviewCard'
import ContentStep from './ContentStep'
import PhonePreview from './PhonePreview'
import ReviewStep from './ReviewStep'
import ScheduleStep from './ScheduleStep'

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
  templates: BroadcastTemplate[]
  onSaveTemplate: (name: string, content: BroadcastContent) => Promise<void>
  onBack: () => void
  onSaved: (broadcast: Broadcast) => void
}

type StepId = 0 | 1 | 2 | 3

const steps = ['Контент', 'Аудитория', 'Расписание', 'Проверка']

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
  templates,
  onSaveTemplate,
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
  const [schedule, setSchedule] = useState({
    type: (broadcast?.schedule_type ?? 'now') as 'now' | 'scheduled',
    scheduledAt: isoToLocalInput(broadcast?.scheduled_at ?? null),
    timezoneMode: (broadcast?.timezone_mode ?? 'project') as 'project' | 'lead_local' | 'fixed',
  })
  const [currentBroadcast, setCurrentBroadcast] = useState<Broadcast | null>(broadcast)
  const [audience, setAudience] = useState<AudiencePreview | null>(null)
  const [isAudienceLoading, setIsAudienceLoading] = useState(false)
  const [audienceError, setAudienceError] = useState('')
  const [isAudienceStale, setIsAudienceStale] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')

  const botLabel = useMemo(
    () => bots.find((bot) => bot.id === botId)?.label ?? '',
    [botId, bots],
  )
  const hasContent = content.messages.some((message) => message.text.trim())
  const requiresLargeAudienceConfirmation = (audience?.count ?? 0) > 1000
  const hasLargeAudienceConfirmation =
    !requiresLargeAudienceConfirmation || confirmation.trim() === 'ПОДТВЕРЖДАЮ'
  const canGoNext =
    (step === 0 && hasContent) ||
    (step === 1 && Boolean(audience && audience.count > 0 && !isAudienceStale)) ||
    (step === 2 && (schedule.type === 'now' || Boolean(schedule.scheduledAt))) ||
    step === 3

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
  }, [audienceFilter, botId, content])

  useEffect(() => {
    if (step !== 1 || !botId) {
      return undefined
    }
    const timer = window.setTimeout(() => {
      void refreshAudience()
    }, 450)
    return () => window.clearTimeout(timer)
  }, [botId, refreshAudience, step])

  const saveDraft = async () => {
    setIsSaving(true)
    setError('')
    try {
      const payload = {
        project_id: projectId,
        bot_id: botId,
        name,
        content_json: content,
        audience_filter_json: audienceFilter,
        schedule_type: schedule.type,
        scheduled_at: schedule.type === 'scheduled' ? localDateTimeToIso(schedule.scheduledAt) : null,
        timezone_mode: schedule.timezoneMode,
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

  const finalAction = async () => {
    if (isAudienceStale || !audience || audience.count === 0) {
      setError('Перед отправкой нужен свежий расчёт аудитории.')
      return
    }
    const saved = await saveDraft()
    if (!saved) return
    try {
      const result =
        schedule.type === 'scheduled'
          ? await scheduleBroadcast(saved.id, projectId, {
              scheduled_at: localDateTimeToIso(schedule.scheduledAt) ?? '',
              timezone_mode: schedule.timezoneMode,
              confirmation,
            })
          : await sendBroadcastNow(saved.id, projectId, confirmation)
      setCurrentBroadcast(result.broadcast)
      onSaved(result.broadcast)
      onBack()
    } catch {
      setError('Не удалось запустить рассылку. Проверьте аудиторию и подтверждение.')
    }
  }

  const scheduleLabel =
    schedule.type === 'now'
      ? 'Отправить сейчас'
      : schedule.scheduledAt
        ? new Date(localDateTimeToIso(schedule.scheduledAt) ?? '').toLocaleString()
        : 'Дата не выбрана'

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/8 bg-[#0d1324]/95 shadow-card">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
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
            <p className="text-xs text-gray-500">{currentBroadcast?.status ?? 'draft'}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void saveDraft()}
            disabled={isSaving}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:opacity-50"
          >
            {isSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />}
            Сохранить черновик
          </button>
          {step > 0 ? (
            <button
              type="button"
              onClick={() => setStep((step - 1) as StepId)}
              className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
            >
              Назад
            </button>
          ) : null}
          {step < 3 ? (
            <button
              type="button"
              disabled={!canGoNext}
              onClick={() => setStep((step + 1) as StepId)}
              className="h-9 rounded-xl bg-accent-500 px-3 text-sm font-semibold text-white transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-45"
            >
              Далее
            </button>
          ) : (
            <button
              type="button"
              disabled={
                !audience ||
                audience.count === 0 ||
                isAudienceStale ||
                !hasLargeAudienceConfirmation
              }
              onClick={() => void finalAction()}
              className="h-9 rounded-xl bg-accent-500 px-3 text-sm font-semibold text-white transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-45"
            >
              {schedule.type === 'scheduled' ? 'Запланировать' : 'Отправить'}
            </button>
          )}
        </div>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_340px]">
        <main className="min-h-0 overflow-y-auto p-5">
          <div className="mb-5 flex flex-wrap gap-2">
            {steps.map((label, index) => (
              <button
                key={label}
                type="button"
                onClick={() => setStep(index as StepId)}
                className={`rounded-full border px-3 py-1 text-xs ${
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
              className="w-full max-w-md rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
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
              templates={templates}
              onChange={setContent}
              onApplyTemplate={setContent}
              onSaveTemplate={async () => {
                const templateName = window.prompt('Название шаблона', name)
                if (templateName) {
                  await onSaveTemplate(templateName, content)
                }
              }}
            />
          ) : null}
          {step === 1 ? (
            <div className="space-y-4">
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
              <AudiencePreviewCard
                preview={audience}
                isLoading={isAudienceLoading}
                isStale={isAudienceStale}
                error={audienceError}
                onRefresh={() => void refreshAudience()}
              />
            </div>
          ) : null}
          {step === 2 ? <ScheduleStep value={schedule} onChange={setSchedule} /> : null}
          {step === 3 ? (
            <ReviewStep
              content={content}
              audience={audience}
              audienceStale={isAudienceStale}
              audienceFilter={audienceFilter}
              botLabel={botLabel}
              scheduleLabel={scheduleLabel}
              confirmation={confirmation}
              onConfirmationChange={setConfirmation}
            />
          ) : null}

          {error ? (
            <p className="mt-4 rounded-xl border border-red-300/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
              {error}
            </p>
          ) : null}
        </main>

        <aside className="min-h-0 overflow-y-auto border-l border-white/8 p-5">
          <PhonePreview content={content} />
          <div className="mt-4">
            <AudiencePreviewCard
              preview={audience}
              isLoading={isAudienceLoading}
              isStale={isAudienceStale}
              error={audienceError}
              onRefresh={() => void refreshAudience()}
            />
          </div>
        </aside>
      </div>
    </section>
  )
}

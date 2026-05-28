import type { AudienceFilter, AudiencePreview, BroadcastContent } from '../types'

type ReviewStepProps = {
  content: BroadcastContent
  audience: AudiencePreview | null
  audienceStale: boolean
  audienceFilter: AudienceFilter
  botLabel: string
  scheduleLabel: string
  confirmation: string
  onConfirmationChange: (value: string) => void
}

function rulesCount(filter: AudienceFilter) {
  return filter.include.rules.length + filter.exclude.rules.length
}

export default function ReviewStep({
  content,
  audience,
  audienceStale,
  audienceFilter,
  botLabel,
  scheduleLabel,
  confirmation,
  onConfirmationChange,
}: ReviewStepProps) {
  const count = audience?.count ?? 0
  const requiresConfirmation = count > 1000
  const firstLine = content.messages[0]?.text?.split('\n')[0] || 'Нет текста'
  const startsFunnel = content.after_send_action?.type === 'start_funnel'

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Summary label="Контент" value={firstLine} />
        <Summary label="Бот" value={botLabel || 'Не выбран'} />
        <Summary label="Аудитория" value={audienceStale ? 'Нужен свежий пересчёт' : `${count} получателей`} />
        <Summary label="Расписание" value={scheduleLabel} />
      </div>
      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4 text-sm text-gray-300">
        <p className="font-medium text-white">Условия аудитории</p>
        <p className="mt-1 text-gray-500">
          Include: {audienceFilter.include.rules.length} · Exclude: {audienceFilter.exclude.rules.length} · Всего правил: {rulesCount(audienceFilter)}
        </p>
      </div>
      {startsFunnel ? (
        <div className="rounded-xl border border-accent-300/20 bg-accent-300/10 p-4 text-sm text-accent-50">
          После рассылки будет запущена выбранная воронка. Активная воронка бота не изменится.
        </div>
      ) : null}
      {requiresConfirmation ? (
        <label className="block rounded-xl border border-amber-300/20 bg-amber-300/10 p-4">
          <span className="mb-2 block text-sm font-medium text-amber-50">
            Большая аудитория. Введите “ПОДТВЕРЖДАЮ”.
          </span>
          <input
            value={confirmation}
            onChange={(event) => onConfirmationChange(event.target.value)}
            className="w-full rounded-lg border border-amber-300/20 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
          />
        </label>
      ) : null}
    </div>
  )
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-2 text-sm font-medium text-white">{value}</p>
    </div>
  )
}

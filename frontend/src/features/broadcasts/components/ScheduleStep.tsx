type ScheduleValue = {
  type: 'now' | 'scheduled'
  scheduledAt: string
  timezoneMode: 'project' | 'lead_local' | 'fixed'
}

type ScheduleStepProps = {
  value: ScheduleValue
  onChange: (value: ScheduleValue) => void
}

export default function ScheduleStep({ value, onChange }: ScheduleStepProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onChange({ ...value, type: 'now' })}
          className={`rounded-xl border p-4 text-left transition ${
            value.type === 'now'
              ? 'border-accent-300/45 bg-accent-300/10 text-accent-50'
              : 'border-white/10 bg-white/[0.03] text-gray-300'
          }`}
        >
          <p className="font-semibold">Отправить сейчас</p>
          <p className="mt-1 text-xs text-gray-500">Получатели будут поставлены в очередь.</p>
        </button>
        <button
          type="button"
          onClick={() => onChange({ ...value, type: 'scheduled' })}
          className={`rounded-xl border p-4 text-left transition ${
            value.type === 'scheduled'
              ? 'border-accent-300/45 bg-accent-300/10 text-accent-50'
              : 'border-white/10 bg-white/[0.03] text-gray-300'
          }`}
        >
          <p className="font-semibold">Запланировать</p>
          <p className="mt-1 text-xs text-gray-500">Дата и время в будущем.</p>
        </button>
      </div>

      {value.type === 'scheduled' ? (
        <div className="grid gap-3 rounded-xl border border-white/8 bg-white/[0.03] p-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Дата и время</span>
            <input
              type="datetime-local"
              value={value.scheduledAt}
              onChange={(event) => onChange({ ...value, scheduledAt: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Часовой пояс</span>
            <select
              value={value.timezoneMode}
              onChange={(event) =>
                onChange({ ...value, timezoneMode: event.target.value as ScheduleValue['timezoneMode'] })
              }
              className="w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            >
              <option value="project">По времени проекта</option>
              <option value="lead_local" disabled>По часовому поясу клиента · скоро</option>
              <option value="fixed">Фиксированный timezone</option>
            </select>
            <p className="mt-1 text-xs text-gray-500">Часовой пояс клиента пока не собирается.</p>
          </label>
        </div>
      ) : null}
    </div>
  )
}

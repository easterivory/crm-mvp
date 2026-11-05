import { useEffect, useState } from 'react'
import { LoaderCircle, Save } from 'lucide-react'
import api from '../../api/client'

type Schedule = {
  enabled: boolean
  timezone: string
  cutoff_time: string
  working_days: number[]
  before_cutoff: 'today' | 'next_working_day'
  closed_dates: string[]
}
const defaults: Schedule = {
  enabled: false, timezone: 'Europe/Moscow', cutoff_time: '18:00',
  working_days: [0, 1, 2, 3, 4, 5], before_cutoff: 'today', closed_dates: [],
}
const days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const inputClass = 'w-full min-w-0 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100'

export default function HoldScheduleSettings({ projectId }: { projectId: string }) {
  const [schedule, setSchedule] = useState<Schedule>(defaults)
  const [closedDates, setClosedDates] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setLoaded(false); setError(''); setSaved(false)
    void api.get<{ hold_schedule: Schedule }>(`/projects/${projectId}`, { signal: controller.signal })
      .then(({ data }) => {
        if (controller.signal.aborted) return
        const value = { ...defaults, ...data.hold_schedule }
        setSchedule(value); setClosedDates(value.closed_dates.join('\n')); setLoaded(true)
      })
      .catch(() => { if (!controller.signal.aborted) setError('Не удалось загрузить расписание HOLD') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [projectId, retry])
  const update = (patch: Partial<Schedule>) => {
    setSchedule(current => ({ ...current, ...patch })); setSaved(false)
  }
  const save = async () => {
    if (!loaded || saving) return
    setError(''); setSaved(false)
    const dates = closedDates.split(/[\s,;]+/).filter(Boolean)
    if (!schedule.working_days.length || dates.some(value => !/^\d{4}-\d{2}-\d{2}$/.test(value))) {
      setError('Выберите дни выдачи. Даты исключений: ГГГГ-ММ-ДД.'); return
    }
    setSaving(true)
    try {
      const { data } = await api.patch<{ hold_schedule: Schedule }>(`/projects/${projectId}`, {
        hold_schedule: { ...schedule, closed_dates: dates },
      })
      setSchedule(data.hold_schedule); setClosedDates(data.hold_schedule.closed_dates.join('\n')); setSaved(true)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось сохранить расписание. Проверьте часовой пояс, время и даты.')
    } finally { setSaving(false) }
  }
  return <section className="space-y-4 border-y border-zinc-800 py-4">
    <h3 className="text-base font-semibold text-zinc-100">HOLD · расписание записи</h3>
    {loading ? <p role="status">Загрузка…</p> : <>
      <fieldset disabled={!loaded || saving} className="space-y-4">
        <label className="flex items-center gap-3 text-sm text-zinc-100">
          <input type="checkbox" checked={schedule.enabled} onChange={e => update({ enabled: e.target.checked })} />
          Расписание включено
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="min-w-0 space-y-1 text-sm text-zinc-300">Часовой пояс
            <input className={inputClass} list="hold-timezones" value={schedule.timezone}
              onChange={e => update({ timezone: e.target.value })} />
            <datalist id="hold-timezones">
              {['Europe/Moscow', 'Asia/Tashkent', 'Asia/Almaty', 'UTC'].map(zone => <option key={zone} value={zone} />)}
            </datalist>
          </label>
          <label className="min-w-0 space-y-1 text-sm text-zinc-300">Время отсечки
            <input type="time" className={inputClass} value={schedule.cutoff_time}
              onChange={e => update({ cutoff_time: e.target.value })} />
          </label>
        </div>
        <label className="block space-y-1 text-sm text-zinc-300">Запись до отсечки
          <select className={inputClass} value={schedule.before_cutoff}
            onChange={e => update({ before_cutoff: e.target.value as Schedule['before_cutoff'] })}>
            <option value="today">На сегодня, если день рабочий</option>
            <option value="next_working_day">На следующий рабочий день</option>
          </select>
        </label>
        <fieldset><legend className="mb-2 text-sm text-zinc-300">Дни выдачи</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-3">
            {days.map((label, day) => <label key={day} className="flex items-center gap-2 text-sm text-zinc-100">
              <input type="checkbox" checked={schedule.working_days.includes(day)} onChange={() => update({
                working_days: schedule.working_days.includes(day) ? schedule.working_days.filter(n => n !== day) : [...schedule.working_days, day],
              })} />{label}</label>)}
          </div>
        </fieldset>
        <label className="block space-y-1 text-sm text-zinc-300">Нерабочие даты · ГГГГ-ММ-ДД
          <textarea rows={3} className={inputClass} value={closedDates}
            onChange={e => { setClosedDates(e.target.value); setSaved(false) }} />
        </label>
      </fieldset>
      <button type="button" onClick={() => void save()} disabled={!loaded || saving}
        className="inline-flex max-w-full items-center gap-2 rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-100 disabled:opacity-40">
        {saving ? <LoaderCircle size={16} className="shrink-0 animate-spin" /> : <Save size={16} className="shrink-0" />}
        Сохранить расписание HOLD
      </button>
      {saved && <p role="status" className="text-sm text-emerald-300">Расписание сохранено</p>}
    </>}
    {error && <p role="alert" className="text-sm text-red-300">{error}
      {!loaded && <button type="button" className="ml-2 underline" onClick={() => setRetry(n => n + 1)}>Повторить</button>}
    </p>}
  </section>
}

import type { FunnelStep } from '../types'

export type RepeatedStartMode = 'inherit' | 'continue' | 'remind'

export function defaultStartStep(steps: FunnelStep[]) {
  return steps.find((step) => step.step_type === 'trigger'
    && !(step.block_type === 'generic_trigger' && step.config_json.trigger_type === 'custom_command'))
}

export function RepeatedStartModeSelect({ value, inherit = false, onChange }: {
  value: RepeatedStartMode
  inherit?: boolean
  onChange: (mode: RepeatedStartMode) => void
}) {
  return <label className="block">
    <span className="mb-1 block text-xs font-medium text-gray-400">Реакция на повторный /start</span>
    <select value={value} onChange={(event) => onChange(event.target.value as RepeatedStartMode)}
      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-2 text-sm text-gray-100 outline-none focus:ring-2 focus:ring-accent-400/50">
      {inherit && <option value="inherit">Как в настройках воронки</option>}
      <option value="continue">Продолжать</option>
      <option value="remind">Напомнить текущий шаг</option>
    </select>
  </label>
}

export default function RepeatedStartSettings({ steps, readOnly, onUpdate }: {
  steps: FunnelStep[]
  readOnly: boolean
  onUpdate: (stepId: string, patch: Partial<FunnelStep>) => void
}) {
  const trigger = defaultStartStep(steps)
  const raw = trigger?.config_json.repeat_start_defaults
  const defaults = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
  const mode = defaults.mode === 'remind' ? 'remind' : 'continue'
  const text = typeof defaults.text === 'string' ? defaults.text : ''
  const patch = (change: Record<string, unknown>) => {
    if (!trigger || readOnly) return
    onUpdate(trigger.id, { config_json: { ...trigger.config_json,
      repeat_start_defaults: { ...defaults, mode, text, ...change } } })
  }
  return <section className="mx-auto w-full max-w-2xl space-y-5 px-4 py-6 sm:px-6">
    <h2 className="text-base font-semibold text-white">Повторный /start</h2>
    {!trigger && <p role="status" className="text-sm text-amber-200">Стартовый блок отсутствует.</p>}
    <fieldset disabled={readOnly || !trigger} className="min-w-0 space-y-4 disabled:opacity-70">
      <RepeatedStartModeSelect value={mode} onChange={(value) => patch({ mode: value })} />
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-gray-400">Текст перед напоминанием (необязательно)</span>
        <textarea rows={4} maxLength={4000} value={text} onChange={(event) => patch({ text: event.target.value })}
          className="w-full resize-y rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none focus:ring-2 focus:ring-accent-400/50" />
      </label>
    </fieldset>
  </section>
}

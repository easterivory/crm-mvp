import { Plus, Trash2 } from 'lucide-react'

import type { FunnelPushRule, FunnelStep } from '../types'
import {
  funnelStepLabel,
  funnelStepNumberMap,
  orderedFunnelSteps,
} from '../funnelConfig'

type PushRulesPanelProps = {
  selectedStep: FunnelStep | null
  steps: FunnelStep[]
  rules: FunnelPushRule[]
  onChange: (rules: FunnelPushRule[]) => void
}

const actions = [
  ['stay', 'Остаться'],
  ['move_to_step', 'Перейти к блоку'],
  ['finish', 'Завершить'],
  ['assign_operator', 'Назначить оператора'],
] as const

export default function PushRulesPanel({
  selectedStep,
  steps,
  rules,
  onChange,
}: PushRulesPanelProps) {
  const stepRules = selectedStep ? rules.filter((rule) => rule.step_id === selectedStep.id) : []
  const numberById = funnelStepNumberMap(steps)

  const addRule = () => {
    if (!selectedStep) {
      return
    }
    onChange([
      ...rules,
      {
        id: crypto.randomUUID(),
        step_id: selectedStep.id,
        delay_minutes: 30,
        message_text: 'Напомнить клиенту о вопросе',
        action_after_send: 'stay',
        target_step_id: null,
        is_active: true,
      },
    ])
  }

  const patchRule = (ruleId: string, patch: Partial<FunnelPushRule>) => {
    onChange(rules.map((rule) => (rule.id === ruleId ? { ...rule, ...patch } : rule)))
  }

  const removeRule = (ruleId: string) => {
    onChange(rules.filter((rule) => rule.id !== ruleId))
  }

  return (
    <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-white">Push rules</h3>
        <button
          type="button"
          onClick={addRule}
          disabled={!selectedStep}
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 text-xs text-gray-200 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      {!selectedStep ? (
        <p className="mt-2 text-sm text-gray-500">Выберите блок для настройки push.</p>
      ) : null}

      {stepRules.length > 0 ? (
        <div className="mt-3 space-y-3">
          {stepRules.map((rule) => (
            <div key={rule.id} className="rounded-lg border border-white/8 bg-background/45 p-3">
              <div className="grid gap-2">
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">Задержка, минут</span>
                  <input
                    type="number"
                    min={1}
                    value={rule.delay_minutes}
                    onChange={(event) =>
                      patchRule(rule.id, { delay_minutes: Number(event.target.value) || 1 })
                    }
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">Сообщение</span>
                  <textarea
                    rows={2}
                    value={rule.message_text}
                    onChange={(event) => patchRule(rule.id, { message_text: event.target.value })}
                    className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">После отправки</span>
                  <select
                    value={rule.action_after_send}
                    onChange={(event) =>
                      patchRule(rule.id, {
                        action_after_send: event.target.value as FunnelPushRule['action_after_send'],
                      })
                    }
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  >
                    {actions.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {rule.action_after_send === 'move_to_step' ? (
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">Целевой блок</span>
                    <select
                      value={rule.target_step_id ?? ''}
                      onChange={(event) =>
                        patchRule(rule.id, { target_step_id: event.target.value || null })
                      }
                      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                    >
                      <option value="">Выберите блок</option>
                      {orderedFunnelSteps(steps).map((step) => (
                        <option key={step.id} value={step.id}>
                          {funnelStepLabel(step, numberById)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => removeRule(rule.id)}
                className="mt-2 inline-flex h-8 items-center gap-1 rounded-lg border border-red-300/15 px-2 text-xs text-red-200 transition hover:border-red-300/35"
              >
                <Trash2 size={13} />
                Удалить
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}

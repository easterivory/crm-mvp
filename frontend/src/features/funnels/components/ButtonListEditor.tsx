import { ArrowDown, ArrowUp, Phone, Plus, Trash2 } from 'lucide-react'

import type { FunnelStep } from '../types'
import {
  configId,
  funnelStepLabel,
  funnelStepNumberMap,
  orderedFunnelSteps,
  type ButtonConfig,
} from '../funnelConfig'

type TargetSelectProps = {
  value?: string
  currentStepId: string
  steps: FunnelStep[]
  onChange: (value: string) => void
}

export function TargetSelect({ value, currentStepId, steps, onChange }: TargetSelectProps) {
  const numberById = funnelStepNumberMap(steps)
  return (
    <select
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
    >
      <option value="">По обычной связи</option>
      {orderedFunnelSteps(steps)
        .filter((item) => item.id !== currentStepId)
        .map((item) => (
          <option key={item.id} value={item.id}>
            {funnelStepLabel(item, numberById)}
          </option>
        ))}
    </select>
  )
}

type ButtonListEditorProps = {
  buttons: ButtonConfig[]
  currentStepId: string
  steps: FunnelStep[]
  onChange: (buttons: ButtonConfig[]) => void
  title?: string
}

export default function ButtonListEditor({
  buttons,
  currentStepId,
  steps,
  onChange,
  title = 'Кнопки',
}: ButtonListEditorProps) {
  const update = (index: number, patch: Partial<ButtonConfig>) => {
    onChange(buttons.map((button, idx) => (idx === index ? { ...button, ...patch } : button)))
  }

  const move = (from: number, to: number) => {
    const next = [...buttons]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-500">{title}</span>
        <button
          type="button"
          disabled={buttons.some((button) => button.type === 'contact')}
          onClick={() =>
            onChange([
              ...buttons,
              { id: configId('btn'), label: 'Кнопка', value: 'button', type: 'branch' },
            ])
          }
          className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      {buttons.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/10 px-3 py-2 text-xs text-gray-500">
          Кнопок пока нет.
        </p>
      ) : null}

      {buttons.map((button, index) => (
        <div key={button.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-2">
          <div className="flex items-center gap-2">
            <input
              value={button.label}
              onChange={(event) => update(index, { label: event.target.value })}
              placeholder="Текст кнопки"
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
            <button
              type="button"
              disabled={index === 0}
              onClick={() => move(index, index - 1)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
              title="Выше"
            >
              <ArrowUp size={13} />
            </button>
            <button
              type="button"
              disabled={index === buttons.length - 1}
              onClick={() => move(index, index + 1)}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
              title="Ниже"
            >
              <ArrowDown size={13} />
            </button>
            <button
              type="button"
              onClick={() => onChange(buttons.filter((_, idx) => idx !== index))}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35"
              title="Удалить"
            >
              <Trash2 size={13} />
            </button>
          </div>

          <div className="mt-2 grid gap-2">
            <select
              value={button.type}
              onChange={(event) => {
                const type = event.target.value as ButtonConfig['type']
                const nextButton = {
                  ...button,
                  type,
                  target_step_id: type === 'branch' ? button.target_step_id : undefined,
                  url: type === 'url' ? button.url : undefined,
                  value: type === 'contact' ? 'contact' : button.value,
                }
                if (type === 'contact') {
                  onChange([nextButton])
                } else {
                  update(index, nextButton)
                }
              }}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="branch">Ветка</option>
              <option value="url">URL</option>
              <option value="contact">Запросить номер Telegram</option>
            </select>
            {button.type !== 'contact' ? (
              <input
                value={button.value}
                onChange={(event) => update(index, { value: event.target.value })}
                placeholder="value"
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            ) : null}
            {button.type === 'url' ? (
              <input
                value={button.url ?? ''}
                onChange={(event) => update(index, { url: event.target.value })}
                placeholder="https://example.com"
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            ) : button.type === 'contact' ? (
              <div className="flex items-start gap-2 rounded-lg border border-emerald-300/15 bg-emerald-300/5 px-3 py-2 text-xs leading-5 text-emerald-100/80">
                <Phone size={14} className="mt-0.5 shrink-0" />
                Telegram покажет системную кнопку отправки номера. Она работает в личном чате с ботом.
              </div>
            ) : (
              <>
                <TargetSelect
                  value={button.target_step_id}
                  currentStepId={currentStepId}
                  steps={steps}
                  onChange={(value) => update(index, { target_step_id: value })}
                />
                {!button.target_step_id ? (
                  <span className="text-xs text-amber-200">
                    Без target используется обычная связь блока.
                  </span>
                ) : null}
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

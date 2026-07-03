import { ArrowDown, ArrowUp, Phone, Plus, Trash2 } from 'lucide-react'

import type { FunnelStep } from '../types'
import {
  configId,
  funnelStepLabel,
  funnelStepNumberMap,
  orderedFunnelSteps,
  type ButtonConfig,
  type ButtonDisplayMode,
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
  buttonMode?: ButtonDisplayMode
  onButtonModeChange?: (mode: ButtonDisplayMode) => void
  title?: string
}

export default function ButtonListEditor({
  buttons,
  currentStepId,
  steps,
  onChange,
  buttonMode = 'inline',
  onButtonModeChange,
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
          onClick={() =>
            onChange([
              ...buttons,
              { id: configId('btn'), label: 'Кнопка', value: 'button', type: 'branch' },
            ])
          }
          className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      {onButtonModeChange ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Размещение</span>
          <select
            value={buttonMode}
            onChange={(event) => {
              const mode = event.target.value as ButtonDisplayMode
              onButtonModeChange(mode)
              onChange(buttons.map((button) =>
                button.type === 'contact'
                  ? { ...button, contact_mode: mode === 'reply' ? 'native' : 'mini_app' }
                  : button,
              ))
            }}
            disabled={buttons.some((button) => button.type === 'url')}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
          >
            <option value="inline">Inline под сообщением</option>
            <option value="reply">Клавиатура у поля ввода</option>
          </select>
          {buttons.some((button) => button.type === 'url') ? (
            <span className="mt-1 block text-xs text-gray-500">
              URL-кнопки поддерживаются только в inline-режиме.
            </span>
          ) : null}
        </label>
      ) : null}

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
                  target_step_id:
                    type === 'branch' || type === 'contact'
                      ? button.target_step_id
                      : undefined,
                  url: type === 'url' ? button.url : undefined,
                  value: type === 'contact' ? 'contact' : button.value,
                  contact_mode: type === 'contact' ? button.contact_mode ?? 'mini_app' : undefined,
                }
                if (type === 'url') {
                  onButtonModeChange?.('inline')
                }
                update(index, nextButton)
              }}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="branch">Ветка</option>
              <option value="url">URL</option>
              <option
                value="contact"
                disabled={buttons.some((item, itemIndex) => itemIndex !== index && item.type === 'contact')}
              >
                Запросить номер Telegram
              </option>
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
              <>
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">Способ запроса</span>
                  <select
                    value={button.contact_mode ?? 'mini_app'}
                    onChange={(event) => {
                      const contactMode = event.target.value as 'mini_app' | 'native'
                      update(index, { contact_mode: contactMode })
                      onButtonModeChange?.(contactMode === 'native' ? 'reply' : 'inline')
                    }}
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  >
                    <option value="mini_app">Mini App под сообщением</option>
                    <option value="native">Нативная кнопка Telegram</option>
                  </select>
                </label>
                <div className="flex items-start gap-2 rounded-lg border border-emerald-300/15 bg-emerald-300/5 px-3 py-2 text-xs leading-5 text-emerald-100/80">
                  <Phone size={14} className="mt-0.5 shrink-0" />
                  {(button.contact_mode ?? 'mini_app') === 'native'
                    ? 'Telegram запросит номер нативно и скроет одноразовую клавиатуру после отправки.'
                    : 'Mini App запросит номер через Telegram, после отправки кнопка будет убрана.'}
                </div>
                <TargetSelect
                  value={button.target_step_id}
                  currentStepId={currentStepId}
                  steps={steps}
                  onChange={(value) => update(index, { target_step_id: value })}
                />
              </>
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
            {button.type === 'branch' && buttonMode === 'inline' ? (
              <label className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/[0.025] px-3 py-2 text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={button.hide_after_click === true}
                  onChange={(event) => update(index, { hide_after_click: event.target.checked })}
                />
                Убрать inline-кнопки после нажатия
              </label>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  )
}

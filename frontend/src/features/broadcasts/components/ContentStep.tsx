import { Braces, Plus, Trash2 } from 'lucide-react'

import type { BroadcastContent, BroadcastOption } from '../types'
import BroadcastButtonListEditor from './BroadcastButtonListEditor'
import VariablePicker from './VariablePicker'

type ContentStepProps = {
  content: BroadcastContent
  botId: string | null
  funnels: BroadcastOption[]
  templates: Array<{ id: string; name: string; content_json: BroadcastContent }>
  onChange: (content: BroadcastContent) => void
  onSaveTemplate: () => void
  onApplyTemplate: (content: BroadcastContent) => void
}

function ensureMessages(content: BroadcastContent) {
  return content.messages.length
    ? content.messages
    : [{ type: 'text' as const, text: '', delay_seconds: 0, buttons: [] }]
}

export default function ContentStep({
  content,
  botId,
  funnels,
  templates,
  onChange,
  onSaveTemplate,
  onApplyTemplate,
}: ContentStepProps) {
  const messages = ensureMessages(content)
  const firstMessage = messages[0]?.text ?? ''
  const availableFunnels = funnels.filter((funnel) => !botId || funnel.meta?.botId === botId)

  const updateMessage = (index: number, patch: Partial<(typeof messages)[number]>) => {
    onChange({
      ...content,
      messages: messages.map((message, idx) => (idx === index ? { ...message, ...patch } : message)),
    })
  }

  const addMessage = () => {
    onChange({
      ...content,
      messages: [...messages, { type: 'text', text: '', delay_seconds: 0, buttons: [] }],
    })
  }

  const removeMessage = (index: number) => {
    const next = messages.filter((_, idx) => idx !== index)
    onChange({ ...content, messages: next.length ? next : [{ type: 'text', text: '', buttons: [] }] })
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-white">Шаблоны</p>
            <p className="text-xs text-gray-500">Можно сохранить текущий текст или подставить готовый.</p>
          </div>
          <button
            type="button"
            onClick={onSaveTemplate}
            className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
          >
            Сохранить как шаблон
          </button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {templates.length === 0 ? (
            <span className="text-sm text-gray-500">Шаблонов пока нет.</span>
          ) : (
            templates.map((template) => (
              <button
                key={template.id}
                type="button"
                onClick={() => onApplyTemplate(template.content_json)}
                className="rounded-full border border-white/10 px-3 py-1 text-xs text-gray-300 transition hover:border-accent-300/35"
              >
                {template.name}
              </button>
            ))
          )}
        </div>
      </div>

      <div className="space-y-3">
        {messages.map((message, index) => (
          <section key={index} className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-sm font-semibold text-white">Сообщение {index + 1}</p>
              <button
                type="button"
                onClick={() => removeMessage(index)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
              >
                <Trash2 size={14} />
              </button>
            </div>
            <textarea
              rows={6}
              value={message.text}
              onChange={(event) => updateMessage(index, { text: event.target.value })}
              placeholder="Напишите сообщение для рассылки..."
              className="w-full resize-none rounded-xl border border-white/10 bg-background/70 px-4 py-3 text-sm leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
            />
            <label className="mt-3 block">
              <span className="mb-1 block text-xs text-gray-500">Задержка перед сообщением, сек.</span>
              <input
                type="number"
                min={0}
                value={message.delay_seconds ?? 0}
                onChange={(event) => updateMessage(index, { delay_seconds: Number(event.target.value || 0) })}
                className="w-44 rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
              />
            </label>
            <div className="mt-4">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">Кнопки</p>
              <BroadcastButtonListEditor
                buttons={message.buttons ?? []}
                funnels={availableFunnels}
                onChange={(buttons) => updateMessage(index, { buttons })}
              />
            </div>
          </section>
        ))}
        <button
          type="button"
          onClick={addMessage}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={15} />
          Добавить сообщение
        </button>
      </div>

      <div className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-200">
          <Braces size={16} className="text-accent-200" />
          Переменные
        </div>
        <VariablePicker
          onInsert={(value) =>
            updateMessage(0, {
              text: `${firstMessage}${firstMessage.endsWith(' ') || !firstMessage ? '' : ' '}${value}`,
            })
          }
        />
      </div>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <p className="text-sm font-semibold text-white">Действие после отправки</p>
        <p className="mt-1 text-xs text-gray-500">
          Broadcast-сценарий не меняет активную воронку бота, а запускает выбранную кампанию точечно.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-[190px_minmax(0,1fr)_190px]">
          <select
            value={content.after_send_action?.type ?? ''}
            onChange={(event) =>
              onChange({
                ...content,
                after_send_action: event.target.value
                  ? { type: 'start_funnel', funnel_id: '', funnel_version_id: null, mode: 'skip_if_active' }
                  : null,
              })
            }
            className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
          >
            <option value="">Только отправить</option>
            <option value="start_funnel">Запустить воронку</option>
          </select>
          <select
            value={content.after_send_action?.funnel_id ?? ''}
            disabled={!content.after_send_action}
            onChange={(event) => {
              const selected = funnels.find((item) => item.id === event.target.value)
              onChange({
                ...content,
                after_send_action: content.after_send_action
                  ? {
                      ...content.after_send_action,
                      funnel_id: selected?.id ?? '',
                      funnel_version_id: (selected?.meta?.versionId as string | undefined) ?? null,
                    }
                  : null,
              })
            }}
            className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none disabled:opacity-50"
          >
            <option value="">Выберите опубликованную воронку</option>
            {availableFunnels.map((funnel) => (
              <option key={funnel.id} value={funnel.id}>{funnel.label}</option>
            ))}
          </select>
          <select
            value={content.after_send_action?.mode ?? 'skip_if_active'}
            disabled={!content.after_send_action}
            onChange={(event) =>
              onChange({
                ...content,
                after_send_action: content.after_send_action
                  ? { ...content.after_send_action, mode: event.target.value as never }
                  : null,
              })
            }
            className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none disabled:opacity-50"
          >
            <option value="skip_if_active">Не трогать активных</option>
            <option value="skip_if_completed">Не трогать завершивших</option>
            <option value="restart">Перезапустить</option>
          </select>
        </div>
      </section>
    </div>
  )
}

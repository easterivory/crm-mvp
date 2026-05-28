import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'

import type { FunnelStep } from '../types'
import { configId, type MessageConfig } from '../funnelConfig'
import ButtonListEditor from './ButtonListEditor'

type MessageSequenceEditorProps = {
  messages: MessageConfig[]
  currentStepId: string
  steps: FunnelStep[]
  onChange: (messages: MessageConfig[]) => void
}

export default function MessageSequenceEditor({
  messages,
  currentStepId,
  steps,
  onChange,
}: MessageSequenceEditorProps) {
  const move = (from: number, to: number) => {
    const next = [...messages]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    onChange(next)
  }

  const update = (index: number, patch: Partial<MessageConfig>) => {
    onChange(messages.map((message, idx) => (idx === index ? { ...message, ...patch } : message)))
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Sequence</p>
          <p className="text-xs text-gray-600">Несколько сообщений внутри одного блока.</p>
        </div>
        <button
          type="button"
          onClick={() =>
            onChange([
              ...messages,
              { id: configId('msg'), type: 'text', text: '', delay_seconds: 0, buttons: [] },
            ])
          }
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      {messages.map((message, index) => (
        <div key={message.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold text-gray-300">Сообщение {index + 1}</span>
            <div className="flex gap-1">
              <button
                type="button"
                disabled={index === 0}
                onClick={() => move(index, index - 1)}
                className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                title="Вверх"
              >
                <ArrowUp size={13} />
              </button>
              <button
                type="button"
                disabled={index === messages.length - 1}
                onClick={() => move(index, index + 1)}
                className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                title="Вниз"
              >
                <ArrowDown size={13} />
              </button>
              <button
                type="button"
                disabled={messages.length === 1}
                onClick={() => onChange(messages.filter((_, idx) => idx !== index))}
                className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-red-300/15 text-red-200 disabled:opacity-40"
                title="Удалить"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>

          <textarea
            rows={4}
            value={message.text}
            onChange={(event) => update(index, { text: event.target.value })}
            placeholder="Текст сообщения"
            className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />

          <label className="mt-2 block">
            <span className="mb-1 block text-xs text-gray-500">Задержка перед сообщением, сек</span>
            <input
              type="number"
              min={0}
              value={message.delay_seconds}
              onChange={(event) => update(index, { delay_seconds: Number(event.target.value) || 0 })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>

          <div className="mt-3">
            <ButtonListEditor
              buttons={message.buttons}
              currentStepId={currentStepId}
              steps={steps}
              onChange={(buttons) => update(index, { buttons })}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

import { Plus, Trash2 } from 'lucide-react'

import type { BroadcastOption } from '../types'

type BroadcastButton = Record<string, unknown> & {
  id?: string
  label?: string
  type?: 'url' | 'callback' | 'start_funnel'
  url?: string
  payload?: string
  funnel_id?: string
  funnel_version_id?: string | null
}

type Props = {
  buttons: BroadcastButton[]
  funnels: BroadcastOption[]
  onChange: (buttons: BroadcastButton[]) => void
}

function newButton(): BroadcastButton {
  return {
    id: crypto.randomUUID(),
    label: 'Кнопка',
    type: 'callback',
    payload: '',
  }
}

export default function BroadcastButtonListEditor({ buttons, funnels, onChange }: Props) {
  const update = (index: number, patch: Partial<BroadcastButton>) => {
    onChange(buttons.map((button, idx) => (idx === index ? { ...button, ...patch } : button)))
  }

  return (
    <div className="space-y-2">
      {buttons.map((button, index) => (
        <div key={button.id ?? index} className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_145px_auto]">
            <input
              value={button.label ?? ''}
              onChange={(event) => update(index, { label: event.target.value })}
              placeholder="Текст кнопки"
              className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            />
            <select
              value={button.type ?? 'callback'}
              onChange={(event) =>
                update(index, { type: event.target.value as BroadcastButton['type'] })
              }
              className="rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            >
              <option value="callback">Callback</option>
              <option value="url">URL</option>
              <option value="start_funnel">Запустить воронку</option>
            </select>
            <button
              type="button"
              onClick={() => onChange(buttons.filter((_, idx) => idx !== index))}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
            >
              <Trash2 size={15} />
            </button>
          </div>
          {button.type === 'url' ? (
            <input
              value={button.url ?? ''}
              onChange={(event) => update(index, { url: event.target.value })}
              placeholder="https://..."
              className="mt-2 w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            />
          ) : null}
          {button.type === 'callback' ? (
            <input
              value={button.payload ?? ''}
              onChange={(event) => update(index, { payload: event.target.value })}
              placeholder="payload для логирования"
              className="mt-2 w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            />
          ) : null}
          {button.type === 'start_funnel' ? (
            <select
              value={button.funnel_id ?? ''}
              onChange={(event) => {
                const selected = funnels.find((item) => item.id === event.target.value)
                update(index, {
                  funnel_id: selected?.id ?? '',
                  funnel_version_id: selected?.meta?.versionId as string | undefined,
                })
              }}
              className="mt-2 w-full rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none"
            >
              <option value="">Выберите опубликованную воронку</option>
              {funnels.map((funnel) => (
                <option key={funnel.id} value={funnel.id}>{funnel.label}</option>
              ))}
            </select>
          ) : null}
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...buttons, newButton()])}
        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
      >
        <Plus size={15} />
        Добавить кнопку
      </button>
    </div>
  )
}

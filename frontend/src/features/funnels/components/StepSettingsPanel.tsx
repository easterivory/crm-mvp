import { Trash2 } from 'lucide-react'

import { blockGroups, getBlockLabel, mvpBlockTypes } from '../blockCatalog'
import type { FunnelStep } from '../types'
import UnsupportedBlockCard from './UnsupportedBlockCard'

type StepSettingsPanelProps = {
  step: FunnelStep | null
  onUpdate: (stepId: string, patch: Partial<FunnelStep>) => void
  onDelete: (stepId: string) => void
}

function textValue(config: Record<string, unknown>, key: string) {
  const value = config[key]
  return typeof value === 'string' ? value : ''
}

function numberValue(config: Record<string, unknown>, key: string, fallback: number) {
  const value = config[key]
  return typeof value === 'number' ? value : fallback
}

export default function StepSettingsPanel({
  step,
  onUpdate,
  onDelete,
}: StepSettingsPanelProps) {
  if (!step) {
    return (
      <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
        <h3 className="text-sm font-semibold text-white">Настройки блока</h3>
        <p className="mt-2 text-sm text-gray-500">Выберите блок на canvas.</p>
      </section>
    )
  }

  const isSupported = mvpBlockTypes.has(step.block_type)
  const patchConfig = (patch: Record<string, unknown>) => {
    onUpdate(step.id, { config_json: { ...step.config_json, ...patch } })
  }

  return (
    <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white">Настройки блока</h3>
          <p className="truncate text-xs text-gray-500">{getBlockLabel(step.block_type)}</p>
        </div>
        <button
          type="button"
          onClick={() => onDelete(step.id)}
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35"
          title="Удалить блок"
        >
          <Trash2 size={14} />
        </button>
      </div>

      <div className="mt-3 space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Название</span>
          <input
            value={step.title}
            onChange={(event) => onUpdate(step.id, { title: event.target.value })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Тип блока</span>
          <select
            value={step.block_type}
            onChange={(event) => {
              const item = blockGroups
                .flatMap((group) => group.items)
                .find((candidate) => candidate.blockType === event.target.value)
              if (!item) {
                return
              }
              onUpdate(step.id, {
                title: item.defaultTitle,
                step_type: item.stepType,
                block_type: item.blockType,
                config_json: item.defaultConfig ?? {},
              })
            }}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          >
            {blockGroups.map((group) => (
              <optgroup key={group.title} label={group.title}>
                {group.items.map((item) => (
                  <option key={item.blockType} value={item.blockType}>
                    {item.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>

        {!isSupported ? <UnsupportedBlockCard blockType={step.block_type} /> : null}

        {isSupported && step.step_type === 'message' ? (
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Текст сообщения</span>
            <textarea
              rows={4}
              value={textValue(step.config_json, 'text') || textValue(step.config_json, 'message_text')}
              onChange={(event) => patchConfig({ text: event.target.value })}
              className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
            <span className="mt-1 block text-xs text-gray-500">
              Переменные: {'{{name}}'}, {'{{phone}}'}, {'{{project}}'}, {'{{bot}}'}
            </span>
          </label>
        ) : null}

        {isSupported && step.step_type === 'input' ? (
          <>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Текст вопроса</span>
              <textarea
                rows={3}
                value={textValue(step.config_json, 'question_text') || textValue(step.config_json, 'text')}
                onChange={(event) => patchConfig({ question_text: event.target.value })}
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
            {step.block_type === 'ask_choice' ? (
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Варианты, по одному в строке</span>
                <textarea
                  rows={4}
                  value={
                    Array.isArray(step.config_json.options)
                      ? (step.config_json.options as string[]).join('\n')
                      : ''
                  }
                  onChange={(event) =>
                    patchConfig({
                      options: event.target.value
                        .split('\n')
                        .map((item) => item.trim())
                        .filter(Boolean),
                    })
                  }
                  className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              </label>
            ) : null}
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Сообщение при ошибке</span>
              <input
                value={textValue(step.config_json, 'retry_message')}
                onChange={(event) => patchConfig({ retry_message: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          </>
        ) : null}

        {isSupported && step.step_type === 'condition' ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Поле</span>
              <input
                value={textValue(step.config_json, 'field')}
                onChange={(event) => patchConfig({ field: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Значение</span>
              <input
                value={textValue(step.config_json, 'value')}
                onChange={(event) => patchConfig({ value: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          </div>
        ) : null}

        {isSupported && step.step_type === 'action' ? (
          <div className="grid gap-2">
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Поле/статус/тег</span>
              <input
                value={textValue(step.config_json, 'target')}
                onChange={(event) => patchConfig({ target: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
            {step.block_type === 'write_field' ? (
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">lead_field_key</span>
                <input
                  value={textValue(step.config_json, 'lead_field_key')}
                  onChange={(event) => patchConfig({ lead_field_key: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              </label>
            ) : null}
          </div>
        ) : null}

        {isSupported && step.step_type === 'delay' ? (
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">
              {step.block_type === 'wait_hours' ? 'Часы' : 'Минуты'}
            </span>
            <input
              type="number"
              min={1}
              value={
                step.block_type === 'wait_hours'
                  ? numberValue(step.config_json, 'delay_hours', 1)
                  : numberValue(step.config_json, 'delay_minutes', 10)
              }
              onChange={(event) =>
                patchConfig({
                  [step.block_type === 'wait_hours' ? 'delay_hours' : 'delay_minutes']:
                    Number(event.target.value) || 1,
                })
              }
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
        ) : null}

        {isSupported && step.step_type === 'integration' ? (
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">URL</span>
            <input
              value={textValue(step.config_json, 'url')}
              onChange={(event) => patchConfig({ url: event.target.value })}
              placeholder="https://example.com/webhook"
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none placeholder:text-gray-600"
            />
          </label>
        ) : null}
      </div>
    </section>
  )
}

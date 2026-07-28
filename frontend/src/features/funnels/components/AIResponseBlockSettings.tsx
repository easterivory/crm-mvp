import { BrainCircuit, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import {
  fetchAIProviderModels,
  fetchAIProviderOptions,
  type AIProviderOption,
} from '../../ai'
import { configId, leadFields } from '../funnelConfig'
import type { FunnelStep } from '../types'
import { TargetSelect } from './ButtonListEditor'

type AIOutcome = {
  id: string
  label: string
  instruction: string
  target_step_id: string
}

type AIOutputField = {
  id: string
  response_key: string
  lead_field_key: string
  value_type: 'text' | 'number' | 'boolean'
  required: boolean
}

type AIResponseBlockSettingsProps = {
  step: FunnelStep
  projectId: string
  steps: FunnelStep[]
  onConfigChange: (patch: Record<string, unknown>) => void
}

const inputClass =
  'w-full rounded-lg border border-white/10 bg-background/70 px-2.5 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2 md:text-sm'

function normalizeAIOutcomes(value: unknown): AIOutcome[] {
  if (!Array.isArray(value) || value.length === 0) {
    return [
      { id: 'continue', label: 'Далее', instruction: '', target_step_id: '' },
      { id: 'fallback', label: 'Ошибка / fallback', instruction: '', target_step_id: '' },
    ]
  }
  return value.map((item, index) => {
    const current = typeof item === 'object' && item !== null
      ? item as Record<string, unknown>
      : {}
    return {
      id: String(current.id ?? `route_${index + 1}`),
      label: String(current.label ?? `Маршрут ${index + 1}`),
      instruction: String(current.instruction ?? current.when ?? ''),
      target_step_id: typeof current.target_step_id === 'string'
        ? current.target_step_id
        : '',
    }
  })
}

function normalizeOutputFields(value: unknown): AIOutputField[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item, index) => {
    const current = typeof item === 'object' && item !== null
      ? item as Record<string, unknown>
      : {}
    const valueType = String(current.value_type ?? 'text')
    return {
      id: String(current.id ?? `ai_field_${index + 1}`),
      response_key: String(current.response_key ?? ''),
      lead_field_key: String(current.lead_field_key ?? ''),
      value_type: valueType === 'number' || valueType === 'boolean' ? valueType : 'text',
      required: current.required === true,
    }
  })
}

function optionalNumber(value: unknown) {
  return typeof value === 'number' || typeof value === 'string' ? String(value) : ''
}

export default function AIResponseBlockSettings({
  step,
  projectId,
  steps,
  onConfigChange,
}: AIResponseBlockSettingsProps) {
  const [providers, setProviders] = useState<AIProviderOption[]>([])
  const [models, setModels] = useState<string[]>([])
  const [isLoadingModels, setIsLoadingModels] = useState(false)
  const [modelWarning, setModelWarning] = useState<string | null>(null)

  const config = step.config_json
  const connectionId = typeof config.connection_id === 'string' ? config.connection_id : ''
  const outcomes = useMemo(() => normalizeAIOutcomes(config.outcomes), [config.outcomes])
  const outputFields = useMemo(
    () => normalizeOutputFields(config.output_fields),
    [config.output_fields],
  )

  useEffect(() => {
    let cancelled = false
    fetchAIProviderOptions(projectId)
      .then((items) => {
        if (!cancelled) setProviders(items)
      })
      .catch(() => {
        if (!cancelled) setProviders([])
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  const loadModels = async (selectedConnectionId: string) => {
    if (!selectedConnectionId) {
      setModels([])
      setModelWarning(null)
      return
    }
    setIsLoadingModels(true)
    setModelWarning(null)
    try {
      const result = await fetchAIProviderModels(selectedConnectionId)
      setModels(result.models)
      setModelWarning(result.warning)
    } catch {
      setModels([])
      setModelWarning('Список моделей недоступен. Название можно ввести вручную.')
    } finally {
      setIsLoadingModels(false)
    }
  }

  useEffect(() => {
    void loadModels(connectionId)
  }, [connectionId])

  const updateOutcome = (index: number, patch: Partial<AIOutcome>) => {
    onConfigChange({
      outcomes: outcomes.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    })
  }

  const updateOutputField = (index: number, patch: Partial<AIOutputField>) => {
    onConfigChange({
      output_fields: outputFields.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...patch } : item,
      ),
    })
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 border-b border-white/8 pb-3">
        <BrainCircuit size={17} className="shrink-0 text-cyan-200" />
        <h4 className="text-sm font-semibold text-white">ИИ-ответ</h4>
      </div>

      <label className="block">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
          Цель шага
        </span>
        <textarea
          value={typeof config.step_goal === 'string' ? config.step_goal : ''}
          onChange={(event) => onConfigChange({ step_goal: event.target.value })}
          rows={4}
          className={`${inputClass} resize-y`}
          placeholder="Что модель должна выяснить или сообщить"
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
          Правила этого шага
        </span>
        <textarea
          value={typeof config.instructions === 'string' ? config.instructions : ''}
          onChange={(event) => onConfigChange({ instructions: event.target.value })}
          rows={3}
          className={`${inputClass} resize-y`}
          placeholder="Необязательные ограничения и тон ответа"
        />
      </label>

      <div className="grid gap-3">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Подключение</span>
          <select
            value={connectionId}
            onChange={(event) => {
              const nextId = event.target.value
              const defaultModel = providers.find((item) => item.id === nextId)?.default_model ?? ''
              onConfigChange({ connection_id: nextId, model: defaultModel })
            }}
            className={inputClass}
          >
            <option value="">Настройки проекта</option>
            {providers.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.name} · {provider.provider}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1 flex items-center justify-between gap-2 text-xs text-gray-500">
            <span>Модель</span>
            {connectionId ? (
              <button
                type="button"
                onClick={() => void loadModels(connectionId)}
                disabled={isLoadingModels}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/10 text-gray-300 disabled:opacity-50"
                title="Обновить список моделей"
              >
                <RefreshCw size={13} className={isLoadingModels ? 'animate-spin' : ''} />
              </button>
            ) : null}
          </span>
          <input
            list={`ai-models-${step.id}`}
            value={typeof config.model === 'string' ? config.model : ''}
            onChange={(event) => onConfigChange({ model: event.target.value })}
            disabled={!connectionId}
            placeholder={connectionId ? 'Название модели' : 'Из настроек проекта'}
            className={`${inputClass} disabled:cursor-not-allowed disabled:opacity-60`}
          />
          <datalist id={`ai-models-${step.id}`}>
            {models.map((model) => <option key={model} value={model} />)}
          </datalist>
          {modelWarning ? (
            <span className="mt-1 block text-xs leading-5 text-amber-200/80">{modelWarning}</span>
          ) : null}
        </label>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Маршруты
          </span>
          <button
            type="button"
            onClick={() => onConfigChange({
              outcomes: [
                ...outcomes,
                {
                  id: `route_${outcomes.length + 1}`,
                  label: `Маршрут ${outcomes.length + 1}`,
                  instruction: '',
                  target_step_id: '',
                },
              ],
            })}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-cyan-300/40"
          >
            <Plus size={13} />
            Добавить
          </button>
        </div>
        {outcomes.map((outcome, index) => (
          <div key={`${outcome.id}:${index}`} className="grid gap-2 rounded-lg border border-white/8 bg-white/[0.03] p-2">
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_32px] gap-2">
              <input
                value={outcome.id}
                onChange={(event) => updateOutcome(index, { id: event.target.value.toLowerCase() })}
                disabled={outcome.id === 'fallback'}
                placeholder="route_key"
                className={`${inputClass} min-w-0 disabled:opacity-70`}
              />
              <input
                value={outcome.label}
                onChange={(event) => updateOutcome(index, { label: event.target.value })}
                placeholder="Название"
                className={`${inputClass} min-w-0`}
              />
              <button
                type="button"
                onClick={() => onConfigChange({
                  outcomes: outcomes.filter((_, itemIndex) => itemIndex !== index),
                })}
                disabled={outcome.id === 'fallback'}
                className="inline-flex h-10 w-8 items-center justify-center rounded-lg border border-red-300/15 text-red-200 disabled:cursor-not-allowed disabled:opacity-30"
                title="Удалить маршрут"
              >
                <Trash2 size={13} />
              </button>
            </div>
            <input
              value={outcome.instruction}
              onChange={(event) => updateOutcome(index, { instruction: event.target.value })}
              placeholder="Когда модель должна выбрать этот маршрут"
              className={inputClass}
            />
            <TargetSelect
              value={outcome.target_step_id}
              currentStepId={step.id}
              steps={steps}
              onChange={(value) => updateOutcome(index, { target_step_id: value })}
            />
          </div>
        ))}
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">
            Данные в карточку лида
          </span>
          <button
            type="button"
            onClick={() => onConfigChange({
              output_fields: [
                ...outputFields,
                {
                  id: configId('ai_field'),
                  response_key: '',
                  lead_field_key: '',
                  value_type: 'text',
                  required: false,
                },
              ],
            })}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-cyan-300/40"
          >
            <Plus size={13} />
            Добавить
          </button>
        </div>
        {outputFields.length === 0 ? (
          <p className="rounded-lg border border-dashed border-white/10 px-3 py-2 text-xs text-gray-500">
            Извлечение данных выключено.
          </p>
        ) : null}
        {outputFields.map((field, index) => (
          <div key={field.id} className="grid gap-2 rounded-lg border border-white/8 bg-white/[0.03] p-2">
            <div className="flex gap-2">
              <input
                value={field.response_key}
                onChange={(event) => updateOutputField(index, {
                  response_key: event.target.value.toLowerCase(),
                })}
                placeholder="Ключ ответа модели"
                className={`${inputClass} min-w-0 flex-1`}
              />
              <button
                type="button"
                onClick={() => onConfigChange({
                  output_fields: outputFields.filter((_, itemIndex) => itemIndex !== index),
                })}
                className="inline-flex h-10 w-9 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
                title="Удалить поле"
              >
                <Trash2 size={13} />
              </button>
            </div>
            <input
              list={`lead-fields-${step.id}`}
              value={field.lead_field_key}
              onChange={(event) => updateOutputField(index, { lead_field_key: event.target.value })}
              placeholder="Поле лида или новый custom_key"
              className={inputClass}
            />
            <datalist id={`lead-fields-${step.id}`}>
              {leadFields.filter(([value]) => value).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </datalist>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
              <select
                value={field.value_type}
                onChange={(event) => updateOutputField(index, {
                  value_type: event.target.value as AIOutputField['value_type'],
                })}
                className={inputClass}
              >
                <option value="text">Текст</option>
                <option value="number">Число</option>
                <option value="boolean">Да / нет</option>
              </select>
              <label className="flex min-h-10 items-center gap-2 px-1 text-xs text-gray-300">
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(event) => updateOutputField(index, { required: event.target.checked })}
                />
                Обязательно
              </label>
            </div>
          </div>
        ))}
      </div>

      <label className="flex items-center justify-between gap-3 border-y border-white/8 py-3 text-sm text-gray-200">
        <span>Разделять ответ на сообщения</span>
        <input
          type="checkbox"
          checked={config.split_messages !== false}
          onChange={(event) => onConfigChange({ split_messages: event.target.checked })}
        />
      </label>

      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Temperature</span>
          <input
            type="number"
            min="0"
            max="2"
            step="0.05"
            value={optionalNumber(config.temperature)}
            onChange={(event) => onConfigChange({
              temperature: event.target.value === '' ? null : Number(event.target.value),
            })}
            placeholder="Проект"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Макс. токенов</span>
          <input
            type="number"
            min="1"
            max="32000"
            value={optionalNumber(config.max_output_tokens)}
            onChange={(event) => onConfigChange({
              max_output_tokens: event.target.value === '' ? null : Number(event.target.value),
            })}
            placeholder="Проект"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">мс на символ</span>
          <input
            type="number"
            min="0"
            max="250"
            value={optionalNumber(config.typing_delay_per_char_ms)}
            onChange={(event) => onConfigChange({
              typing_delay_per_char_ms: event.target.value === '' ? null : Number(event.target.value),
            })}
            placeholder="Проект"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">История, сообщений</span>
          <input
            type="number"
            min="1"
            max="100"
            value={optionalNumber(config.history_message_limit)}
            onChange={(event) => onConfigChange({
              history_message_limit: event.target.value === '' ? null : Number(event.target.value),
            })}
            placeholder="Проект"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Мин. задержка, мс</span>
          <input
            type="number"
            min="0"
            max="30000"
            value={optionalNumber(config.min_delay_ms)}
            onChange={(event) => onConfigChange({
              min_delay_ms: event.target.value === '' ? null : Number(event.target.value),
            })}
            placeholder="Проект"
            className={inputClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Макс. задержка, мс</span>
          <input
            type="number"
            min="0"
            max="30000"
            value={optionalNumber(config.max_delay_ms)}
            onChange={(event) => onConfigChange({
              max_delay_ms: event.target.value === '' ? null : Number(event.target.value),
            })}
            placeholder="Проект"
            className={inputClass}
          />
        </label>
      </div>

      <label className="block">
        <span className="mb-1 block text-xs text-gray-500">Сообщение при недоступности ИИ</span>
        <textarea
          value={typeof config.fallback_message === 'string' ? config.fallback_message : ''}
          onChange={(event) => onConfigChange({ fallback_message: event.target.value })}
          rows={3}
          className={`${inputClass} resize-y`}
          placeholder="Необязательно; затем сработает маршрут fallback"
        />
      </label>
    </div>
  )
}

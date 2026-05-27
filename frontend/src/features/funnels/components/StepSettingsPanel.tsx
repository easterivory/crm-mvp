import { ArrowDown, ArrowUp, Plus, Trash2, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { getBlockLabel, mvpBlockTypes, universalBlocks } from '../blockCatalog'
import type { FunnelStep } from '../types'
import UnsupportedBlockCard from './UnsupportedBlockCard'

type StepSettingsPanelProps = {
  step: FunnelStep | null
  steps: FunnelStep[]
  onUpdate: (stepId: string, patch: Partial<FunnelStep>) => void
  onDelete: (stepId: string) => void
}

type ButtonConfig = {
  id: string
  label: string
  value: string
  type: 'branch' | 'url'
  target_step_id?: string
  url?: string
}

type MessageConfig = {
  id: string
  type: string
  text: string
  delay_seconds: number
  buttons: ButtonConfig[]
}

type ConditionConfig = {
  id: string
  source: string
  field: string
  operator: string
  value: string
}

type OutcomeConfig = {
  id: string
  label: string
  target_step_id?: string
}

type ActionConfig = {
  id: string
  type: string
  tag_id?: string
  status?: string
  field?: string
  value?: string
  operator_id?: string
  note?: string
}

const answerTypes = [
  ['text', 'Текст'],
  ['phone', 'Телефон'],
  ['number', 'Число'],
  ['choice', 'Выбор'],
  ['date', 'Дата'],
  ['time', 'Время'],
]

const leadFields = [
  ['', 'Не сохранять'],
  ['name', 'Имя'],
  ['phone', 'Телефон'],
  ['username', 'Username'],
  ['age', 'Возраст'],
  ['country', 'Страна'],
  ['call_time_text', 'Время созвона'],
  ['has_card', 'Есть карта'],
  ['experience', 'Опыт'],
]

const conditionSources = [
  ['last_answer', 'Последний ответ'],
  ['lead_field', 'Поле лида'],
  ['tag', 'Тег'],
  ['status', 'Статус'],
  ['tracking_link', 'Ссылка'],
  ['operator_assigned', 'Оператор назначен'],
]

const conditionOperators = [
  ['equals', 'Равно'],
  ['not_equals', 'Не равно'],
  ['contains', 'Содержит'],
  ['exists', 'Заполнено'],
  ['empty', 'Пусто'],
  ['gt', 'Больше'],
  ['lt', 'Меньше'],
]

const actionTypes = [
  ['add_tag', 'Добавить тег'],
  ['remove_tag', 'Удалить тег'],
  ['clear_tags', 'Очистить теги'],
  ['set_lead_status', 'Изменить статус'],
  ['write_field', 'Записать поле'],
  ['assign_operator', 'Назначить оператора'],
  ['add_note', 'Добавить заметку'],
  ['send_to_crm_placeholder', 'CRM placeholder'],
]

function textValue(config: Record<string, unknown>, key: string) {
  const value = config[key]
  return typeof value === 'string' ? value : ''
}

function boolValue(config: Record<string, unknown>, key: string, fallback: boolean) {
  const value = config[key]
  return typeof value === 'boolean' ? value : fallback
}

function numberValue(config: Record<string, unknown>, key: string, fallback: number) {
  const value = config[key]
  return typeof value === 'number' ? value : fallback
}

function id(prefix: string) {
  return `${prefix}_${crypto.randomUUID().slice(0, 8)}`
}

function normalizeButton(raw: unknown, index: number): ButtonConfig {
  if (typeof raw === 'string') {
    return {
      id: `btn_${index + 1}`,
      label: raw,
      value: raw,
      type: 'branch',
    }
  }
  const item = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {}
  const label = String(item.label ?? item.text ?? item.title ?? item.value ?? `Кнопка ${index + 1}`)
  return {
    id: String(item.id ?? `btn_${index + 1}`),
    label,
    value: String(item.value ?? item.key ?? label),
    type: item.type === 'url' || item.url ? 'url' : 'branch',
    target_step_id: typeof item.target_step_id === 'string' ? item.target_step_id : '',
    url: typeof item.url === 'string' ? item.url : '',
  }
}

function normalizeButtons(raw: unknown): ButtonConfig[] {
  return Array.isArray(raw) ? raw.map(normalizeButton) : []
}

function normalizeMessages(config: Record<string, unknown>): MessageConfig[] {
  const rawMessages = config.messages
  if (Array.isArray(rawMessages) && rawMessages.length > 0) {
    return rawMessages.map((raw, index) => {
      const item = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {}
      return {
        id: String(item.id ?? `msg_${index + 1}`),
        type: String(item.type ?? 'text'),
        text: String(item.text ?? item.message ?? item.message_text ?? ''),
        delay_seconds: typeof item.delay_seconds === 'number' ? item.delay_seconds : 0,
        buttons: normalizeButtons(item.buttons),
      }
    })
  }
  return [
    {
      id: 'msg_1',
      type: 'text',
      text: textValue(config, 'text') || textValue(config, 'message') || textValue(config, 'message_text'),
      delay_seconds: numberValue(config, 'delay_seconds', 0),
      buttons: normalizeButtons(config.buttons),
    },
  ]
}

function normalizeConditions(raw: unknown): ConditionConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [{ id: id('cond'), source: 'last_answer', field: '', operator: 'equals', value: '' }]
  }
  return raw.map((item, index) => {
    const condition = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(condition.id ?? `cond_${index + 1}`),
      source: String(condition.source ?? condition.field ?? 'last_answer'),
      field: String(condition.field ?? ''),
      operator: String(condition.operator ?? condition.type ?? 'equals'),
      value: String(condition.value ?? ''),
    }
  })
}

function normalizeOutcomes(raw: unknown): OutcomeConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [
      { id: 'true', label: 'Да' },
      { id: 'false', label: 'Нет' },
      { id: 'fallback', label: 'Fallback' },
    ]
  }
  return raw.map((item, index) => {
    if (typeof item === 'string') {
      return { id: item, label: item }
    }
    const outcome = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(outcome.id ?? `outcome_${index + 1}`),
      label: String(outcome.label ?? outcome.id ?? `Исход ${index + 1}`),
      target_step_id: typeof outcome.target_step_id === 'string' ? outcome.target_step_id : '',
    }
  })
}

function normalizeActions(raw: unknown): ActionConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [{ id: id('action'), type: 'set_lead_status', status: 'in_progress' }]
  }
  return raw.map((item, index) => {
    const action = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(action.id ?? `action_${index + 1}`),
      type: String(action.type ?? 'set_lead_status'),
      tag_id: typeof action.tag_id === 'string' ? action.tag_id : '',
      status: typeof action.status === 'string' ? action.status : '',
      field: typeof action.field === 'string' ? action.field : '',
      value: typeof action.value === 'string' ? action.value : '',
      operator_id: typeof action.operator_id === 'string' ? action.operator_id : '',
      note: typeof action.note === 'string' ? action.note : '',
    }
  })
}

function TargetSelect({
  value,
  currentStepId,
  steps,
  onChange,
}: {
  value?: string
  currentStepId: string
  steps: FunnelStep[]
  onChange: (value: string) => void
}) {
  return (
    <select
      value={value ?? ''}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
    >
      <option value="">По обычной связи</option>
      {steps
        .filter((item) => item.id !== currentStepId)
        .map((item) => (
          <option key={item.id} value={item.id}>
            {item.title}
          </option>
        ))}
    </select>
  )
}

function ButtonListEditor({
  buttons,
  currentStepId,
  steps,
  onChange,
}: {
  buttons: ButtonConfig[]
  currentStepId: string
  steps: FunnelStep[]
  onChange: (buttons: ButtonConfig[]) => void
}) {
  const update = (index: number, patch: Partial<ButtonConfig>) => {
    onChange(buttons.map((button, idx) => (idx === index ? { ...button, ...patch } : button)))
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-gray-500">Кнопки</span>
        <button
          type="button"
          onClick={() =>
            onChange([
              ...buttons,
              { id: id('btn'), label: 'Кнопка', value: 'button', type: 'branch' },
            ])
          }
          className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>
      {buttons.map((button, index) => (
        <div key={button.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
          <div className="flex items-center justify-between gap-2">
            <input
              value={button.label}
              onChange={(event) => update(index, { label: event.target.value })}
              placeholder="Текст кнопки"
              className="min-w-0 flex-1 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
            <button
              type="button"
              onClick={() => onChange(buttons.filter((_, idx) => idx !== index))}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-red-300/15 text-red-200 transition hover:border-red-300/35"
              title="Удалить кнопку"
            >
              <X size={14} />
            </button>
          </div>
          <div className="mt-2 grid gap-2">
            <input
              value={button.value}
              onChange={(event) => update(index, { value: event.target.value })}
              placeholder="value"
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
            <select
              value={button.type}
              onChange={(event) => update(index, { type: event.target.value as 'branch' | 'url' })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="branch">Ветка</option>
              <option value="url">URL</option>
            </select>
            {button.type === 'url' ? (
              <input
                value={button.url ?? ''}
                onChange={(event) => update(index, { url: event.target.value })}
                placeholder="https://example.com"
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            ) : (
              <>
                <TargetSelect
                  value={button.target_step_id}
                  currentStepId={currentStepId}
                  steps={steps}
                  onChange={(value) => update(index, { target_step_id: value })}
                />
                {!button.target_step_id ? (
                  <span className="text-xs text-amber-200">Без target используется обычная связь блока.</span>
                ) : null}
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function StepSettingsPanel({
  step,
  steps,
  onUpdate,
  onDelete,
}: StepSettingsPanelProps) {
  if (!step) {
    return (
      <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
        <h3 className="text-sm font-semibold text-white">Настройки блока</h3>
        <p className="mt-2 text-sm text-gray-500">Выберите блок на полотне.</p>
      </section>
    )
  }

  const isSupported = mvpBlockTypes.has(step.block_type)
  const isUniversalBlock = universalBlocks.some((item) => item.blockType === step.block_type)
  const patchConfig = (patch: Record<string, unknown>) => {
    onUpdate(step.id, { config_json: { ...step.config_json, ...patch } })
  }
  const replaceConfig = (config: Record<string, unknown>) => {
    onUpdate(step.id, { config_json: config })
  }

  const sectionShell = (children: ReactNode) => (
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
      {children}
    </section>
  )

  if (!isSupported) {
    return sectionShell(
      <div className="mt-3">
        <UnsupportedBlockCard blockType={step.block_type} />
      </div>,
    )
  }

  const messages = normalizeMessages(step.config_json)
  const conditions = normalizeConditions(step.config_json.conditions)
  const outcomes = normalizeOutcomes(step.config_json.outcomes)
  const actions = normalizeActions(step.config_json.actions)

  const updateMessages = (nextMessages: MessageConfig[]) => {
    replaceConfig({
      ...step.config_json,
      messages: nextMessages,
      text: nextMessages[0]?.text ?? '',
      buttons: nextMessages[0]?.buttons ?? [],
    })
  }

  return sectionShell(
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
          value={isUniversalBlock ? step.block_type : '__legacy__'}
          onChange={(event) => {
            if (event.target.value === '__legacy__') {
              return
            }
            const item = universalBlocks.find((candidate) => candidate.blockType === event.target.value)
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
          {!isUniversalBlock ? <option value="__legacy__">{getBlockLabel(step.block_type)} · legacy</option> : null}
          {universalBlocks.map((item) => (
            <option key={item.blockType} value={item.blockType}>
              {item.label}
            </option>
          ))}
        </select>
      </label>

      {step.block_type === 'generic_trigger' ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Триггер</span>
          <select
            value={textValue(step.config_json, 'trigger_type') || 'new_chat'}
            onChange={(event) => patchConfig({ trigger_type: event.target.value })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          >
            <option value="new_chat">Новый чат</option>
            <option value="start_command">/start</option>
            <option value="start_with_ref_code">/start с ref-кодом</option>
            <option value="manual_operator_start">Ручной запуск</option>
          </select>
        </label>
      ) : null}

      {step.block_type === 'generic_message' ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-500">Сообщения внутри блока</span>
            <button
              type="button"
              onClick={() =>
                updateMessages([
                  ...messages,
                  { id: id('msg'), type: 'text', text: '', delay_seconds: 0, buttons: [] },
                ])
              }
              className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
            >
              <Plus size={13} />
              Добавить сообщение
            </button>
          </div>
          {messages.map((message, index) => (
            <div key={message.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-gray-300">Сообщение {index + 1}</span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    disabled={index === 0}
                    onClick={() => {
                      const next = [...messages]
                      const [item] = next.splice(index, 1)
                      next.splice(index - 1, 0, item)
                      updateMessages(next)
                    }}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                    title="Вверх"
                  >
                    <ArrowUp size={13} />
                  </button>
                  <button
                    type="button"
                    disabled={index === messages.length - 1}
                    onClick={() => {
                      const next = [...messages]
                      const [item] = next.splice(index, 1)
                      next.splice(index + 1, 0, item)
                      updateMessages(next)
                    }}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                    title="Вниз"
                  >
                    <ArrowDown size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => updateMessages(messages.filter((_, idx) => idx !== index))}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
                    title="Удалить"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
              <textarea
                rows={4}
                value={message.text}
                onChange={(event) =>
                  updateMessages(messages.map((item, idx) => (idx === index ? { ...item, text: event.target.value } : item)))
                }
                placeholder="Текст сообщения"
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
              <label className="mt-2 block">
                <span className="mb-1 block text-xs text-gray-500">Задержка перед сообщением, сек</span>
                <input
                  type="number"
                  min={0}
                  value={message.delay_seconds}
                  onChange={(event) =>
                    updateMessages(
                      messages.map((item, idx) =>
                        idx === index ? { ...item, delay_seconds: Number(event.target.value) || 0 } : item,
                      ),
                    )
                  }
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              </label>
              <div className="mt-3">
                <ButtonListEditor
                  buttons={message.buttons}
                  currentStepId={step.id}
                  steps={steps}
                  onChange={(buttons) =>
                    updateMessages(messages.map((item, idx) => (idx === index ? { ...item, buttons } : item)))
                  }
                />
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {step.step_type === 'message' && step.block_type !== 'generic_message' ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Текст сообщения</span>
          <textarea
            rows={4}
            value={textValue(step.config_json, 'text') || textValue(step.config_json, 'message_text')}
            onChange={(event) => patchConfig({ text: event.target.value })}
            className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>
      ) : null}

      {step.block_type === 'generic_input' ? (
        <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm text-gray-200">
            <input
              type="checkbox"
              checked={boolValue(step.config_json, 'wait_for_answer', true)}
              onChange={(event) => patchConfig({ wait_for_answer: event.target.checked })}
            />
            Ждать ответ пользователя
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Текст вопроса</span>
            <textarea
              rows={3}
              value={textValue(step.config_json, 'prompt') || textValue(step.config_json, 'question_text') || textValue(step.config_json, 'text')}
              onChange={(event) => patchConfig({ prompt: event.target.value })}
              className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Тип ответа</span>
              <select
                value={textValue(step.config_json, 'answer_type') || 'text'}
                onChange={(event) =>
                  patchConfig({
                    answer_type: event.target.value,
                    validation: { type: event.target.value },
                  })
                }
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                {answerTypes.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Сохранить в поле</span>
              <select
                value={textValue(step.config_json, 'save_to')}
                onChange={(event) => patchConfig({ save_to: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                {leadFields.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Max retries</span>
              <input
                type="number"
                min={0}
                value={numberValue(step.config_json, 'max_retries', 2)}
                onChange={(event) => patchConfig({ max_retries: Number(event.target.value) || 0 })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Timeout, сек</span>
              <input
                type="number"
                min={0}
                value={numberValue(step.config_json, 'timeout_seconds', 0)}
                onChange={(event) => patchConfig({ timeout_seconds: Number(event.target.value) || 0 })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Сообщение при ошибке</span>
            <input
              value={textValue(step.config_json, 'retry_message')}
              onChange={(event) => patchConfig({ retry_message: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Ветка по таймауту</span>
            <TargetSelect
              value={textValue(step.config_json, 'timeout_target_step_id')}
              currentStepId={step.id}
              steps={steps}
              onChange={(value) => patchConfig({ timeout_target_step_id: value })}
            />
          </label>
          <ButtonListEditor
            buttons={normalizeButtons(step.config_json.choices)}
            currentStepId={step.id}
            steps={steps}
            onChange={(choices) => patchConfig({ choices })}
          />
        </div>
      ) : null}

      {step.step_type === 'input' && step.block_type !== 'generic_input' ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Текст вопроса</span>
          <textarea
            rows={3}
            value={textValue(step.config_json, 'question_text') || textValue(step.config_json, 'text')}
            onChange={(event) => patchConfig({ question_text: event.target.value })}
            className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>
      ) : null}

      {step.block_type === 'generic_condition' ? (
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Режим</span>
            <select
              value={textValue(step.config_json, 'mode') || 'all'}
              onChange={(event) => patchConfig({ mode: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="all">Все условия</option>
              <option value="any">Любое условие</option>
              <option value="simple_yes_no">Да / Нет по последнему ответу</option>
            </select>
          </label>
          {conditions.map((condition, index) => (
            <div key={condition.id} className="rounded-lg border border-white/8 bg-white/[0.03] p-2">
              <div className="grid gap-2">
                <select
                  value={condition.source}
                  onChange={(event) =>
                    patchConfig({
                      conditions: conditions.map((item, idx) => idx === index ? { ...item, source: event.target.value } : item),
                    })
                  }
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  {conditionSources.map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
                <input
                  value={condition.field}
                  onChange={(event) =>
                    patchConfig({
                      conditions: conditions.map((item, idx) => idx === index ? { ...item, field: event.target.value } : item),
                    })
                  }
                  placeholder="Поле"
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
                <select
                  value={condition.operator}
                  onChange={(event) =>
                    patchConfig({
                      conditions: conditions.map((item, idx) => idx === index ? { ...item, operator: event.target.value } : item),
                    })
                  }
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  {conditionOperators.map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
                <div className="flex gap-2">
                  <input
                    value={condition.value}
                    onChange={(event) =>
                      patchConfig({
                        conditions: conditions.map((item, idx) => idx === index ? { ...item, value: event.target.value } : item),
                      })
                    }
                    placeholder="Значение"
                    className="min-w-0 flex-1 rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => patchConfig({ conditions: conditions.filter((_, idx) => idx !== index) })}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={() => patchConfig({ conditions: [...conditions, { id: id('cond'), source: 'last_answer', field: '', operator: 'equals', value: '' }] })}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
          >
            <Plus size={13} />
            Добавить условие
          </button>
          <div className="space-y-2">
            <span className="text-xs text-gray-500">Исходы</span>
            {outcomes.map((outcome, index) => (
              <div key={outcome.id} className="grid gap-2 rounded-lg border border-white/8 bg-white/[0.03] p-2">
                <input
                  value={outcome.label}
                  onChange={(event) =>
                    patchConfig({ outcomes: outcomes.map((item, idx) => idx === index ? { ...item, label: event.target.value } : item) })
                  }
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
                <TargetSelect
                  value={outcome.target_step_id}
                  currentStepId={step.id}
                  steps={steps}
                  onChange={(value) =>
                    patchConfig({ outcomes: outcomes.map((item, idx) => idx === index ? { ...item, target_step_id: value } : item) })
                  }
                />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {step.block_type === 'generic_crm_action' ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-500">Действия</span>
            <button
              type="button"
              onClick={() => patchConfig({ actions: [...actions, { id: id('action'), type: 'set_lead_status', status: 'in_progress' }] })}
              className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
            >
              <Plus size={13} />
              Добавить
            </button>
          </div>
          {actions.map((action, index) => (
            <div key={action.id} className="grid gap-2 rounded-lg border border-white/8 bg-white/[0.03] p-2">
              <select
                value={action.type}
                onChange={(event) => patchConfig({ actions: actions.map((item, idx) => idx === index ? { ...item, type: event.target.value } : item) })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                {actionTypes.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              {action.type.includes('tag') && action.type !== 'clear_tags' ? (
                <input
                  value={action.tag_id ?? ''}
                  onChange={(event) => patchConfig({ actions: actions.map((item, idx) => idx === index ? { ...item, tag_id: event.target.value } : item) })}
                  placeholder="tag_id"
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              ) : null}
              {action.type === 'set_lead_status' ? (
                <input
                  value={action.status ?? ''}
                  onChange={(event) => patchConfig({ actions: actions.map((item, idx) => idx === index ? { ...item, status: event.target.value } : item) })}
                  placeholder="new / in_progress / qualified / lost"
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                />
              ) : null}
              {action.type === 'write_field' ? (
                <div className="grid gap-2">
                  <input
                    value={action.field ?? ''}
                    onChange={(event) => patchConfig({ actions: actions.map((item, idx) => idx === index ? { ...item, field: event.target.value } : item) })}
                    placeholder="field"
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  />
                  <input
                    value={action.value ?? ''}
                    onChange={(event) => patchConfig({ actions: actions.map((item, idx) => idx === index ? { ...item, value: event.target.value } : item) })}
                    placeholder="value"
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  />
                </div>
              ) : null}
              <button
                type="button"
                onClick={() => patchConfig({ actions: actions.filter((_, idx) => idx !== index) })}
                className="inline-flex h-8 items-center justify-center gap-1 rounded-lg border border-red-300/15 text-xs text-red-200"
              >
                <Trash2 size={13} />
                Удалить действие
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {step.block_type === 'generic_delay' ? (
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Тип ожидания</span>
            <select
              value={textValue(step.config_json, 'delay_type') || 'wait'}
              onChange={(event) => patchConfig({ delay_type: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="wait">Ждать и перейти дальше</option>
              <option value="no_reply_timeout">Если нет ответа</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Задержка, сек</span>
            <input
              type="number"
              min={0}
              value={numberValue(step.config_json, 'delay_seconds', 600)}
              onChange={(event) => patchConfig({ delay_seconds: Number(event.target.value) || 0 })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Куда перейти</span>
            <TargetSelect
              value={textValue(step.config_json, 'target_step_id')}
              currentStepId={step.id}
              steps={steps}
              onChange={(value) => patchConfig({ target_step_id: value })}
            />
          </label>
        </div>
      ) : null}

      {step.step_type === 'operator' ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Действие оператора</span>
          <select
            value={textValue(step.config_json, 'operator_action') || 'handoff'}
            onChange={(event) => patchConfig({ operator_action: event.target.value })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          >
            <option value="handoff">Передать оператору</option>
            <option value="notify">Уведомить оператора</option>
            <option value="stop_bot">Остановить бота</option>
          </select>
        </label>
      ) : null}

      {step.step_type === 'integration' ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">URL</span>
          <input
            value={textValue(step.config_json, 'url')}
            onChange={(event) => patchConfig({ url: event.target.value })}
            placeholder="https://example.com/webhook"
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>
      ) : null}

      {step.step_type === 'finish' ? (
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Результат</span>
            <select
              value={textValue(step.config_json, 'result') || 'stop'}
              onChange={(event) => patchConfig({ result: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="stop">Остановить сценарий</option>
              <option value="success">Успешно</option>
              <option value="lost">Lost</option>
              <option value="rejected">Rejected</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-200">
            <input
              type="checkbox"
              checked={boolValue(step.config_json, 'set_lead_status', true)}
              onChange={(event) => patchConfig({ set_lead_status: event.target.checked })}
            />
            Обновить статус лида
          </label>
        </div>
      ) : null}
    </div>,
  )
}

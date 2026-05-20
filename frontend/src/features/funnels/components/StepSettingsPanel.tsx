import { Trash2 } from 'lucide-react'

import { legacyBlockGroups, getBlockLabel, mvpBlockTypes } from '../blockCatalog'
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

function arrayValue(config: Record<string, unknown>, key: string) {
  const value = config[key]
  return Array.isArray(value) ? value : []
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
        <p className="mt-2 text-sm text-gray-500">Выберите блок на полотне.</p>
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
              const item = legacyBlockGroups
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
            {legacyBlockGroups.map((group) => (
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

        {isSupported && step.block_type === 'generic_trigger' ? (
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

        {isSupported && step.block_type === 'generic_message' ? (
          <>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Тип сообщения</span>
              <select
                value={textValue(step.config_json, 'message_type') || 'text'}
                onChange={(event) => patchConfig({ message_type: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                <option value="text">Текст</option>
                <option value="buttons">Текст + кнопки</option>
                <option value="personalized">Персонализированное</option>
                <option value="media">Media placeholder</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Текст сообщения</span>
              <textarea
                rows={4}
                value={textValue(step.config_json, 'text')}
                onChange={(event) => patchConfig({ text: event.target.value })}
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
              <span className="mt-1 block text-xs text-gray-500">
                Переменные: {'{{name}}'}, {'{{phone}}'}, {'{{project}}'}, {'{{bot}}'}
              </span>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Кнопки, по одной в строке</span>
              <textarea
                rows={3}
                value={arrayValue(step.config_json, 'buttons').map(String).join('\n')}
                onChange={(event) =>
                  patchConfig({
                    buttons: event.target.value
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          </>
        ) : null}

        {isSupported && step.step_type === 'message' && step.block_type !== 'generic_message' ? (
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

        {isSupported && step.block_type === 'generic_input' ? (
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
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Тип ответа</span>
                <select
                  value={textValue(step.config_json, 'answer_type') || 'text'}
                  onChange={(event) => patchConfig({ answer_type: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  <option value="text">Текст</option>
                  <option value="phone">Телефон</option>
                  <option value="number">Число</option>
                  <option value="choice">Выбор</option>
                  <option value="date">Дата</option>
                  <option value="time">Время</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs text-gray-500">Сохранить в поле</span>
                <select
                  value={textValue(step.config_json, 'save_to')}
                  onChange={(event) => patchConfig({ save_to: event.target.value })}
                  className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                >
                  <option value="">Не сохранять</option>
                  <option value="name">Имя</option>
                  <option value="phone">Телефон</option>
                  <option value="age">Возраст</option>
                  <option value="country">Страна</option>
                  <option value="call_time_text">Время созвона</option>
                  <option value="has_card">Есть карта</option>
                  <option value="experience">Опыт</option>
                </select>
              </label>
            </div>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Варианты выбора, по одному в строке</span>
              <textarea
                rows={3}
                value={arrayValue(step.config_json, 'choices').map(String).join('\n')}
                onChange={(event) =>
                  patchConfig({
                    choices: event.target.value
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          </>
        ) : null}

        {isSupported && step.step_type === 'input' && step.block_type !== 'generic_input' ? (
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

        {isSupported && step.block_type === 'generic_condition' ? (
          <>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Режим</span>
              <select
                value={textValue(step.config_json, 'mode') || 'all'}
                onChange={(event) => patchConfig({ mode: event.target.value })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              >
                <option value="all">Все условия</option>
                <option value="any">Любое условие</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">
                Условия: type | field | operator | value
              </span>
              <textarea
                rows={4}
                value={arrayValue(step.config_json, 'conditions')
                  .map((item) => {
                    if (typeof item !== 'object' || item === null) {
                      return ''
                    }
                    const condition = item as Record<string, unknown>
                    return [
                      condition.type,
                      condition.field,
                      condition.operator,
                      condition.value,
                    ].map((part) => String(part ?? '')).join(' | ')
                  })
                  .join('\n')}
                onChange={(event) =>
                  patchConfig({
                    conditions: event.target.value
                      .split('\n')
                      .map((line) => line.split('|').map((part) => part.trim()))
                      .filter((parts) => parts.some(Boolean))
                      .map(([type, field, operator, value]) => ({
                        type: type || 'text_contains',
                        field: field || 'last_answer',
                        operator: operator || 'contains',
                        value: value || '',
                      })),
                  })
                }
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Исходы, по одному в строке</span>
              <textarea
                rows={3}
                value={arrayValue(step.config_json, 'outcomes').map(String).join('\n')}
                onChange={(event) =>
                  patchConfig({
                    outcomes: event.target.value
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
                className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>
          </>
        ) : null}

        {isSupported && step.step_type === 'condition' && step.block_type !== 'generic_condition' ? (
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

        {isSupported && step.block_type === 'generic_crm_action' ? (
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">
              Действия, по одному type на строке
            </span>
            <textarea
              rows={4}
              value={arrayValue(step.config_json, 'actions')
                .map((item) =>
                  typeof item === 'object' && item !== null
                    ? String((item as Record<string, unknown>).type ?? '')
                    : '',
                )
                .join('\n')}
              onChange={(event) =>
                patchConfig({
                  actions: event.target.value
                    .split('\n')
                    .map((item) => item.trim())
                    .filter(Boolean)
                    .map((type) => ({ type, config: {} })),
                })
              }
              className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
        ) : null}

        {isSupported && step.step_type === 'action' && step.block_type !== 'generic_crm_action' ? (
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
                step.block_type === 'generic_delay'
                  ? numberValue(step.config_json, 'minutes', 10)
                  : step.block_type === 'wait_hours'
                    ? numberValue(step.config_json, 'delay_hours', 1)
                    : numberValue(step.config_json, 'delay_minutes', 10)
              }
              onChange={(event) =>
                patchConfig({
                  [step.block_type === 'generic_delay'
                    ? 'minutes'
                    : step.block_type === 'wait_hours'
                      ? 'delay_hours'
                      : 'delay_minutes']:
                    Number(event.target.value) || 1,
                })
              }
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            />
          </label>
        ) : null}

        {isSupported && step.step_type === 'operator' ? (
          <label className="block">
            <span className="mb-1 block text-xs text-gray-500">Действие оператора</span>
            <select
              value={textValue(step.config_json, 'operator_action') || 'handoff_to_operator'}
              onChange={(event) => patchConfig({ operator_action: event.target.value })}
              className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
            >
              <option value="handoff_to_operator">Передать оператору</option>
              <option value="assign_specific_operator">Назначить конкретного</option>
              <option value="assign_random_operator">Назначить случайного</option>
              <option value="stop_bot_for_operator">Остановить бота</option>
              <option value="return_to_bot">Вернуть в бота</option>
            </select>
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

        {isSupported && step.step_type === 'finish' ? (
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
        ) : null}
      </div>
    </section>
  )
}

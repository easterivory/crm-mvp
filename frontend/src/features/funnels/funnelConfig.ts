import type { FunnelEdge, FunnelStep } from './types'

export type ButtonConfig = {
  id: string
  label: string
  value: string
  type: 'branch' | 'url'
  target_step_id?: string
  url?: string
}

export type MessageConfig = {
  id: string
  type: string
  text: string
  delay_seconds: number
  buttons: ButtonConfig[]
}

export type ConditionRuleConfig = {
  id: string
  source: string
  field: string
  operator: string
  value: string
}

export type OutcomeConfig = {
  id: string
  label: string
  target_step_id?: string
}

export type AbTestVariantConfig = {
  id: string
  label: string
  weight: number
  target_step_id?: string
}

export type ActionConfig = {
  id: string
  type: string
  tag_id?: string
  status?: string
  field?: string
  value?: string
  operator_id?: string
  partner_integration_id?: string
  note?: string
}

export type ConfiguredOutput = {
  key: string
  label: string
  targetStepId?: string
}

export const answerTypes = [
  ['text', 'Текст'],
  ['phone', 'Телефон'],
  ['number', 'Число'],
  ['choice', 'Выбор'],
  ['date', 'Дата'],
  ['time', 'Время'],
] as const

export const leadFields = [
  ['', 'Не сохранять'],
  ['name', 'Имя'],
  ['phone', 'Телефон'],
  ['username', 'Username'],
  ['age', 'Возраст'],
  ['country', 'Страна'],
  ['call_time_text', 'Время созвона'],
  ['has_card', 'Есть карта'],
  ['experience', 'Опыт'],
] as const

export const conditionSources = [
  ['last_answer', 'Ответ пользователя'],
  ['lead_field', 'Поле лида'],
  ['tag', 'Тег'],
  ['status', 'Статус'],
  ['tracking_link', 'Tracking link'],
  ['hold_mode', 'Hold включён'],
  ['operator_assigned', 'Назначен менеджер'],
] as const

export const conditionOperators = [
  ['equals', 'равно'],
  ['not_equals', 'не равно'],
  ['contains', 'содержит'],
  ['exists', 'заполнено'],
  ['empty', 'пусто'],
  ['gt', 'больше'],
  ['lt', 'меньше'],
] as const

export const actionTypes = [
  ['add_tag', 'Добавить тег'],
  ['remove_tag', 'Удалить тег'],
  ['clear_tags', 'Очистить теги'],
  ['set_lead_status', 'Изменить статус'],
  ['write_field', 'Записать поле'],
  ['assign_operator', 'Назначить оператора'],
  ['add_note', 'Добавить заметку'],
  ['submit_to_partner', 'Отправить в partner CRM'],
] as const

export function textValue(config: Record<string, unknown>, key: string) {
  const value = config[key]
  return typeof value === 'string' ? value : ''
}

export function boolValue(config: Record<string, unknown>, key: string, fallback: boolean) {
  const value = config[key]
  return typeof value === 'boolean' ? value : fallback
}

export function numberValue(config: Record<string, unknown>, key: string, fallback: number) {
  const value = config[key]
  return typeof value === 'number' ? value : fallback
}

export function configId(prefix: string) {
  return `${prefix}_${crypto.randomUUID().slice(0, 8)}`
}

export function normalizeButton(raw: unknown, index: number): ButtonConfig {
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

export function normalizeButtons(raw: unknown): ButtonConfig[] {
  return Array.isArray(raw) ? raw.map(normalizeButton) : []
}

export function normalizeMessages(config: Record<string, unknown>): MessageConfig[] {
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

export function normalizeConditions(raw: unknown): ConditionRuleConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [{ id: configId('cond'), source: 'last_answer', field: '', operator: 'equals', value: '' }]
  }
  return raw.map((item, index) => {
    const condition = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(condition.id ?? `cond_${index + 1}`),
      source: String(condition.source ?? 'last_answer'),
      field: String(condition.field ?? ''),
      operator: String(condition.operator ?? condition.type ?? 'equals'),
      value: String(condition.value ?? ''),
    }
  })
}

export function normalizeOutcomes(raw: unknown): OutcomeConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [
      { id: 'true', label: 'Да', target_step_id: '' },
      { id: 'false', label: 'Нет', target_step_id: '' },
      { id: 'fallback', label: 'Fallback', target_step_id: '' },
    ]
  }
  return raw.map((item, index) => {
    if (typeof item === 'string') {
      return { id: item, label: item, target_step_id: '' }
    }
    const outcome = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(outcome.id ?? `outcome_${index + 1}`),
      label: String(outcome.label ?? outcome.id ?? `Исход ${index + 1}`),
      target_step_id: typeof outcome.target_step_id === 'string' ? outcome.target_step_id : '',
    }
  })
}

export function normalizeAbVariants(raw: unknown): AbTestVariantConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [
      { id: 'a', label: 'Вариант A', weight: 50, target_step_id: '' },
      { id: 'b', label: 'Вариант B', weight: 50, target_step_id: '' },
    ]
  }
  return raw.map((item, index) => {
    const variant = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(variant.id ?? `variant_${index + 1}`),
      label: String(variant.label ?? variant.name ?? `Вариант ${index + 1}`),
      weight: typeof variant.weight === 'number' ? Math.max(0, variant.weight) : 50,
      target_step_id: typeof variant.target_step_id === 'string' ? variant.target_step_id : '',
    }
  })
}

export function normalizeActions(raw: unknown): ActionConfig[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return [{ id: configId('action'), type: 'set_lead_status', status: 'in_progress' }]
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
      partner_integration_id:
        typeof action.partner_integration_id === 'string' ? action.partner_integration_id : '',
      note: typeof action.note === 'string' ? action.note : '',
    }
  })
}

export function collectConfiguredOutputs(step: FunnelStep): ConfiguredOutput[] {
  if (step.step_type === 'finish') {
    return []
  }

  if (step.step_type === 'condition') {
    if (step.block_type === 'generic_ab_test') {
      return normalizeAbVariants(step.config_json.variants).map((variant) => ({
        key: `ab:${variant.id}`,
        label: `${variant.label} · ${variant.weight}%`,
        targetStepId: variant.target_step_id,
      }))
    }

    return normalizeOutcomes(step.config_json.outcomes).map((outcome) => ({
      key: `condition:${outcome.id}`,
      label: outcome.label,
      targetStepId: outcome.target_step_id,
    }))
  }

  if (step.step_type === 'input') {
    const choices = normalizeButtons(step.config_json.choices ?? step.config_json.options ?? step.config_json.buttons)
    const outputs = choices.map((choice) => ({
      key: `choice:${choice.id}`,
      label: choice.label,
      targetStepId: choice.target_step_id,
    }))
    if (numberValue(step.config_json, 'timeout_seconds', 0) > 0 || textValue(step.config_json, 'timeout_target_step_id')) {
      outputs.push({
        key: 'input:timeout',
        label: 'Таймаут',
        targetStepId: textValue(step.config_json, 'timeout_target_step_id'),
      })
    }
    outputs.push({ key: 'input:answer', label: 'Ответ', targetStepId: undefined })
    return outputs
  }

  if (step.step_type === 'message') {
    const outputs = normalizeMessages(step.config_json).flatMap((message) =>
      message.buttons
        .filter((button) => button.type === 'branch')
        .map((button) => ({
          key: `message:${message.id}:button:${button.id}`,
          label: button.label,
          targetStepId: button.target_step_id,
        })),
    )
    return outputs.length > 0 ? outputs : [{ key: 'message:next', label: 'Далее' }]
  }

  if (step.step_type === 'delay') {
    return [
      {
        key: 'delay:target',
        label: textValue(step.config_json, 'delay_type') === 'no_reply_timeout' ? 'Нет ответа' : 'Далее',
        targetStepId: textValue(step.config_json, 'target_step_id'),
      },
    ]
  }

  return [{ key: `${step.step_type}:next`, label: 'Далее' }]
}

export function collectManagedEdges(step: FunnelStep): Array<{
  sourceKey: string
  label: string
  targetStepId: string
}> {
  return collectConfiguredOutputs(step)
    .filter((output) => output.targetStepId)
    .map((output) => ({
      sourceKey: output.key,
      label: output.label,
      targetStepId: output.targetStepId as string,
    }))
}

export function syncManagedEdgesForStep(edges: FunnelEdge[], step: FunnelStep): FunnelEdge[] {
  const desired = collectManagedEdges(step)
  const desiredKeys = new Set(desired.map((item) => item.sourceKey))
  let nextEdges = edges.filter((edge) => {
    const sourceKey = edge.condition_json?.source_key
    return (
      edge.from_step_id !== step.id ||
      edge.condition_json?.managed !== true ||
      typeof sourceKey !== 'string' ||
      desiredKeys.has(sourceKey)
    )
  })

  for (const output of desired) {
    const existingIndex = nextEdges.findIndex(
      (edge) =>
        edge.from_step_id === step.id &&
        (edge.condition_json?.source_key === output.sourceKey ||
          (typeof edge.condition_json?.source_key !== 'string' &&
            edgeLabel(edge) === output.label)),
    )
    const condition_json = {
      source_key: output.sourceKey,
      outcome: output.label,
      label: output.label,
      managed: true,
    }
    if (existingIndex >= 0) {
      nextEdges = nextEdges.map((edge, index) =>
        index === existingIndex
          ? { ...edge, to_step_id: output.targetStepId, condition_json }
          : edge,
      )
    } else if (output.targetStepId !== step.id) {
      nextEdges = [
        ...nextEdges,
        {
          id: crypto.randomUUID(),
          from_step_id: step.id,
          to_step_id: output.targetStepId,
          condition_json,
          priority: 0,
        },
      ]
    }
  }
  return nextEdges
}

export function edgeLabel(edge: FunnelEdge) {
  const raw = edge.condition_json?.label ?? edge.condition_json?.outcome
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null
}

export function edgeSourceKey(edge: FunnelEdge, sourceStep?: FunnelStep | null) {
  const rawSourceKey = edge.condition_json?.source_key ?? edge.condition_json?.sourceKey
  if (typeof rawSourceKey === 'string' && rawSourceKey.trim()) {
    return rawSourceKey.trim()
  }

  if (!sourceStep) {
    return null
  }

  const outputs = collectConfiguredOutputs(sourceStep)
  const label = edgeLabel(edge)
  if (label) {
    const matches = outputs.filter((output) => output.label === label)
    if (matches.length === 1) {
      return matches[0].key
    }
  }

  if (!label && outputs.length === 1) {
    return outputs[0].key
  }

  return null
}

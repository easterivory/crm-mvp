import type { FunnelEdge, FunnelGraph, FunnelStep } from './types'

export type ButtonConfig = {
  id: string
  label: string
  value: string
  type: 'branch' | 'url' | 'contact'
  target_step_id?: string
  url?: string
}

export type FunnelMessageMediaType = 'photo' | 'video' | 'voice' | 'video_note' | 'document'

export type MessageMediaConfig = {
  source: 'upload' | 'telegram_file_id'
  upload_id?: string
  telegram_file_id?: string
  file_name?: string
  mime_type?: string
  file_size?: number
  media_type?: FunnelMessageMediaType
}

export type MessageConfig = {
  id: string
  type: string
  text: string
  caption?: string
  delay_seconds: number
  wait_for_answer?: boolean
  buttons: ButtonConfig[]
  media?: MessageMediaConfig
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
  event_name?: string
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
  ['send_fb_event', 'Facebook CAPI event'],
] as const

export function orderedFunnelSteps(steps: FunnelStep[]) {
  return [...steps].sort(
    (left, right) =>
      left.position_y - right.position_y ||
      left.position_x - right.position_x ||
      left.id.localeCompare(right.id),
  )
}

export function funnelStepNumberMap(steps: FunnelStep[]) {
  return new Map(
    orderedFunnelSteps(steps).map((step, index) => [step.id, index + 1]),
  )
}

export function funnelStepLabel(
  step: FunnelStep,
  numberById: Map<string, number>,
) {
  const number = numberById.get(step.id)
  return number ? `#${number} · ${step.title}` : step.title
}

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

function normalizeMessageMedia(raw: Record<string, unknown>): MessageMediaConfig | undefined {
  const nested = typeof raw.media === 'object' && raw.media !== null
    ? raw.media as Record<string, unknown>
    : {}
  const uploadId = String(raw.upload_id ?? nested.upload_id ?? '').trim()
  const telegramFileId = String(
    raw.telegram_file_id
      ?? raw.file_id
      ?? raw.media_file_id
      ?? nested.telegram_file_id
      ?? nested.file_id
      ?? nested.media_file_id
      ?? '',
  ).trim()
  if (!uploadId && !telegramFileId) {
    return undefined
  }
  const rawType = String(raw.media_type ?? nested.media_type ?? raw.type ?? 'document')
  const mediaType: FunnelMessageMediaType =
    rawType === 'photo' ||
    rawType === 'video' ||
    rawType === 'voice' ||
    rawType === 'video_note' ||
    rawType === 'document'
      ? rawType
      : 'document'
  const rawFileSize = raw.file_size ?? nested.file_size
  return {
    source: uploadId ? 'upload' : 'telegram_file_id',
    ...(uploadId ? { upload_id: uploadId } : {}),
    ...(telegramFileId ? { telegram_file_id: telegramFileId } : {}),
    file_name: String(raw.file_name ?? nested.file_name ?? '').trim() || undefined,
    mime_type: String(raw.mime_type ?? nested.mime_type ?? '').trim() || undefined,
    file_size: typeof rawFileSize === 'number' ? rawFileSize : undefined,
    media_type: mediaType,
  }
}

export function normalizeMessages(config: Record<string, unknown>): MessageConfig[] {
  const rawMessages = config.messages
  if (Array.isArray(rawMessages) && rawMessages.length > 0) {
    return rawMessages.map((raw, index) => {
      const item = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {}
      const media = normalizeMessageMedia(item)
      const type = String(item.type ?? item.media_type ?? media?.media_type ?? 'text')
      const text = String(item.text ?? item.message ?? item.message_text ?? item.caption ?? '')
      return {
        id: String(item.id ?? `msg_${index + 1}`),
        type,
        text,
        caption: typeof item.caption === 'string' ? item.caption : undefined,
        delay_seconds: typeof item.delay_seconds === 'number' ? item.delay_seconds : 0,
        wait_for_answer:
          typeof item.wait_for_answer === 'boolean'
            ? item.wait_for_answer
            : item.waitForAnswer === true,
        buttons: normalizeButtons(item.buttons),
        ...(media ? { media } : {}),
      }
    })
  }
  const legacyMedia = normalizeMessageMedia(config)
  const legacyType = String(config.message_type ?? config.type ?? legacyMedia?.media_type ?? 'text')
  const legacyText = textValue(config, 'text') || textValue(config, 'message') || textValue(config, 'message_text')
  return [
    {
      id: 'msg_1',
      type: legacyType,
      text: legacyText,
      caption: textValue(config, 'caption') || undefined,
      delay_seconds: numberValue(config, 'delay_seconds', 0),
      wait_for_answer: boolValue(config, 'wait_for_answer', false),
      buttons: normalizeButtons(config.buttons),
      ...(legacyMedia ? { media: legacyMedia } : {}),
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
  const normalizeWeights = (variants: AbTestVariantConfig[]): AbTestVariantConfig[] => {
    const clamped = variants.map((variant) => ({
      ...variant,
      weight: Math.max(0, Math.round(Number.isFinite(variant.weight) ? variant.weight : 0)),
    }))
    const total = clamped.reduce((sum, variant) => sum + variant.weight, 0)
    if (total === 100) {
      return clamped
    }
    if (total <= 0) {
      const base = Math.floor(100 / clamped.length)
      let remainder = 100 - base * clamped.length
      return clamped.map((variant) => {
        const weight = base + (remainder > 0 ? 1 : 0)
        remainder -= 1
        return { ...variant, weight }
      })
    }
    let remaining = 100
    const scaled = clamped.map((variant, index) => {
      if (index === clamped.length - 1) {
        return { ...variant, weight: remaining }
      }
      const weight = Math.max(0, Math.round((variant.weight / total) * 100))
      remaining -= weight
      return { ...variant, weight }
    })
    if (remaining < 0) {
      const last = scaled[scaled.length - 1]
      scaled[scaled.length - 1] = { ...last, weight: Math.max(0, last.weight + remaining) }
    }
    const adjustedTotal = scaled.reduce((sum, variant) => sum + variant.weight, 0)
    if (adjustedTotal !== 100 && scaled.length > 0) {
      const last = scaled[scaled.length - 1]
      scaled[scaled.length - 1] = { ...last, weight: Math.max(0, last.weight + 100 - adjustedTotal) }
    }
    return scaled
  }

  if (!Array.isArray(raw) || raw.length === 0) {
    return [
      { id: 'a', label: 'Вариант A', weight: 50, target_step_id: '' },
      { id: 'b', label: 'Вариант B', weight: 50, target_step_id: '' },
    ]
  }
  return normalizeWeights(raw.map((item, index) => {
    const variant = typeof item === 'object' && item !== null ? (item as Record<string, unknown>) : {}
    return {
      id: String(variant.id ?? `variant_${index + 1}`),
      label: String(variant.label ?? variant.name ?? `Вариант ${index + 1}`),
      weight: typeof variant.weight === 'number' ? Math.max(0, variant.weight) : 50,
      target_step_id: typeof variant.target_step_id === 'string' ? variant.target_step_id : '',
    }
  }))
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
      event_name: typeof action.event_name === 'string'
        ? action.event_name
        : typeof action.fb_event_name === 'string'
          ? action.fb_event_name
          : 'Lead',
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
    const messages = normalizeMessages(step.config_json)
    const outputs = messages.flatMap((message) =>
      message.buttons
        .filter((button) => button.type === 'branch')
        .map((button) => ({
          key: `message:${message.id}:button:${button.id}`,
          label: button.label,
          targetStepId: button.target_step_id,
        })),
    )
    return outputs.length > 0
      ? outputs
      : [{ key: 'message:next', label: messages.some((message) => message.wait_for_answer) ? 'После ответа' : 'Далее' }]
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

function sanitizeTarget(value: unknown, stepIds: Set<string>): unknown {
  return typeof value === 'string' && value && !stepIds.has(value) ? '' : value
}

function sanitizeTargetList(value: unknown, stepIds: Set<string>): unknown {
  if (!Array.isArray(value)) {
    return value
  }
  return value.map((item) => {
    if (!item || typeof item !== 'object') {
      return item
    }
    const record = item as Record<string, unknown>
    return {
      ...record,
      target_step_id: sanitizeTarget(record.target_step_id, stepIds),
    }
  })
}

function sanitizeStepTargets(step: FunnelStep, stepIds: Set<string>): FunnelStep {
  const config = { ...step.config_json }
  for (const key of ['target_step_id', 'timeout_target_step_id', 'fallback_target_step_id']) {
    config[key] = sanitizeTarget(config[key], stepIds)
  }
  for (const key of ['buttons', 'choices', 'outcomes', 'variants']) {
    config[key] = sanitizeTargetList(config[key], stepIds)
  }
  if (Array.isArray(config.messages)) {
    config.messages = config.messages.map((message) => {
      if (!message || typeof message !== 'object') {
        return message
      }
      const record = message as Record<string, unknown>
      return {
        ...record,
        buttons: sanitizeTargetList(record.buttons, stepIds),
      }
    })
  }
  return { ...step, config_json: config }
}

export function sanitizeGraphReferences(graph: FunnelGraph): FunnelGraph {
  const stepIds = new Set(graph.steps.map((step) => step.id))
  return {
    steps: graph.steps.map((step) => sanitizeStepTargets(step, stepIds)),
    edges: graph.edges.filter(
      (edge) => stepIds.has(edge.from_step_id) && stepIds.has(edge.to_step_id),
    ),
    push_rules: graph.push_rules
      .filter((rule) => stepIds.has(rule.step_id))
      .map((rule) => {
        if (!rule.target_step_id || stepIds.has(rule.target_step_id)) {
          return rule
        }
        const actionAfterSend = rule.action_after_send === 'move_to_step'
          ? 'stay'
          : rule.action_after_send
        return {
          ...rule,
          target_step_id: null,
          action_after_send: actionAfterSend,
        }
      }),
    field_mappings: graph.field_mappings.filter((mapping) => stepIds.has(mapping.step_id)),
  }
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

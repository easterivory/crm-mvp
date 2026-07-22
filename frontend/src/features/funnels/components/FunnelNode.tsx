import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import {
  Bell,
  CheckCircle2,
  Clock,
  GitBranch,
  Handshake,
  HelpCircle,
  MessageSquare,
  MousePointer2,
  Plug,
  Trash2,
  Workflow,
} from 'lucide-react'

import { getBlockLabel, mvpBlockTypes } from '../blockCatalog'
import {
  collectConfiguredOutputs,
  conditionOperators,
  conditionSources,
  normalizeActions,
  normalizeConditions,
  normalizeMessages,
  numberValue,
  textValue,
} from '../funnelConfig'
import type { FunnelStep } from '../types'
import UnsupportedBlockCard from './UnsupportedBlockCard'

export type FunnelNodeData = {
  step: FunnelStep
  stepNumber?: number
  onDelete?: (stepId: string) => void
} & Record<string, unknown>

export type FunnelFlowNode = Node<FunnelNodeData, 'funnelStep'>

export const TARGET_HANDLE_ID = 'in'
export const DEFAULT_SOURCE_HANDLE_ID = 'next'

export function sourceHandleId(sourceKey: string | null) {
  const normalized = sourceKey?.trim()
  return normalized ? `out:${normalized}` : DEFAULT_SOURCE_HANDLE_ID
}

export function outcomeFromSourceHandle(handleId: string | null) {
  if (!handleId || handleId === DEFAULT_SOURCE_HANDLE_ID) {
    return null
  }
  return handleId.startsWith('out:') ? handleId.slice(4) : handleId
}

const iconByType = {
  trigger: MousePointer2,
  message: MessageSquare,
  input: HelpCircle,
  condition: GitBranch,
  action: Workflow,
  delay: Clock,
  operator: Handshake,
  integration: Plug,
  finish: CheckCircle2,
}

const headerByType = {
  trigger: 'from-cyan-500/25 to-cyan-500/5 text-cyan-50',
  message: 'from-violet-500/25 to-violet-500/5 text-violet-50',
  input: 'from-emerald-500/25 to-emerald-500/5 text-emerald-50',
  condition: 'from-amber-500/25 to-amber-500/5 text-amber-50',
  action: 'from-sky-500/25 to-sky-500/5 text-sky-50',
  delay: 'from-orange-500/25 to-orange-500/5 text-orange-50',
  operator: 'from-pink-500/25 to-pink-500/5 text-pink-50',
  integration: 'from-slate-500/25 to-slate-500/5 text-slate-50',
  finish: 'from-green-500/25 to-green-500/5 text-green-50',
}

function previewLines(step: FunnelStep) {
  if (step.step_type === 'trigger') {
    const triggerType = textValue(step.config_json, 'trigger_type') || 'new_chat'
    if (triggerType === 'custom_command') {
      const command = textValue(step.config_json, 'command').replace(/^\//, '')
      const description = textValue(step.config_json, 'command_description')
      return [`/${command || 'command'}`, ...(description ? [description] : [])]
    }
    if (triggerType === 'start_command') return ['/start']
    if (triggerType === 'start_with_ref_code') return ['/start с ref-кодом']
    if (triggerType === 'manual_operator_start') return ['Ручной запуск']
    return ['Новый чат']
  }

  if (step.step_type === 'message') {
    const messages = normalizeMessages(step.config_json)
    const lines = messages
      .slice(0, 2)
      .map((message) => message.text.trim())
      .filter(Boolean)
    if (messages.length > 2) {
      lines.push(`${messages.length} сообщения`)
    }
    return lines.length > 0 ? lines : ['Пустое сообщение']
  }

  if (step.step_type === 'input') {
    const prompt =
      textValue(step.config_json, 'prompt') ||
      textValue(step.config_json, 'question_text') ||
      textValue(step.config_json, 'text') ||
      'Вопрос без текста'
    const saveTo =
      textValue(step.config_json, 'custom_field_key') ||
      textValue(step.config_json, 'save_to')
    return saveTo ? [prompt, `Сохранить: ${saveTo}`] : [prompt]
  }

  if (step.step_type === 'condition') {
    const mode = textValue(step.config_json, 'mode') || 'all'
    const conditions = normalizeConditions(step.config_json.conditions)
    const first = conditions[0]
    const source = conditionSources.find(([value]) => value === first?.source)?.[1] ?? 'Условие'
    const operator = conditionOperators.find(([value]) => value === first?.operator)?.[1] ?? ''
    if (conditions.length > 1) {
      return [`${conditions.length} условия · ${mode.toUpperCase()}`]
    }
    return [`Если ${source} ${operator} ${first?.value ?? ''}`.trim()]
  }

  if (step.step_type === 'delay') {
    const seconds = numberValue(step.config_json, 'delay_seconds', 0)
    if (seconds >= 3600) return [`Ждать ${Math.round(seconds / 3600)} ч`]
    if (seconds >= 60) return [`Ждать ${Math.round(seconds / 60)} мин`]
    return [`Ждать ${seconds} сек`]
  }

  if (step.step_type === 'action') {
    if (step.block_type === 'set_lead_status') {
      return [`Статус: ${textValue(step.config_json, 'status') || '...'}`]
    }
    const actions = normalizeActions(step.config_json.actions)
    return actions.slice(0, 2).map((action) => {
      if (action.type === 'set_lead_status') return `Статус: ${action.status || '...'}` 
      if (action.type === 'add_tag') return 'Добавить тег'
      if (action.type === 'write_field') return `Поле: ${action.field || '...'}`
      if (action.type === 'send_fb_event') {
        return `FB: ${action.source_event || action.event_name || 'Lead'}`
      }
      return action.type
    })
  }

  if (step.step_type === 'finish') {
    return [`Результат: ${textValue(step.config_json, 'result') || 'stop'}`]
  }

  return [getBlockLabel(step.block_type)]
}

export default function FunnelNode({ data, selected, isConnectable }: NodeProps<FunnelFlowNode>) {
  const { step, stepNumber, onDelete } = data
  const Icon = iconByType[step.step_type] ?? Bell
  const isSupported = mvpBlockTypes.has(step.block_type)
  const outputs = collectConfiguredOutputs(step)
  const headerClass = headerByType[step.step_type] ?? headerByType.integration
  const lines = previewLines(step)

  return (
    <div
      className={`group relative w-[270px] select-none overflow-hidden rounded-xl border bg-[#111827]/96 shadow-card transition ${
        selected ? 'border-accent-300/70 ring-2 ring-accent-300/20' : 'border-white/10'
      }`}
    >
      <Handle
        id={TARGET_HANDLE_ID}
        type="target"
        position={Position.Left}
        isConnectable={isConnectable}
        className="!h-4 !w-4 !border !border-white/30 !bg-background !shadow-card"
      />
      {outputs.length > 0 ? (
        <Handle
          id={DEFAULT_SOURCE_HANDLE_ID}
          type="source"
          position={Position.Right}
          isConnectable={false}
          className="!right-[-14px] !h-3.5 !w-3.5 !border-0 !bg-transparent !opacity-0"
          style={{ top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
        />
      ) : null}

      <div className={`flex items-start gap-3 bg-gradient-to-r ${headerClass} px-3 py-3`}>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-current/25 bg-black/15">
          <Icon size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-white">
            {stepNumber ? `#${stepNumber} · ` : ''}
            {step.title}
          </p>
          <p className="truncate text-xs text-gray-400">{getBlockLabel(step.block_type)}</p>
        </div>
        {onDelete ? (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onDelete(step.id)
            }}
            className={`hidden h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-red-300/20 text-red-200 transition hover:border-red-300/40 ${selected ? 'flex' : 'group-hover:flex'}`}
            title="Удалить блок"
          >
            <Trash2 size={14} />
          </button>
        ) : null}
      </div>

      <div className="space-y-2 px-3 py-3">
        {!isSupported ? <UnsupportedBlockCard blockType={step.block_type} /> : null}
        {lines.map((line, index) => (
          <p key={`${line}:${index}`} className="truncate text-xs leading-5 text-gray-400">
            {line}
          </p>
        ))}

        {outputs.length > 0 ? (
          <div className="mt-2 grid gap-1.5">
            {outputs.map((output) => (
              <div
                key={output.key}
                className="relative flex min-h-7 items-center justify-end gap-2 rounded-md border border-accent-300/15 bg-accent-300/5 px-2 text-[11px] text-accent-50"
              >
                <span className="max-w-[176px] truncate">{output.label}</span>
                <Handle
                  id={sourceHandleId(output.key)}
                  type="source"
                  position={Position.Right}
                  isConnectable={isConnectable}
                  title={`Потянуть связь: ${output.label}`}
                  className="!right-[-14px] !h-3.5 !w-3.5 !border !border-accent-200 !bg-accent-300"
                />
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

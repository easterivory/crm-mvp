import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import {
  Bell,
  CheckCircle2,
  Clock,
  GitBranch,
  Handshake,
  MessageSquare,
  MousePointer2,
  Plug,
  Send,
  Workflow,
} from 'lucide-react'

import { getBlockLabel, mvpBlockTypes } from '../blockCatalog'
import type { FunnelStep } from '../types'
import UnsupportedBlockCard from './UnsupportedBlockCard'

export type StepNodeData = {
  step: FunnelStep
} & Record<string, unknown>

export type StepFlowNode = Node<StepNodeData, 'funnelStep'>

export const TARGET_HANDLE_ID = 'in'
export const DEFAULT_SOURCE_HANDLE_ID = 'next'

export function sourceHandleId(label: string | null) {
  const normalized = label?.trim()
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
  input: Send,
  condition: GitBranch,
  action: Workflow,
  delay: Clock,
  operator: Handshake,
  integration: Plug,
  finish: CheckCircle2,
}

const toneByType = {
  trigger: 'border-cyan-300/30 bg-cyan-300/10 text-cyan-50',
  message: 'border-violet-300/30 bg-violet-300/10 text-violet-50',
  input: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-50',
  condition: 'border-amber-300/30 bg-amber-300/10 text-amber-50',
  action: 'border-sky-300/30 bg-sky-300/10 text-sky-50',
  delay: 'border-orange-300/30 bg-orange-300/10 text-orange-50',
  operator: 'border-pink-300/30 bg-pink-300/10 text-pink-50',
  integration: 'border-slate-300/30 bg-slate-300/10 text-slate-50',
  finish: 'border-green-300/30 bg-green-300/10 text-green-50',
}

function getOutputLabels(step: FunnelStep) {
  if (step.step_type === 'condition') {
    const outcomes = step.config_json.outcomes
    if (Array.isArray(outcomes) && outcomes.length > 0) {
      return outcomes.map(String)
    }
    return ['true', 'false', 'fallback']
  }
  if (step.step_type === 'input') {
    const choices = step.config_json.choices ?? step.config_json.options ?? step.config_json.buttons
    if (Array.isArray(choices) && choices.length > 0) {
      return choices.slice(0, 4).map(String)
    }
  }
  if (step.step_type === 'finish') {
    return []
  }
  return ['Далее']
}

export default function StepNode({ data, selected, isConnectable }: NodeProps<StepFlowNode>) {
  const { step } = data
  const Icon = iconByType[step.step_type] ?? Bell
  const isSupported = mvpBlockTypes.has(step.block_type)
  const outputs = getOutputLabels(step)

  return (
    <div
      className={`relative w-[250px] select-none rounded-lg border bg-[#111827]/95 p-3 shadow-card transition ${
        selected ? 'border-accent-300/60 ring-2 ring-accent-300/20' : 'border-white/10'
      }`}
    >
      <Handle
        id={TARGET_HANDLE_ID}
        type="target"
        position={Position.Left}
        isConnectable={isConnectable}
        className="!h-4 !w-4 !border !border-white/30 !bg-background !shadow-card"
      />

      <div className="flex items-start gap-3">
        <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${toneByType[step.step_type]}`}>
          <Icon size={17} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-white">{step.title}</p>
          <p className="truncate text-xs text-gray-500">{getBlockLabel(step.block_type)}</p>
        </div>
      </div>

      {!isSupported ? (
        <div className="mt-3">
          <UnsupportedBlockCard blockType={step.block_type} />
        </div>
      ) : null}

      {outputs.length > 0 ? (
        <div className="mt-3 grid gap-1.5">
          {outputs.map((label) => (
            <div
              key={label}
              className="relative flex min-h-7 items-center justify-end gap-2 rounded-md border border-accent-300/15 bg-accent-300/5 px-2 text-[11px] text-accent-50"
            >
              <span className="max-w-[170px] truncate">{label}</span>
              <Handle
                id={sourceHandleId(label)}
                type="source"
                position={Position.Right}
                isConnectable={isConnectable}
                title={`Потянуть связь: ${label}`}
                className="!right-[-14px] !h-3.5 !w-3.5 !border !border-accent-200 !bg-accent-300"
              />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

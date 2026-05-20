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
import { PointerEvent } from 'react'

import { getBlockLabel, mvpBlockTypes } from '../blockCatalog'
import type { FunnelStep } from '../types'
import UnsupportedBlockCard from './UnsupportedBlockCard'

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

type StepNodeProps = {
  step: FunnelStep
  isSelected: boolean
  onSelect: (stepId: string) => void
  onPointerDown: (event: PointerEvent<HTMLDivElement>, stepId: string) => void
  onStartConnect: (
    stepId: string,
    outcome: string | null,
    event: PointerEvent<HTMLButtonElement>,
  ) => void
  onFinishConnect: (stepId: string, event: PointerEvent<HTMLButtonElement>) => void
}

function getOutputLabels(step: FunnelStep) {
  if (step.step_type === 'condition') {
    const outcomes = step.config_json.outcomes
    if (Array.isArray(outcomes) && outcomes.length > 0) {
      return outcomes.map(String)
    }
    return ['true', 'false']
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

export default function StepNode({
  step,
  isSelected,
  onSelect,
  onPointerDown,
  onStartConnect,
  onFinishConnect,
}: StepNodeProps) {
  const Icon = iconByType[step.step_type] ?? Bell
  const isSupported = mvpBlockTypes.has(step.block_type)
  const outputs = getOutputLabels(step)

  return (
    <div
      style={{ left: step.position_x, top: step.position_y, width: 250 }}
      className={`absolute select-none rounded-lg border bg-[#111827]/95 p-3 shadow-card transition ${
        isSelected ? 'border-accent-300/60 ring-2 ring-accent-300/20' : 'border-white/10'
      }`}
      onPointerDown={(event) => onPointerDown(event, step.id)}
      onClick={() => onSelect(step.id)}
    >
      <button
        type="button"
        aria-label="Вход блока"
        className="absolute -left-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border border-white/30 bg-background shadow-card transition hover:border-accent-300"
        onPointerDown={(event) => event.stopPropagation()}
        onPointerUp={(event) => onFinishConnect(step.id, event)}
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
        <div className="mt-3 flex flex-wrap justify-end gap-1.5">
          {outputs.map((label) => (
            <button
              key={label}
              type="button"
              title={`Потянуть связь: ${label}`}
              onPointerDown={(event) => onStartConnect(step.id, label, event)}
              className="inline-flex items-center gap-1 rounded-full border border-accent-300/25 bg-accent-300/10 px-2 py-1 text-[11px] text-accent-50 transition hover:border-accent-300/50"
            >
              <span className="max-w-[92px] truncate">{label}</span>
              <span className="h-2 w-2 rounded-full bg-accent-300" />
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

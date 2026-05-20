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
  isConnecting: boolean
  canConnectHere: boolean
  onSelect: (stepId: string) => void
  onPointerDown: (event: PointerEvent<HTMLDivElement>, stepId: string) => void
  onStartConnect: (stepId: string) => void
  onFinishConnect: (stepId: string) => void
}

export default function StepNode({
  step,
  isSelected,
  isConnecting,
  canConnectHere,
  onSelect,
  onPointerDown,
  onStartConnect,
  onFinishConnect,
}: StepNodeProps) {
  const Icon = iconByType[step.step_type] ?? Bell
  const isSupported = mvpBlockTypes.has(step.block_type)

  return (
    <div
      style={{ left: step.position_x, top: step.position_y, width: 230 }}
      className={`absolute select-none rounded-lg border bg-[#111827]/95 p-3 shadow-card transition ${
        isSelected ? 'border-accent-300/60 ring-2 ring-accent-300/20' : 'border-white/10'
      }`}
      onPointerDown={(event) => onPointerDown(event, step.id)}
      onClick={() => onSelect(step.id)}
    >
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

      <div className="mt-3 flex justify-end">
        {isConnecting ? (
          <button
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onFinishConnect(step.id)
            }}
            disabled={!canConnectHere}
            className="rounded-lg border border-accent-300/25 bg-accent-300/10 px-2 py-1 text-xs text-accent-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Сюда
          </button>
        ) : (
          <button
            type="button"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation()
              onStartConnect(step.id)
            }}
            className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-xs text-gray-300 transition hover:border-accent-300/30"
          >
            Связать
          </button>
        )}
      </div>
    </div>
  )
}

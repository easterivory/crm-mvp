import { MouseEvent, PointerEvent, useMemo, useRef, useState } from 'react'

import type { FunnelEdge, FunnelStep } from '../types'
import StepNode from './StepNode'

type FunnelCanvasProps = {
  steps: FunnelStep[]
  edges: FunnelEdge[]
  selectedStepId: string | null
  connectingFromId: string | null
  onSelectStep: (stepId: string | null) => void
  onMoveStep: (stepId: string, position: { x: number; y: number }) => void
  onStartConnect: (stepId: string) => void
  onFinishConnect: (stepId: string) => void
}

const NODE_WIDTH = 230
const NODE_HEIGHT = 118
const CANVAS_WIDTH = 1600
const CANVAS_HEIGHT = 900

export default function FunnelCanvas({
  steps,
  edges,
  selectedStepId,
  connectingFromId,
  onSelectStep,
  onMoveStep,
  onStartConnect,
  onFinishConnect,
}: FunnelCanvasProps) {
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const [drag, setDrag] = useState<{
    stepId: string
    offsetX: number
    offsetY: number
  } | null>(null)

  const stepById = useMemo(() => new Map(steps.map((step) => [step.id, step])), [steps])

  const edgeLines = useMemo(() => {
    return edges
      .map((edge) => {
        const from = stepById.get(edge.from_step_id)
        const to = stepById.get(edge.to_step_id)
        if (!from || !to) {
          return null
        }
        const startX = from.position_x + NODE_WIDTH
        const startY = from.position_y + NODE_HEIGHT / 2
        const endX = to.position_x
        const endY = to.position_y + NODE_HEIGHT / 2
        const midX = startX + Math.max(80, (endX - startX) / 2)
        return {
          id: edge.id,
          path: `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`,
        }
      })
      .filter(Boolean)
  }, [edges, stepById])

  const getPoint = (event: PointerEvent<HTMLDivElement> | MouseEvent<HTMLDivElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) {
      return { x: 0, y: 0 }
    }
    return {
      x: event.clientX - rect.left + (canvasRef.current?.scrollLeft ?? 0),
      y: event.clientY - rect.top + (canvasRef.current?.scrollTop ?? 0),
    }
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>, stepId: string) => {
    const step = stepById.get(stepId)
    if (!step) {
      return
    }
    const point = getPoint(event)
    setDrag({
      stepId,
      offsetX: point.x - step.position_x,
      offsetY: point.y - step.position_y,
    })
    onSelectStep(stepId)
    canvasRef.current?.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag) {
      return
    }
    const point = getPoint(event)
    onMoveStep(drag.stepId, {
      x: Math.max(24, Math.min(CANVAS_WIDTH - NODE_WIDTH - 24, point.x - drag.offsetX)),
      y: Math.max(24, Math.min(CANVAS_HEIGHT - NODE_HEIGHT - 24, point.y - drag.offsetY)),
    })
  }

  return (
    <div className="h-full min-h-[520px] overflow-auto rounded-lg border border-white/8 bg-[#0b1020]">
      <div
        ref={canvasRef}
        className="relative"
        style={{ width: CANVAS_WIDTH, height: CANVAS_HEIGHT }}
        onPointerMove={handlePointerMove}
        onPointerUp={() => setDrag(null)}
        onPointerCancel={() => setDrag(null)}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) {
            onSelectStep(null)
          }
        }}
      >
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[size:32px_32px]" />
        <svg className="pointer-events-none absolute inset-0 h-full w-full">
          <defs>
            <marker id="funnel-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
              <path d="M 0 0 L 8 4 L 0 8 z" fill="rgba(34,211,238,0.85)" />
            </marker>
          </defs>
          {edgeLines.map((edge) =>
            edge ? (
              <path
                key={edge.id}
                d={edge.path}
                fill="none"
                stroke="rgba(34,211,238,0.7)"
                strokeWidth="2"
                markerEnd="url(#funnel-arrow)"
              />
            ) : null,
          )}
        </svg>
        {steps.map((step) => (
          <StepNode
            key={step.id}
            step={step}
            isSelected={selectedStepId === step.id}
            isConnecting={Boolean(connectingFromId)}
            canConnectHere={Boolean(connectingFromId && connectingFromId !== step.id)}
            onSelect={onSelectStep}
            onPointerDown={handlePointerDown}
            onStartConnect={onStartConnect}
            onFinishConnect={onFinishConnect}
          />
        ))}
      </div>
    </div>
  )
}

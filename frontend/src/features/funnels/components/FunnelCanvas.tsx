import { Maximize2, Minus, Plus } from 'lucide-react'
import { MouseEvent, PointerEvent, useMemo, useRef, useState } from 'react'

import type { FunnelEdge, FunnelStep } from '../types'
import StepNode from './StepNode'

type FunnelCanvasProps = {
  steps: FunnelStep[]
  edges: FunnelEdge[]
  selectedStepId: string | null
  selectedEdgeId: string | null
  onSelectStep: (stepId: string | null) => void
  onSelectEdge: (edgeId: string | null) => void
  onMoveStep: (stepId: string, position: { x: number; y: number }) => void
  onConnect: (fromStepId: string, toStepId: string, outcome: string | null) => void
}

const NODE_WIDTH = 250
const NODE_HEIGHT = 132
const CANVAS_WIDTH = 3600
const CANVAS_HEIGHT = 2200

export default function FunnelCanvas({
  steps,
  edges,
  selectedStepId,
  selectedEdgeId,
  onSelectStep,
  onSelectEdge,
  onMoveStep,
  onConnect,
}: FunnelCanvasProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const [viewport, setViewport] = useState({ x: 80, y: 80, zoom: 0.9 })
  const [drag, setDrag] = useState<{
    stepId: string
    offsetX: number
    offsetY: number
  } | null>(null)
  const [pan, setPan] = useState<{ x: number; y: number; startX: number; startY: number } | null>(
    null,
  )
  const [connect, setConnect] = useState<{
    fromStepId: string
    outcome: string | null
    x: number
    y: number
  } | null>(null)

  const stepById = useMemo(() => new Map(steps.map((step) => [step.id, step])), [steps])

  const toWorld = (event: PointerEvent | MouseEvent) => {
    const rect = viewportRef.current?.getBoundingClientRect()
    if (!rect) {
      return { x: 0, y: 0 }
    }
    return {
      x: (event.clientX - rect.left - viewport.x) / viewport.zoom,
      y: (event.clientY - rect.top - viewport.y) / viewport.zoom,
    }
  }

  const edgeLines = useMemo(() => {
    return edges
      .map((edge) => {
        const from = stepById.get(edge.from_step_id)
        const to = stepById.get(edge.to_step_id)
        if (!from || !to) {
          return null
        }
        const label = String(edge.condition_json?.label ?? edge.condition_json?.outcome ?? '')
        const startX = from.position_x + NODE_WIDTH
        const startY = from.position_y + NODE_HEIGHT / 2
        const endX = to.position_x
        const endY = to.position_y + NODE_HEIGHT / 2
        const midX = startX + Math.max(100, (endX - startX) / 2)
        return {
          id: edge.id,
          label,
          labelX: (startX + endX) / 2,
          labelY: (startY + endY) / 2 - 12,
          path: `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`,
        }
      })
      .filter(Boolean)
  }, [edges, stepById])

  const handleNodePointerDown = (event: PointerEvent<HTMLDivElement>, stepId: string) => {
    if ((event.target as HTMLElement).closest('button')) {
      return
    }
    const step = stepById.get(stepId)
    if (!step) {
      return
    }
    const point = toWorld(event)
    setDrag({
      stepId,
      offsetX: point.x - step.position_x,
      offsetY: point.y - step.position_y,
    })
    onSelectStep(stepId)
    onSelectEdge(null)
    viewportRef.current?.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (drag) {
      const point = toWorld(event)
      onMoveStep(drag.stepId, {
        x: Math.max(24, Math.min(CANVAS_WIDTH - NODE_WIDTH - 24, point.x - drag.offsetX)),
        y: Math.max(24, Math.min(CANVAS_HEIGHT - NODE_HEIGHT - 24, point.y - drag.offsetY)),
      })
      return
    }
    if (pan) {
      setViewport((current) => ({
        ...current,
        x: pan.x + event.clientX - pan.startX,
        y: pan.y + event.clientY - pan.startY,
      }))
      return
    }
    if (connect) {
      const point = toWorld(event)
      setConnect({ ...connect, x: point.x, y: point.y })
    }
  }

  const clearPointerState = () => {
    setDrag(null)
    setPan(null)
    setConnect(null)
  }

  const zoomBy = (delta: number) => {
    setViewport((current) => ({
      ...current,
      zoom: Math.max(0.35, Math.min(1.6, Number((current.zoom + delta).toFixed(2)))),
    }))
  }

  const fitView = () => {
    setViewport({ x: 80, y: 80, zoom: 0.9 })
  }

  return (
    <div className="relative h-full min-h-[620px] overflow-hidden rounded-lg border border-white/8 bg-[#0b1020]">
      <div className="absolute left-3 top-3 z-20 flex items-center gap-1 rounded-lg border border-white/10 bg-background/80 p-1 shadow-card backdrop-blur">
        <button
          type="button"
          onClick={() => zoomBy(-0.1)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-300 hover:bg-white/10"
          title="Уменьшить"
        >
          <Minus size={15} />
        </button>
        <span className="w-12 text-center text-xs text-gray-400">
          {Math.round(viewport.zoom * 100)}%
        </span>
        <button
          type="button"
          onClick={() => zoomBy(0.1)}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-300 hover:bg-white/10"
          title="Увеличить"
        >
          <Plus size={15} />
        </button>
        <button
          type="button"
          onClick={fitView}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-300 hover:bg-white/10"
          title="Показать начало"
        >
          <Maximize2 size={15} />
        </button>
      </div>

      <div
        ref={viewportRef}
        className="h-full w-full cursor-grab overflow-hidden active:cursor-grabbing"
        onPointerMove={handlePointerMove}
        onPointerUp={clearPointerState}
        onPointerCancel={clearPointerState}
        onPointerDown={(event) => {
          if (event.target !== event.currentTarget) {
            return
          }
          onSelectStep(null)
          onSelectEdge(null)
          setPan({ x: viewport.x, y: viewport.y, startX: event.clientX, startY: event.clientY })
          viewportRef.current?.setPointerCapture(event.pointerId)
        }}
      >
        <div
          className="relative origin-top-left"
          style={{
            width: CANVAS_WIDTH,
            height: CANVAS_HEIGHT,
            transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
          }}
        >
          <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.04)_1px,transparent_1px)] bg-[size:40px_40px]" />
          <svg className="absolute inset-0 h-full w-full">
            <defs>
              <marker id="funnel-arrow" markerHeight="8" markerWidth="8" orient="auto" refX="7" refY="4">
                <path d="M 0 0 L 8 4 L 0 8 z" fill="rgba(34,211,238,0.9)" />
              </marker>
            </defs>
            {edgeLines.map((edge) =>
              edge ? (
                <g key={edge.id}>
                  <path
                    d={edge.path}
                    fill="none"
                    stroke={
                      selectedEdgeId === edge.id
                        ? 'rgba(167,139,250,0.95)'
                        : 'rgba(34,211,238,0.7)'
                    }
                    strokeWidth={selectedEdgeId === edge.id ? 3 : 2}
                    markerEnd="url(#funnel-arrow)"
                    className="cursor-pointer"
                    onClick={(event) => {
                      event.stopPropagation()
                      onSelectEdge(edge.id)
                      onSelectStep(null)
                    }}
                  />
                  {edge.label ? (
                    <text
                      x={edge.labelX}
                      y={edge.labelY}
                      textAnchor="middle"
                      className="pointer-events-none fill-gray-300 text-[11px]"
                    >
                      {edge.label}
                    </text>
                  ) : null}
                </g>
              ) : null,
            )}
            {connect ? (() => {
              const from = stepById.get(connect.fromStepId)
              if (!from) {
                return null
              }
              return (
                <path
                  d={`M ${from.position_x + NODE_WIDTH} ${from.position_y + NODE_HEIGHT / 2} L ${connect.x} ${connect.y}`}
                  fill="none"
                  stroke="rgba(167,139,250,0.85)"
                  strokeDasharray="6 6"
                  strokeWidth="2"
                />
              )
            })() : null}
          </svg>
          {steps.map((step) => (
            <StepNode
              key={step.id}
              step={step}
              isSelected={selectedStepId === step.id}
              onSelect={(stepId) => {
                onSelectStep(stepId)
                onSelectEdge(null)
              }}
              onPointerDown={handleNodePointerDown}
              onStartConnect={(stepId, outcome, event) => {
                event.stopPropagation()
                const point = toWorld(event)
                setConnect({ fromStepId: stepId, outcome, x: point.x, y: point.y })
              }}
              onFinishConnect={(stepId, event) => {
                event.stopPropagation()
                if (connect && connect.fromStepId !== stepId) {
                  onConnect(connect.fromStepId, stepId, connect.outcome)
                }
                setConnect(null)
              }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

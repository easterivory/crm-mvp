import '@xyflow/react/dist/style.css'

import {
  Background,
  BackgroundVariant,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { edgeLabel, edgeSourceKey } from '../funnelConfig'
import type { FunnelEdge, FunnelStep } from '../types'
import FunnelNode, {
  TARGET_HANDLE_ID,
  outcomeFromSourceHandle,
  sourceHandleId,
  type FunnelFlowNode,
} from './FunnelNode'

type FunnelCanvasProps = {
  steps: FunnelStep[]
  edges: FunnelEdge[]
  selectedStepId: string | null
  selectedEdgeId: string | null
  onSelectStep: (stepId: string | null) => void
  onSelectEdge: (edgeId: string | null) => void
  onMoveStep: (stepId: string, position: { x: number; y: number }) => void
  onConnect: (fromStepId: string, toStepId: string, sourceKey: string | null) => void
  onDeleteStep: (stepId: string) => void
  readOnly?: boolean
}

type FlowEdge = Edge<Record<string, unknown>, 'smoothstep'>

const nodeTypes = {
  funnelStep: FunnelNode,
} satisfies NodeTypes

function FunnelCanvasInner({
  steps,
  edges,
  selectedStepId,
  selectedEdgeId,
  onSelectStep,
  onSelectEdge,
  onMoveStep,
  onConnect,
  onDeleteStep,
  readOnly = false,
}: FunnelCanvasProps) {
  const { fitView, zoomIn, zoomOut } = useReactFlow()
  const [zoom, setZoom] = useState(1)

  const flowNodes = useMemo<FunnelFlowNode[]>(
    () =>
      steps.map((step) => ({
        id: step.id,
        type: 'funnelStep',
        position: { x: step.position_x, y: step.position_y },
        data: { step, onDelete: readOnly ? undefined : onDeleteStep },
        selected: selectedStepId === step.id,
        draggable: !readOnly,
      })),
    [onDeleteStep, readOnly, selectedStepId, steps],
  )

  const flowEdges = useMemo<FlowEdge[]>(
    () =>
      edges.map((edge) => {
        const outcome = edgeLabel(edge)
        const sourceStep = steps.find((step) => step.id === edge.from_step_id)
        return {
          id: edge.id,
          type: 'smoothstep',
          source: edge.from_step_id,
          target: edge.to_step_id,
          sourceHandle: sourceHandleId(edgeSourceKey(edge, sourceStep)),
          targetHandle: TARGET_HANDLE_ID,
          label: outcome ?? undefined,
          selected: selectedEdgeId === edge.id,
          markerEnd: { type: MarkerType.ArrowClosed, color: '#22d3ee' },
          style: {
            stroke: selectedEdgeId === edge.id ? '#a78bfa' : '#22d3ee',
            strokeWidth: selectedEdgeId === edge.id ? 3 : 2,
          },
          labelStyle: { fill: '#d1d5db', fontSize: 11, fontWeight: 600 },
          labelBgStyle: { fill: '#0b1020', fillOpacity: 0.86 },
          labelBgPadding: [6, 3],
          labelBgBorderRadius: 6,
        }
      }),
    [edges, selectedEdgeId, steps],
  )

  const graphKey = useMemo(() => steps.map((step) => step.id).join('|'), [steps])

  const fitCanvas = useCallback(() => {
    void fitView({
      padding: 0.28,
      includeHiddenNodes: false,
      minZoom: 0.68,
      maxZoom: 1.05,
      duration: 280,
    })
  }, [fitView])

  useEffect(() => {
    if (steps.length === 0) {
      return undefined
    }
    const timer = window.setTimeout(fitCanvas, 80)
    return () => window.clearTimeout(timer)
  }, [fitCanvas, graphKey, steps.length])

  const handleNodesChange = useCallback(
    (changes: NodeChange<FunnelFlowNode>[]) => {
      for (const change of changes) {
        if (change.type === 'position' && change.position) {
          if (!readOnly) {
            onMoveStep(change.id, change.position)
          }
        }
        if (change.type === 'select' && change.selected) {
          onSelectStep(change.id)
          onSelectEdge(null)
        }
      }
    },
    [onMoveStep, onSelectEdge, onSelectStep, readOnly],
  )

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) {
        return
      }
      if (!readOnly) {
        onConnect(
          connection.source,
          connection.target,
          outcomeFromSourceHandle(connection.sourceHandle),
        )
      }
    },
    [onConnect, readOnly],
  )

  return (
    <div className="relative h-[min(68dvh,720px)] min-h-[430px] overflow-hidden rounded-xl border border-white/8 bg-[#0b1020] lg:h-full lg:min-h-[620px] lg:rounded-none lg:border-0">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        onNodesChange={handleNodesChange}
        onConnect={handleConnect}
        onNodeClick={(_, node) => {
          onSelectStep(node.id)
          onSelectEdge(null)
        }}
        onEdgeClick={(_, edge) => {
          onSelectEdge(edge.id)
          onSelectStep(null)
        }}
        onPaneClick={() => {
          onSelectStep(null)
          onSelectEdge(null)
        }}
        onSelectionChange={({ nodes, edges: selectedEdges }) => {
          const node = nodes[0]
          const edge = selectedEdges[0]
          onSelectStep(node?.id ?? null)
          onSelectEdge(edge?.id ?? null)
        }}
        onMove={(_, viewport) => setZoom(viewport.zoom)}
        connectionRadius={28}
        deleteKeyCode={null}
        fitView
        fitViewOptions={{
          padding: 0.28,
          includeHiddenNodes: false,
          minZoom: 0.68,
          maxZoom: 1.05,
        }}
        minZoom={0.45}
        maxZoom={1.7}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        edgesFocusable
        edgesReconnectable={false}
        className="funnel-react-flow"
      >
        <Background color="rgba(255,255,255,0.16)" gap={28} variant={BackgroundVariant.Dots} />
      </ReactFlow>
      <div className="pointer-events-none absolute bottom-3 left-3 z-20 flex items-center gap-1 rounded-xl border border-white/10 bg-[#0B0F19]/90 p-1 shadow-card backdrop-blur-xl">
        <button
          type="button"
          onClick={fitCanvas}
          className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-300 transition hover:bg-white/[0.06] hover:text-white"
          title="Показать всю схему"
          aria-label="Показать всю схему"
        >
          <Maximize2 size={16} />
        </button>
        <button
          type="button"
          onClick={() => void zoomOut({ duration: 160 })}
          className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-300 transition hover:bg-white/[0.06] hover:text-white"
          title="Уменьшить"
          aria-label="Уменьшить"
        >
          <Minus size={16} />
        </button>
        <div className="min-w-14 px-2 text-center text-xs font-semibold text-gray-300">
          {Math.round(zoom * 100)}%
        </div>
        <button
          type="button"
          onClick={() => void zoomIn({ duration: 160 })}
          className="pointer-events-auto inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-300 transition hover:bg-white/[0.06] hover:text-white"
          title="Увеличить"
          aria-label="Увеличить"
        >
          <Plus size={16} />
        </button>
      </div>
    </div>
  )
}

export default function FunnelCanvas(props: FunnelCanvasProps) {
  return (
    <ReactFlowProvider>
      <FunnelCanvasInner {...props} />
    </ReactFlowProvider>
  )
}

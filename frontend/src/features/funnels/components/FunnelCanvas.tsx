import '@xyflow/react/dist/style.css'

import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  type Connection,
  type Edge,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react'
import { useCallback, useMemo } from 'react'

import { edgeLabel, edgeSourceKey } from '../funnelConfig'
import type { FunnelEdge, FunnelStep } from '../types'
import FunnelNode, {
  DEFAULT_SOURCE_HANDLE_ID,
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
}: FunnelCanvasProps) {
  const flowNodes = useMemo<FunnelFlowNode[]>(
    () =>
      steps.map((step) => ({
        id: step.id,
        type: 'funnelStep',
        position: { x: step.position_x, y: step.position_y },
        data: { step, onDelete: onDeleteStep },
        selected: selectedStepId === step.id,
        draggable: true,
      })),
    [onDeleteStep, selectedStepId, steps],
  )
  const stepById = useMemo(() => new Map(steps.map((step) => [step.id, step])), [steps])

  const flowEdges = useMemo<FlowEdge[]>(
    () =>
      edges.map((edge) => {
        const outcome = edgeLabel(edge)
        const sourceKey = edgeSourceKey(edge, stepById.get(edge.from_step_id))
        return {
          id: edge.id,
          type: 'smoothstep',
          source: edge.from_step_id,
          target: edge.to_step_id,
          sourceHandle: sourceKey ? sourceHandleId(sourceKey) : DEFAULT_SOURCE_HANDLE_ID,
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
    [edges, selectedEdgeId, stepById],
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange<FunnelFlowNode>[]) => {
      for (const change of changes) {
        if (change.type === 'position' && change.position) {
          onMoveStep(change.id, change.position)
        }
        if (change.type === 'select' && change.selected) {
          onSelectStep(change.id)
          onSelectEdge(null)
        }
      }
    },
    [onMoveStep, onSelectEdge, onSelectStep],
  )

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) {
        return
      }
      onConnect(
        connection.source,
        connection.target,
        outcomeFromSourceHandle(connection.sourceHandle),
      )
    },
    [onConnect],
  )

  return (
    <div className="relative h-full min-h-[620px] overflow-hidden bg-[#0b1020]">
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
        connectionRadius={28}
        deleteKeyCode={null}
        fitView
        fitViewOptions={{ padding: 0.18, includeHiddenNodes: false }}
        minZoom={0.25}
        maxZoom={1.7}
        nodesDraggable
        nodesConnectable
        edgesFocusable
        edgesReconnectable={false}
        className="funnel-react-flow"
      >
        <Background color="rgba(255,255,255,0.16)" gap={28} variant={BackgroundVariant.Dots} />
        <Controls
          showInteractive={false}
          className="!border !border-white/10 !bg-background/80 !shadow-card"
        />
      </ReactFlow>
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

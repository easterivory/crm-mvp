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

import type { FunnelEdge, FunnelStep } from '../types'
import StepNode, {
  DEFAULT_SOURCE_HANDLE_ID,
  TARGET_HANDLE_ID,
  outcomeFromSourceHandle,
  sourceHandleId,
  type StepFlowNode,
} from './StepNode'

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

type FlowEdge = Edge<Record<string, unknown>, 'smoothstep'>

const nodeTypes = {
  funnelStep: StepNode,
} satisfies NodeTypes

function edgeOutcome(edge: FunnelEdge) {
  const raw = edge.condition_json?.outcome ?? edge.condition_json?.label
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null
}

function FunnelCanvasInner({
  steps,
  edges,
  selectedStepId,
  selectedEdgeId,
  onSelectStep,
  onSelectEdge,
  onMoveStep,
  onConnect,
}: FunnelCanvasProps) {
  const flowNodes = useMemo<StepFlowNode[]>(
    () =>
      steps.map((step) => ({
        id: step.id,
        type: 'funnelStep',
        position: { x: step.position_x, y: step.position_y },
        data: { step },
        selected: selectedStepId === step.id,
        draggable: true,
      })),
    [selectedStepId, steps],
  )

  const flowEdges = useMemo<FlowEdge[]>(
    () =>
      edges.map((edge) => {
        const outcome = edgeOutcome(edge)
        return {
          id: edge.id,
          type: 'smoothstep',
          source: edge.from_step_id,
          target: edge.to_step_id,
          sourceHandle: outcome ? sourceHandleId(outcome) : DEFAULT_SOURCE_HANDLE_ID,
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
    [edges, selectedEdgeId],
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange<StepFlowNode>[]) => {
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
    <div className="relative h-full min-h-[680px] overflow-hidden rounded-lg border border-white/8 bg-[#0b1020]">
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
        fitViewOptions={{ padding: 0.24, includeHiddenNodes: false }}
        minZoom={0.25}
        maxZoom={1.7}
        nodesDraggable
        nodesConnectable
        edgesFocusable
        edgesReconnectable={false}
        className="funnel-react-flow"
      >
        <Background color="rgba(255,255,255,0.12)" gap={32} variant={BackgroundVariant.Lines} />
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

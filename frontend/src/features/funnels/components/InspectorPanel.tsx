import { CheckCircle2 } from 'lucide-react'

import type { FunnelEdge, FunnelFieldMapping, FunnelPushRule, FunnelStep } from '../types'
import EdgeSettingsPanel from './EdgeSettingsPanel'
import FieldMappingsPanel from './FieldMappingsPanel'
import PushRulesPanel from './PushRulesPanel'
import StepSettingsPanel from './StepSettingsPanel'

type InspectorPanelProps = {
  selectedStep: FunnelStep | null
  projectId: string
  selectedEdge: FunnelEdge | null
  steps: FunnelStep[]
  edges: FunnelEdge[]
  fieldMappings: FunnelFieldMapping[]
  pushRules: FunnelPushRule[]
  hasPublishedVersion: boolean
  readOnly?: boolean
  onUpdateStep: (stepId: string, patch: Partial<FunnelStep>) => void
  onDeleteStep: (stepId: string) => void
  onUpdateEdge: (edgeId: string, patch: Partial<FunnelEdge>) => void
  onRemoveEdge: (edgeId: string) => void
  onSelectEdge: (edgeId: string) => void
  onFieldMappingsChange: (mappings: FunnelFieldMapping[]) => void
  onPushRulesChange: (rules: FunnelPushRule[]) => void
}

export default function InspectorPanel({
  selectedStep,
  projectId,
  selectedEdge,
  steps,
  edges,
  fieldMappings,
  pushRules,
  hasPublishedVersion,
  readOnly = false,
  onUpdateStep,
  onDeleteStep,
  onUpdateEdge,
  onRemoveEdge,
  onSelectEdge,
  onFieldMappingsChange,
  onPushRulesChange,
}: InspectorPanelProps) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-white/8 bg-[#0d1324]/92 lg:rounded-none lg:border-y-0 lg:border-r-0 lg:border-l">
      <div className="border-b border-white/8 px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Настройки</h2>
        <p className="mt-1 text-xs text-gray-500">
          {readOnly
            ? 'Опубликованная версия открыта только для просмотра.'
            : 'Выбранный блок, связь и служебные действия.'}
        </p>
      </div>

      <div
        className={`min-h-0 flex-1 space-y-3 overflow-y-auto p-3 ${
          readOnly ? 'pointer-events-none opacity-70' : ''
        }`}
      >
        {selectedEdge ? (
          <EdgeSettingsPanel
            selectedEdge={selectedEdge}
            edges={edges}
            steps={steps}
            onUpdate={onUpdateEdge}
            onRemove={onRemoveEdge}
            onSelect={onSelectEdge}
          />
        ) : (
          <>
            <StepSettingsPanel
              step={selectedStep}
              projectId={projectId}
              steps={steps}
              onUpdate={onUpdateStep}
              onDelete={onDeleteStep}
            />
            {selectedStep ? (
              <>
                <FieldMappingsPanel
                  selectedStep={selectedStep}
                  mappings={fieldMappings}
                  onChange={onFieldMappingsChange}
                />
                <PushRulesPanel
                  selectedStep={selectedStep}
                  steps={steps}
                  rules={pushRules}
                  onChange={onPushRulesChange}
                />
              </>
            ) : null}
          </>
        )}

        {hasPublishedVersion ? (
          <div className="flex items-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-500/10 p-3 text-sm text-emerald-50">
            <CheckCircle2 size={15} />
            Есть опубликованная версия
          </div>
        ) : null}
      </div>
    </aside>
  )
}

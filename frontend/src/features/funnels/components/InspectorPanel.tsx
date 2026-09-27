import { CopyPlus, Pin, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { getBlockLabel } from '../blockCatalog'

import type { FunnelEdge, FunnelFieldMapping, FunnelPushRule, FunnelStep } from '../types'
import { funnelStepNumberMap } from '../funnelConfig'
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
  onDuplicateStep: (stepId: string) => void
  onDeleteStep: (stepId: string) => void
  onUpdateEdge: (edgeId: string, patch: Partial<FunnelEdge>) => void
  onRemoveEdge: (edgeId: string) => void
  onSelectEdge: (edgeId: string) => void
  onFieldMappingsChange: (mappings: FunnelFieldMapping[]) => void
  onPushRulesChange: (rules: FunnelPushRule[]) => void
  onClose?: () => void
  onExpand?: (messageId: string) => void
  pinned?: boolean
  onTogglePin?: () => void
}

export default function InspectorPanel({
  selectedStep,
  projectId,
  selectedEdge,
  steps,
  edges,
  fieldMappings,
  pushRules,
  readOnly = false,
  onUpdateStep,
  onDuplicateStep,
  onDeleteStep,
  onUpdateEdge,
  onRemoveEdge,
  onSelectEdge,
  onFieldMappingsChange,
  onPushRulesChange,
  onClose,
  onExpand,
  pinned,
  onTogglePin,
}: InspectorPanelProps) {
  const [tab, setTab] = useState<'main' | 'content' | 'logic' | 'advanced'>('content')
  const stepNumberById = funnelStepNumberMap(steps)
  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-white/8 bg-[#0d1324]/92 lg:rounded-none lg:border-y-0 lg:border-r-0 lg:border-l">
      <div className="border-b border-white/8 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1"><h2 className="truncate text-sm font-semibold text-white">{selectedStep ? `#${stepNumberById.get(selectedStep.id)} · ${selectedStep.title}` : 'Связь'}</h2>
            <p className="text-xs text-gray-500">{selectedStep ? getBlockLabel(selectedStep.block_type) : 'Переход между блоками'}</p></div>
          {selectedStep && <><button disabled={readOnly} title="Дублировать блок" onClick={() => onDuplicateStep(selectedStep.id)}><CopyPlus size={15} /></button><button disabled={readOnly} title="Удалить блок" onClick={() => { if (window.confirm('Удалить блок и его связи?')) onDeleteStep(selectedStep.id) }}><Trash2 size={15} /></button></>}
          <button title="Закрепить инспектор" aria-pressed={pinned} onClick={onTogglePin} className={pinned ? 'text-cyan-300' : 'text-gray-500'}><Pin size={15} /></button>
          <button title="Закрыть инспектор" onClick={onClose}><X size={16} /></button>
        </div>
      </div>
      {!selectedEdge && <div role="tablist" className="grid grid-cols-4 border-b border-white/10">
        {([{ id: 'main', label: 'Основное' }, { id: 'content', label: 'Контент' }, { id: 'logic', label: 'Логика' }, { id: 'advanced', label: 'Дополнительно' }] as const).map((item) => <button key={item.id} role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)} className={`min-w-0 px-1 py-3 text-[11px] ${tab === item.id ? 'border-b-2 border-cyan-300 text-cyan-100' : 'text-gray-500'}`}>{item.label}</button>)}
      </div>}

      <div
        className={`min-h-0 flex-1 space-y-3 overflow-y-auto p-3 ${
          readOnly ? 'opacity-70' : ''
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
          <fieldset disabled={readOnly} className="min-w-0 space-y-4">
            <StepSettingsPanel
              section={tab}
              onExpand={onExpand}
              step={selectedStep}
              stepNumber={
                selectedStep ? stepNumberById.get(selectedStep.id) : undefined
              }
              projectId={projectId}
              steps={steps}
              onUpdate={onUpdateStep}
              onDuplicate={onDuplicateStep}
              onDelete={onDeleteStep}
            />
            {selectedStep && tab === 'advanced' ? (
              <>
                <FieldMappingsPanel
                  selectedStep={selectedStep}
                  mappings={fieldMappings}
                  onChange={onFieldMappingsChange}
                />
                <PushRulesPanel
                  projectId={projectId}
                  selectedStep={selectedStep}
                  steps={steps}
                  rules={pushRules}
                  onChange={onPushRulesChange}
                />
              </>
            ) : null}
          </fieldset>
        )}

      </div>
    </aside>
  )
}

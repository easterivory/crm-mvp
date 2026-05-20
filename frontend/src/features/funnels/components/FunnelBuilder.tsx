import {
  ArrowLeft,
  CheckCircle2,
  LoaderCircle,
  Save,
  Send,
  ShieldAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNotificationStore } from '../../../shared/lib'
import {
  createDraftVersion,
  fetchFunnel,
  fetchGraph,
  saveGraph,
  validateFunnelVersion,
} from '../api'
import type { BlockMenuItem } from '../blockCatalog'
import type { Funnel, FunnelEdge, FunnelGraph, FunnelStep } from '../types'
import AddBlockMenu from './AddBlockMenu'
import EdgeSettingsPanel from './EdgeSettingsPanel'
import FieldMappingsPanel from './FieldMappingsPanel'
import FunnelCanvas from './FunnelCanvas'
import PublishReviewModal from './PublishReviewModal'
import PushRulesPanel from './PushRulesPanel'
import StepSettingsPanel from './StepSettingsPanel'

type FunnelBuilderProps = {
  funnelId: string
  versionId?: string | null
  projectId: string
  onBack: () => void
  onVersionReady: (versionId: string) => void
}

function graphWithDefaults(graph: FunnelGraph): FunnelGraph {
  return {
    steps: graph.steps.map((step) => ({
      ...step,
      config_json: step.config_json ?? {},
      validation_json: step.validation_json ?? null,
      ui_schema_json: step.ui_schema_json ?? null,
    })),
    edges: graph.edges,
    push_rules: graph.push_rules,
    field_mappings: graph.field_mappings,
  }
}

export default function FunnelBuilder({
  funnelId,
  versionId,
  projectId,
  onBack,
  onVersionReady,
}: FunnelBuilderProps) {
  const notify = useNotificationStore((state) => state.notify)
  const [funnel, setFunnel] = useState<Funnel | null>(null)
  const [graph, setGraph] = useState<FunnelGraph | null>(null)
  const [activeVersionId, setActiveVersionId] = useState(versionId ?? null)
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const [connectingFromId, setConnectingFromId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [isPublishOpen, setIsPublishOpen] = useState(false)

  useEffect(() => {
    let isMounted = true
    const load = async () => {
      setIsLoading(true)
      try {
        const loadedFunnel = await fetchFunnel(funnelId, projectId)
        const draftId =
          activeVersionId ?? loadedFunnel.draft_version_id ?? loadedFunnel.published_version_id
        let resolvedVersionId = draftId
        if (!resolvedVersionId) {
          const draft = await createDraftVersion(funnelId, projectId)
          resolvedVersionId = draft.id
        }
        if (!resolvedVersionId) {
          throw new Error('version_not_found')
        }
        const loadedGraph = await fetchGraph(funnelId, resolvedVersionId, projectId)
        if (isMounted) {
          setFunnel(loadedFunnel)
          setActiveVersionId(resolvedVersionId)
          onVersionReady(resolvedVersionId)
          setGraph(graphWithDefaults(loadedGraph))
          setSelectedStepId(loadedGraph.steps[0]?.id ?? null)
        }
      } catch {
        notify({ tone: 'error', message: 'Не удалось загрузить воронку.' })
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }
    void load()
    return () => {
      isMounted = false
    }
  }, [activeVersionId, funnelId, notify, onVersionReady, projectId])

  const selectedStep = useMemo(
    () => graph?.steps.find((step) => step.id === selectedStepId) ?? null,
    [graph?.steps, selectedStepId],
  )

  const updateStep = useCallback((stepId: string, patch: Partial<FunnelStep>) => {
    setGraph((current) =>
      current
        ? {
            ...current,
            steps: current.steps.map((step) =>
              step.id === stepId ? { ...step, ...patch } : step,
            ),
          }
        : current,
    )
  }, [])

  const deleteStep = (stepId: string) => {
    setGraph((current) =>
      current
        ? {
            ...current,
            steps: current.steps.filter((step) => step.id !== stepId),
            edges: current.edges.filter(
              (edge) => edge.from_step_id !== stepId && edge.to_step_id !== stepId,
            ),
            push_rules: current.push_rules.filter((rule) => rule.step_id !== stepId),
            field_mappings: current.field_mappings.filter(
              (mapping) => mapping.step_id !== stepId,
            ),
          }
        : current,
    )
    setSelectedStepId((current) => (current === stepId ? null : current))
  }

  const addBlock = (item: BlockMenuItem) => {
    setGraph((current) => {
      if (!current) {
        return current
      }
      const nextIndex = current.steps.length + 1
      const step: FunnelStep = {
        id: crypto.randomUUID(),
        key: `${item.blockType}_${nextIndex}`,
        title: item.defaultTitle,
        step_type: item.stepType,
        block_type: item.blockType,
        position_x: 120 + (nextIndex % 4) * 280,
        position_y: 120 + Math.floor(nextIndex / 4) * 180,
        config_json: item.defaultConfig ?? {},
        validation_json: null,
        ui_schema_json: null,
      }
      setSelectedStepId(step.id)
      return { ...current, steps: [...current.steps, step] }
    })
  }

  const updateEdge = (edgeId: string, patch: Partial<FunnelEdge>) => {
    setGraph((current) =>
      current
        ? {
            ...current,
            edges: current.edges.map((edge) =>
              edge.id === edgeId ? { ...edge, ...patch } : edge,
            ),
          }
        : current,
    )
  }

  const removeEdge = (edgeId: string) => {
    setGraph((current) =>
      current ? { ...current, edges: current.edges.filter((edge) => edge.id !== edgeId) } : current,
    )
  }

  const finishConnect = (toStepId: string) => {
    if (!connectingFromId || connectingFromId === toStepId) {
      return
    }
    setGraph((current) => {
      if (!current) {
        return current
      }
      const exists = current.edges.some(
        (edge) => edge.from_step_id === connectingFromId && edge.to_step_id === toStepId,
      )
      if (exists) {
        return current
      }
      return {
        ...current,
        edges: [
          ...current.edges,
          {
            id: crypto.randomUUID(),
            from_step_id: connectingFromId,
            to_step_id: toStepId,
            condition_json: null,
            priority: 0,
          },
        ],
      }
    })
    setConnectingFromId(null)
  }

  const saveDraft = async () => {
    if (!graph || !activeVersionId || isSaving) {
      return
    }
    setIsSaving(true)
    try {
      const saved = await saveGraph(funnelId, activeVersionId, projectId, graph)
      setGraph(graphWithDefaults(saved))
      notify({ tone: 'success', message: 'Draft сохранён.' })
    } catch {
      notify({ tone: 'error', message: 'Не удалось сохранить draft.' })
    } finally {
      setIsSaving(false)
    }
  }

  const validate = async () => {
    if (!activeVersionId || isValidating) {
      return
    }
    setIsValidating(true)
    try {
      if (graph) {
        await saveGraph(funnelId, activeVersionId, projectId, graph)
      }
      const result = await validateFunnelVersion(funnelId, activeVersionId, projectId)
      notify({
        tone: result.can_publish ? 'success' : 'warning',
        message: result.can_publish
          ? 'Проверка пройдена.'
          : `Найдены ошибки: ${result.errors.length}.`,
      })
    } catch {
      notify({ tone: 'error', message: 'Не удалось проверить воронку.' })
    } finally {
      setIsValidating(false)
    }
  }

  const openPublish = async () => {
    if (graph && activeVersionId) {
      await saveGraph(funnelId, activeVersionId, projectId, graph)
    }
    setIsPublishOpen(true)
  }

  const handlePublished = () => {
    notify({ tone: 'success', message: 'Воронка опубликована.' })
    setIsPublishOpen(false)
    void fetchFunnel(funnelId, projectId).then(setFunnel)
  }

  if (isLoading || !graph || !funnel || !activeVersionId) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-white/8 bg-surface/90 text-sm text-gray-400">
        <LoaderCircle size={18} className="mr-2 animate-spin" />
        Загрузка конструктора
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 rounded-lg border border-white/8 bg-surface/90 px-4 py-3 shadow-card">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-white/20"
            title="К списку"
          >
            <ArrowLeft size={16} />
          </button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold text-white">{funnel.name}</h1>
            <p className="text-sm text-gray-500">
              Draft version · {graph.steps.length} блоков · {graph.edges.length} связей
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void saveDraft()}
            disabled={isSaving}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />}
            Сохранить
          </button>
          <button
            type="button"
            onClick={() => void validate()}
            disabled={isValidating}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-amber-300/20 bg-amber-300/10 px-3 text-sm text-amber-50 transition hover:border-amber-300/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isValidating ? <LoaderCircle size={15} className="animate-spin" /> : <ShieldAlert size={15} />}
            Проверить
          </button>
          <button
            type="button"
            onClick={() => void openPublish()}
            className="inline-flex h-9 items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-3 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent"
          >
            <Send size={15} />
            Publish review
          </button>
        </div>
      </header>

      <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-sm text-amber-50 md:hidden">
        Редактор воронок удобнее на компьютере.
      </div>

      <div className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[260px_minmax(0,1fr)_330px]">
        <AddBlockMenu onAdd={addBlock} />
        <FunnelCanvas
          steps={graph.steps}
          edges={graph.edges}
          selectedStepId={selectedStepId}
          connectingFromId={connectingFromId}
          onSelectStep={setSelectedStepId}
          onMoveStep={(stepId, position) =>
            updateStep(stepId, { position_x: position.x, position_y: position.y })
          }
          onStartConnect={setConnectingFromId}
          onFinishConnect={finishConnect}
        />
        <div className="min-h-0 space-y-3 overflow-y-auto rounded-lg border border-white/8 bg-surface/90 p-3">
          <StepSettingsPanel step={selectedStep} onUpdate={updateStep} onDelete={deleteStep} />
          <FieldMappingsPanel
            selectedStep={selectedStep}
            mappings={graph.field_mappings}
            onChange={(field_mappings) =>
              setGraph((current) => (current ? { ...current, field_mappings } : current))
            }
          />
          <PushRulesPanel
            selectedStep={selectedStep}
            steps={graph.steps}
            rules={graph.push_rules}
            onChange={(push_rules) =>
              setGraph((current) => (current ? { ...current, push_rules } : current))
            }
          />
          <EdgeSettingsPanel
            edges={graph.edges}
            steps={graph.steps}
            onUpdate={updateEdge}
            onRemove={removeEdge}
          />
          {funnel.published_version_id ? (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-300/20 bg-emerald-500/10 p-3 text-sm text-emerald-50">
              <CheckCircle2 size={15} />
              Есть опубликованная версия
            </div>
          ) : null}
        </div>
      </div>

      {isPublishOpen ? (
        <PublishReviewModal
          funnelId={funnelId}
          versionId={activeVersionId}
          projectId={projectId}
          onClose={() => setIsPublishOpen(false)}
          onPublished={handlePublished}
        />
      ) : null}
    </div>
  )
}

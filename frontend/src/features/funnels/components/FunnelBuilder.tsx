import {
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  CopyPlus,
  LoaderCircle,
  PlayCircle,
  Save,
  Send,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { useNotificationStore } from '../../../shared/lib'
import { client } from '../../../api/client'
import {
  createDraftVersion,
  createDraftFromVersion,
  fetchFunnel,
  fetchGraph,
  fetchVersions,
  saveGraph,
  setBotActiveFunnel,
  validateFunnelVersion,
} from '../api'
import type { BlockMenuItem } from '../blockCatalog'
import {
  normalizeButtons,
  normalizeMessages,
  normalizeOutcomes,
  syncManagedEdgesForStep,
} from '../funnelConfig'
import type { Funnel, FunnelEdge, FunnelGraph, FunnelStep, FunnelVersion } from '../types'
import BlockLibrary from './BlockLibrary'
import DropOffChart from './DropOffChart'
import FunnelCanvas from './FunnelCanvas'
import HoldModeToggle from './HoldModeToggle'
import InspectorPanel from './InspectorPanel'
import PublishReviewModal from './PublishReviewModal'

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

function clearManagedTarget(step: FunnelStep, sourceKey: string): FunnelStep {
  if (step.step_type === 'condition') {
    return {
      ...step,
      config_json: {
        ...step.config_json,
        outcomes: normalizeOutcomes(step.config_json.outcomes).map((outcome) =>
          `condition:${outcome.id}` === sourceKey ? { ...outcome, target_step_id: '' } : outcome,
        ),
      },
    }
  }

  if (step.step_type === 'message') {
    return {
      ...step,
      config_json: {
        ...step.config_json,
        messages: normalizeMessages(step.config_json).map((message) => ({
          ...message,
          buttons: message.buttons.map((button) =>
            `message:${message.id}:button:${button.id}` === sourceKey
              ? { ...button, target_step_id: '' }
              : button,
          ),
        })),
      },
    }
  }

  if (step.step_type === 'input') {
    if (sourceKey === 'input:timeout') {
      return {
        ...step,
        config_json: { ...step.config_json, timeout_target_step_id: '' },
      }
    }
    return {
      ...step,
      config_json: {
        ...step.config_json,
        choices: normalizeButtons(step.config_json.choices).map((choice) =>
          `choice:${choice.id}` === sourceKey ? { ...choice, target_step_id: '' } : choice,
        ),
      },
    }
  }

  if (step.step_type === 'delay' && sourceKey === 'delay:target') {
    return {
      ...step,
      config_json: { ...step.config_json, target_step_id: '' },
    }
  }

  return step
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
  const [versions, setVersions] = useState<FunnelVersion[]>([])
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [isPublishOpen, setIsPublishOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'analytics'>('editor')
  const [analyticsData, setAnalyticsData] = useState<any[]>([])
  const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false)

  const loadAnalytics = useCallback(async () => {
    if (!activeVersionId || isLoadingAnalytics) {
      return
    }
    setIsLoadingAnalytics(true)
    try {
      const response = await client.get(
        `/api/v1/funnels/${funnelId}/versions/${activeVersionId}/analytics/drop-off`,
        { params: { project_id: projectId } },
      )
      setAnalyticsData(response.data)
    } catch {
      notify({ tone: 'error', message: 'Не удалось загрузить аналитику.' })
      setAnalyticsData([])
    } finally {
      setIsLoadingAnalytics(false)
    }
  }, [activeVersionId, funnelId, isLoadingAnalytics, notify, projectId])

  useEffect(() => {
    if (activeTab === 'analytics') {
      void loadAnalytics()
    }
  }, [activeTab, loadAnalytics])

  const loadVersions = async () => {
    try {
      const loadedVersions = await fetchVersions(funnelId, projectId)
      setVersions(loadedVersions)
    } catch {
      notify({ tone: 'error', message: 'Не удалось обновить версии.' })
    }
  }

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
        const loadedVersions = await fetchVersions(funnelId, projectId)
        if (isMounted) {
          setFunnel(loadedFunnel)
          setActiveVersionId(resolvedVersionId)
          setVersions(loadedVersions)
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
  const selectedEdge = useMemo(
    () => graph?.edges.find((edge) => edge.id === selectedEdgeId) ?? null,
    [graph?.edges, selectedEdgeId],
  )
  const selectedVersion = useMemo(
    () => versions.find((version) => version.id === activeVersionId) ?? null,
    [activeVersionId, versions],
  )

  const updateStep = useCallback((stepId: string, patch: Partial<FunnelStep>) => {
    setGraph((current) => {
      if (!current) {
        return current
      }
      const steps = current.steps.map((step) =>
        step.id === stepId ? { ...step, ...patch } : step,
      )
      const changedStep = steps.find((step) => step.id === stepId)
      return {
        ...current,
        steps,
        edges:
          changedStep && patch.config_json
            ? syncManagedEdgesForStep(current.edges, changedStep)
            : current.edges,
      }
    })
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
    setSelectedEdgeId(null)
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

  const removeEdge = useCallback((edgeId: string) => {
    setGraph((current) =>
      current
        ? {
            ...current,
            steps: current.steps.map((step) => {
              const edge = current.edges.find((item) => item.id === edgeId)
              const sourceKey = edge?.condition_json?.source_key
              return edge?.from_step_id === step.id && typeof sourceKey === 'string'
                ? clearManagedTarget(step, sourceKey)
                : step
            }),
            edges: current.edges.filter((edge) => edge.id !== edgeId),
          }
        : current,
    )
    setSelectedEdgeId((current) => (current === edgeId ? null : current))
  }, [])

  const connectSteps = (fromStepId: string, toStepId: string, outcome: string | null) => {
    if (fromStepId === toStepId) {
      return
    }
    setGraph((current) => {
      if (!current) {
        return current
      }
      const exists = current.edges.some((edge) => {
        const edgeOutcome = edge.condition_json?.outcome ?? edge.condition_json?.label ?? null
        return (
          edge.from_step_id === fromStepId &&
          edge.to_step_id === toStepId &&
          (outcome ? edgeOutcome === outcome : !edgeOutcome)
        )
      })
      if (exists) {
        return current
      }
      const syncedSteps = current.steps.map((step) => {
        if (step.id !== fromStepId || !outcome) {
          return step
        }
        if (step.step_type === 'condition' && Array.isArray(step.config_json.outcomes)) {
          return {
            ...step,
            config_json: {
              ...step.config_json,
              outcomes: step.config_json.outcomes.map((item) => {
                if (typeof item !== 'object' || item === null) {
                  return item
                }
                const outcomeConfig = item as Record<string, unknown>
                const label = String(outcomeConfig.label ?? outcomeConfig.id ?? '')
                return label === outcome ? { ...outcomeConfig, target_step_id: toStepId } : item
              }),
            },
          }
        }
        if (step.step_type === 'input' && outcome === 'Таймаут') {
          return {
            ...step,
            config_json: { ...step.config_json, timeout_target_step_id: toStepId },
          }
        }
        if (step.step_type === 'input' && Array.isArray(step.config_json.choices)) {
          return {
            ...step,
            config_json: {
              ...step.config_json,
              choices: step.config_json.choices.map((item) => {
                if (typeof item !== 'object' || item === null) {
                  return item
                }
                const choice = item as Record<string, unknown>
                const label = String(choice.label ?? choice.value ?? choice.id ?? '')
                return label === outcome ? { ...choice, target_step_id: toStepId } : item
              }),
            },
          }
        }
        if (step.step_type === 'message' && Array.isArray(step.config_json.messages)) {
          const messages = step.config_json.messages
          return {
            ...step,
            config_json: {
              ...step.config_json,
              messages: messages.map((message) => {
                if (typeof message !== 'object' || message === null) {
                  return message
                }
                const messageConfig = message as Record<string, unknown>
                const buttons = Array.isArray(messageConfig.buttons) ? messageConfig.buttons : []
                return {
                  ...messageConfig,
                  buttons: buttons.map((item) => {
                    if (typeof item !== 'object' || item === null) {
                      return item
                    }
                    const button = item as Record<string, unknown>
                    const label = String(button.label ?? button.value ?? button.id ?? '')
                    return label === outcome ? { ...button, target_step_id: toStepId } : item
                  }),
                }
              }),
            },
          }
        }
        if (step.step_type === 'delay') {
          return {
            ...step,
            config_json: { ...step.config_json, target_step_id: toStepId },
          }
        }
        return step
      })
      return {
        ...current,
        steps: syncedSteps,
        edges: [
          ...current.edges,
          {
            id: crypto.randomUUID(),
            from_step_id: fromStepId,
            to_step_id: toStepId,
            condition_json: outcome ? { outcome, label: outcome } : null,
            priority: 0,
          },
        ],
      }
    })
  }

  const saveDraft = async () => {
    if (!graph || !activeVersionId || isSaving) {
      return
    }
    setIsSaving(true)
    try {
      const saved = await saveGraph(funnelId, activeVersionId, projectId, graph)
      setGraph(graphWithDefaults(saved))
      void fetchVersions(funnelId, projectId).then(setVersions)
      notify({ tone: 'success', message: 'Черновик сохранён.' })
    } catch {
      notify({ tone: 'error', message: 'Не удалось сохранить черновик.' })
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
      try {
        await saveGraph(funnelId, activeVersionId, projectId, graph)
      } catch {
        notify({ tone: 'error', message: 'Не удалось сохранить черновик перед публикацией.' })
        return
      }
    }
    setIsPublishOpen(true)
  }

  const handlePublished = () => {
    notify({ tone: 'success', message: 'Воронка опубликована.' })
    setIsPublishOpen(false)
    void fetchFunnel(funnelId, projectId).then(setFunnel)
    void fetchVersions(funnelId, projectId).then(setVersions)
  }

  const switchVersion = async (nextVersionId: string) => {
    if (nextVersionId === activeVersionId) {
      return
    }
    try {
      const loadedGraph = await fetchGraph(funnelId, nextVersionId, projectId)
      setActiveVersionId(nextVersionId)
      onVersionReady(nextVersionId)
      setGraph(graphWithDefaults(loadedGraph))
      setSelectedStepId(loadedGraph.steps[0]?.id ?? null)
      setSelectedEdgeId(null)
    } catch {
      notify({ tone: 'error', message: 'Не удалось открыть версию.' })
    }
  }

  const createDraftFromCurrent = async () => {
    if (!activeVersionId) {
      return
    }
    try {
      const draft = await createDraftFromVersion(funnelId, activeVersionId, projectId)
      const loadedGraph = await fetchGraph(funnelId, draft.id, projectId)
      setActiveVersionId(draft.id)
      onVersionReady(draft.id)
      setVersions(await fetchVersions(funnelId, projectId))
      setGraph(graphWithDefaults(loadedGraph))
      notify({ tone: 'success', message: 'Черновик из версии создан.' })
    } catch {
      notify({ tone: 'error', message: 'Не удалось создать черновик из версии.' })
    }
  }

  const makeCurrentActive = async () => {
    if (!funnel || !activeVersionId) {
      return
    }
    try {
      await setBotActiveFunnel(funnel.bot_id, projectId, {
        funnel_id: funnel.id,
        version_id: activeVersionId,
      })
      notify({ tone: 'success', message: 'Активная версия бота переключена.' })
      setFunnel(await fetchFunnel(funnelId, projectId))
      setVersions(await fetchVersions(funnelId, projectId))
    } catch {
      notify({ tone: 'error', message: 'Можно активировать только опубликованную версию.' })
    }
  }

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const isSave = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's'
      if (isSave) {
        event.preventDefault()
        void saveDraft()
        return
      }
      if ((event.metaKey || event.ctrlKey) && event.key === '0') {
        event.preventDefault()
        return
      }
      if (event.key === 'Escape') {
        setSelectedStepId(null)
        setSelectedEdgeId(null)
        return
      }
      if (event.key !== 'Delete' && event.key !== 'Backspace') {
        return
      }
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select')) {
        return
      }
      if (selectedEdgeId) {
        event.preventDefault()
        removeEdge(selectedEdgeId)
        return
      }
      if (selectedStepId) {
        const hasEdges = graph?.edges.some(
          (edge) => edge.from_step_id === selectedStepId || edge.to_step_id === selectedStepId,
        )
        if (!hasEdges || window.confirm('Удалить блок и связанные с ним связи?')) {
          event.preventDefault()
          deleteStep(selectedStepId)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [activeVersionId, graph?.edges, removeEdge, selectedEdgeId, selectedStepId])

  if (isLoading || !graph || !funnel || !activeVersionId) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-white/8 bg-surface/90 text-sm text-gray-400">
        <LoaderCircle size={18} className="mr-2 animate-spin" />
        Загрузка конструктора
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/8 bg-[#090d18]/80">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/8 bg-[#0d1324]/95 px-4 py-3 shadow-card">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-white/20"
            title="К списку"
          >
            <ArrowLeft size={16} />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold text-white">{funnel.name}</h1>
              <span className="rounded-full border border-white/10 bg-white/[0.05] px-2 py-0.5 text-xs text-gray-300">
                {selectedVersion?.status === 'published'
                  ? 'Опубликована'
                  : selectedVersion?.status === 'archived'
                    ? 'Архив'
                    : 'Черновик'}
              </span>
              {selectedVersion?.is_active_for_bot ? (
                <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2 py-0.5 text-xs text-emerald-100">
                  Активна
                </span>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span>{graph.steps.length} блоков</span>
              <span>{graph.edges.length} связей</span>
              <select
                value={activeVersionId}
                onChange={(event) => void switchVersion(event.target.value)}
                className="h-7 rounded-lg border border-white/10 bg-background/70 px-2 text-xs text-gray-100 outline-none"
              >
                {versions.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} ·{' '}
                    {version.status === 'draft'
                      ? 'черновик'
                      : version.status === 'published'
                        ? version.is_active_for_bot
                          ? 'активна'
                          : 'опубликована'
                        : 'архив'}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void createDraftFromCurrent()}
                className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 text-xs text-gray-300 transition hover:border-accent-300/35"
              >
                <CopyPlus size={13} />
                Черновик
              </button>
              <button
                type="button"
                onClick={() => void makeCurrentActive()}
                className="inline-flex h-7 items-center gap-1 rounded-lg border border-emerald-300/20 bg-emerald-300/10 px-2 text-xs text-emerald-50 transition hover:border-emerald-300/40"
              >
                <CheckCircle2 size={13} />
                Сделать активной
              </button>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setActiveTab(activeTab === 'editor' ? 'analytics' : 'editor')}
            className={`inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-sm transition ${
              activeTab === 'analytics'
                ? 'border-accent-300/35 bg-accent-300/10 text-accent-50'
                : 'border-white/10 bg-white/[0.04] text-gray-100 hover:border-white/20'
            }`}
          >
            <BarChart3 size={15} />
            {activeTab === 'analytics' ? 'Редактор' : 'Аналитика'}
          </button>
          <button
            type="button"
            onClick={() => void validate()}
            disabled={isValidating}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-amber-300/20 bg-amber-300/10 px-3 text-sm text-amber-50 transition hover:border-amber-300/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isValidating ? <LoaderCircle size={15} className="animate-spin" /> : <PlayCircle size={15} />}
            Тестировать
          </button>
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
            onClick={() => void openPublish()}
            className="inline-flex h-9 items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-3 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent"
          >
            <Send size={15} />
            Опубликовать
          </button>
        </div>
      </header>

      <div className="rounded-lg border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-sm text-amber-50 md:hidden">
        Редактор воронок удобнее на компьютере.
      </div>

      {activeTab === 'analytics' && (
        <div className="border-b border-white/8 bg-[#0d1324]/95 px-4 py-3">
          <HoldModeToggle
            funnelId={funnelId}
            versionId={activeVersionId}
            isHoldActive={selectedVersion?.is_hold_active ?? false}
            onToggle={() => void loadVersions()}
          />
        </div>
      )}

      {activeTab === 'editor' ? (
        <>
          <div className="border-b border-white/8 bg-[#0d1324]/95 px-4 py-3">
            <HoldModeToggle
              funnelId={funnelId}
              versionId={activeVersionId}
              isHoldActive={selectedVersion?.is_hold_active ?? false}
              onToggle={() => void loadVersions()}
            />
          </div>

          <div className="grid min-h-0 flex-1 xl:grid-cols-[280px_minmax(0,1fr)_320px] xl:overflow-hidden">
            <BlockLibrary onAdd={addBlock} />
            <div className="min-h-0 overflow-hidden">
              <FunnelCanvas
                steps={graph.steps}
                edges={graph.edges}
                selectedStepId={selectedStepId}
                selectedEdgeId={selectedEdgeId}
                onSelectStep={setSelectedStepId}
                onSelectEdge={setSelectedEdgeId}
                onMoveStep={(stepId, position) =>
                  updateStep(stepId, { position_x: position.x, position_y: position.y })
                }
                onConnect={connectSteps}
                onDeleteStep={deleteStep}
              />
            </div>
            <InspectorPanel
              selectedStep={selectedStep}
              selectedEdge={selectedEdge}
              steps={graph.steps}
              edges={graph.edges}
              fieldMappings={graph.field_mappings}
              pushRules={graph.push_rules}
              hasPublishedVersion={Boolean(funnel.published_version_id)}
              onUpdateStep={updateStep}
              onDeleteStep={deleteStep}
              onUpdateEdge={updateEdge}
              onRemoveEdge={removeEdge}
              onSelectEdge={setSelectedEdgeId}
              onFieldMappingsChange={(field_mappings) =>
                setGraph((current) => (current ? { ...current, field_mappings } : current))
              }
              onPushRulesChange={(push_rules) =>
                setGraph((current) => (current ? { ...current, push_rules } : current))
              }
            />
          </div>
        </>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-6">
          {isLoadingAnalytics ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Загрузка аналитики
            </div>
          ) : analyticsData.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-gray-400">
              Нет данных для отображения
            </div>
          ) : (
            <DropOffChart data={analyticsData} />
          )}
        </div>
      )}

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

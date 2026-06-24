import {
  ArrowLeft,
  BarChart3,
  CopyPlus,
  GitBranch,
  History,
  LoaderCircle,
  PanelLeft,
  PlayCircle,
  Save,
  Send,
  Settings2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useNotificationStore } from '../../../shared/lib'
import {
  createDraftVersion,
  createDraftFromVersion,
  fetchDropOffAnalytics,
  fetchFunnel,
  fetchFunnelUsers,
  fetchGraph,
  fetchVersions,
  saveGraph,
  validateFunnelVersion,
  type FunnelUser,
} from '../api'
import type { BlockMenuItem } from '../blockCatalog'
import { getFunnelApiErrorMessage } from '../errors'
import {
  collectConfiguredOutputs,
  edgeLabel,
  edgeSourceKey,
  normalizeAbVariants,
  normalizeButtons,
  normalizeMessages,
  normalizeOutcomes,
  syncManagedEdgesForStep,
} from '../funnelConfig'
import type {
  Funnel,
  FunnelDropOffStep,
  FunnelEdge,
  FunnelGraph,
  FunnelStep,
  FunnelVersion,
} from '../types'
import BlockLibrary from './BlockLibrary'
import DropOffChart from './DropOffChart'
import FunnelCanvas from './FunnelCanvas'
import HoldModeToggle from './HoldModeToggle'
import InspectorPanel from './InspectorPanel'
import PublishReviewModal from './PublishReviewModal'
import VersionHistoryPanel from './VersionHistoryPanel'

type FunnelBuilderProps = {
  funnelId: string
  versionId?: string | null
  projectId: string
  onBack: () => void
  onVersionReady: (versionId: string) => void
}

type CompactBuilderPanel = 'canvas' | 'library' | 'inspector'

function isCompactBuilderViewport() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 1023px)').matches
}

function graphWithDefaults(graph: FunnelGraph): FunnelGraph {
  const steps = graph.steps.map((step) => ({
    ...step,
    config_json: step.config_json ?? {},
    validation_json: step.validation_json ?? null,
    ui_schema_json: step.ui_schema_json ?? null,
  }))
  const stepById = new Map(steps.map((step) => [step.id, step]))

  return {
    steps,
    edges: graph.edges.map((edge) => {
      const sourceStep = stepById.get(edge.from_step_id)
      const sourceKey = edgeSourceKey(edge, sourceStep)
      if (!sourceKey) {
        return edge
      }
      const output = sourceStep
        ? collectConfiguredOutputs(sourceStep).find((item) => item.key === sourceKey)
        : null
      const label = edgeLabel(edge) ?? output?.label ?? null
      return {
        ...edge,
        condition_json: {
          ...(edge.condition_json ?? {}),
          source_key: sourceKey,
          ...(label ? { outcome: label, label } : {}),
        },
      }
    }),
    push_rules: graph.push_rules,
    field_mappings: graph.field_mappings,
  }
}

function setManagedTarget(step: FunnelStep, sourceKey: string, targetStepId: string): FunnelStep {
  if (step.block_type === 'generic_ab_test') {
    return {
      ...step,
      config_json: {
        ...step.config_json,
        variants: normalizeAbVariants(step.config_json.variants).map((variant) =>
          `ab:${variant.id}` === sourceKey
            ? { ...variant, target_step_id: targetStepId }
            : variant,
        ),
      },
    }
  }

  if (step.step_type === 'condition') {
    return {
      ...step,
      config_json: {
        ...step.config_json,
        outcomes: normalizeOutcomes(step.config_json.outcomes).map((outcome) =>
          `condition:${outcome.id}` === sourceKey
            ? { ...outcome, target_step_id: targetStepId }
            : outcome,
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
              ? { ...button, target_step_id: targetStepId }
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
        config_json: { ...step.config_json, timeout_target_step_id: targetStepId },
      }
    }
    if (!sourceKey.startsWith('choice:')) {
      return step
    }
    return {
      ...step,
      config_json: {
        ...step.config_json,
        choices: normalizeButtons(
          step.config_json.choices ?? step.config_json.options ?? step.config_json.buttons,
        ).map((choice) =>
          `choice:${choice.id}` === sourceKey
            ? { ...choice, target_step_id: targetStepId }
            : choice,
        ),
      },
    }
  }

  if (step.step_type === 'delay' && sourceKey === 'delay:target') {
    return {
      ...step,
      config_json: { ...step.config_json, target_step_id: targetStepId },
    }
  }

  return step
}

function clearManagedTarget(step: FunnelStep, sourceKey: string): FunnelStep {
  return setManagedTarget(step, sourceKey, '')
}

function isConfigBackedSource(sourceKey: string) {
  return (
    sourceKey.startsWith('condition:') ||
    sourceKey.startsWith('ab:') ||
    (sourceKey.startsWith('message:') && sourceKey.includes(':button:')) ||
    sourceKey.startsWith('choice:') ||
    sourceKey === 'input:timeout' ||
    sourceKey === 'delay:target'
  )
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
  const [versionUsers, setVersionUsers] = useState<FunnelUser[]>([])
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isValidating, setIsValidating] = useState(false)
  const [isPublishOpen, setIsPublishOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'analytics' | 'versions'>('editor')
  const [compactPanel, setCompactPanel] = useState<CompactBuilderPanel>('canvas')
  const [analyticsData, setAnalyticsData] = useState<FunnelDropOffStep[]>([])
  const [isLoadingAnalytics, setIsLoadingAnalytics] = useState(false)
  const isLoadingAnalyticsRef = useRef(false)

  const loadAnalytics = useCallback(async () => {
    if (!activeVersionId || isLoadingAnalyticsRef.current) {
      return
    }
    isLoadingAnalyticsRef.current = true
    setIsLoadingAnalytics(true)
    try {
      const response = await fetchDropOffAnalytics(funnelId, activeVersionId, projectId)
      setAnalyticsData(response.steps ?? [])
    } catch {
      notify({ tone: 'error', message: 'Не удалось загрузить аналитику.' })
      setAnalyticsData([])
    } finally {
      isLoadingAnalyticsRef.current = false
      setIsLoadingAnalytics(false)
    }
  }, [activeVersionId, funnelId, notify, projectId])

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
    fetchFunnelUsers(projectId)
      .then((users) => {
        if (isMounted) {
          setVersionUsers(users)
        }
      })
      .catch(() => {
        if (isMounted) {
          setVersionUsers([])
        }
      })
    return () => {
      isMounted = false
    }
  }, [projectId])

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
  const isEditableDraft = selectedVersion?.status === 'draft'

  const revealCompactPanel = useCallback((panel: CompactBuilderPanel) => {
    if (isCompactBuilderViewport()) {
      setCompactPanel(panel)
    }
  }, [])

  const handleSelectStep = useCallback(
    (stepId: string | null) => {
      setSelectedStepId(stepId)
      if (stepId) {
        revealCompactPanel('inspector')
      }
    },
    [revealCompactPanel],
  )

  const handleSelectEdge = useCallback(
    (edgeId: string | null) => {
      setSelectedEdgeId(edgeId)
      if (edgeId) {
        revealCompactPanel('inspector')
      }
    },
    [revealCompactPanel],
  )

  const updateStep = useCallback((stepId: string, patch: Partial<FunnelStep>) => {
    if (!isEditableDraft) {
      return
    }
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
  }, [isEditableDraft])

  const deleteStep = (stepId: string) => {
    if (!isEditableDraft) {
      return
    }
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
    if (!isEditableDraft) {
      return
    }
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
    revealCompactPanel('canvas')
  }

  const updateEdge = (edgeId: string, patch: Partial<FunnelEdge>) => {
    if (!isEditableDraft) {
      return
    }
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
    if (!isEditableDraft) {
      return
    }
    setGraph((current) =>
      current
        ? {
            ...current,
            steps: current.steps.map((step) => {
              const edge = current.edges.find((item) => item.id === edgeId)
              const sourceKey = edge?.condition_json?.source_key
              return edge?.from_step_id === step.id &&
                typeof sourceKey === 'string' &&
                isConfigBackedSource(sourceKey)
                ? clearManagedTarget(step, sourceKey)
                : step
            }),
            edges: current.edges.filter((edge) => edge.id !== edgeId),
          }
        : current,
    )
    setSelectedEdgeId((current) => (current === edgeId ? null : current))
  }, [isEditableDraft])

  const connectSteps = (fromStepId: string, toStepId: string, sourceKey: string | null) => {
    if (!isEditableDraft) {
      return
    }
    if (fromStepId === toStepId) {
      return
    }
    setGraph((current) => {
      if (!current) {
        return current
      }
      const sourceStep = current.steps.find((step) => step.id === fromStepId)
      if (!sourceStep) {
        return current
      }
      const output = sourceKey
        ? collectConfiguredOutputs(sourceStep).find((item) => item.key === sourceKey)
        : null
      const label = output?.label ?? null

      if (sourceKey && isConfigBackedSource(sourceKey)) {
        const syncedSteps = current.steps.map((step) =>
          step.id === fromStepId ? setManagedTarget(step, sourceKey, toStepId) : step,
        )
        const changedStep = syncedSteps.find((step) => step.id === fromStepId)
        return {
          ...current,
          steps: syncedSteps,
          edges: changedStep ? syncManagedEdgesForStep(current.edges, changedStep) : current.edges,
        }
      }

      const condition_json = sourceKey
        ? {
            source_key: sourceKey,
            ...(label ? { outcome: label, label } : {}),
            managed: false,
          }
        : null
      const existingIndex = current.edges.findIndex((edge) => {
        if (edge.from_step_id !== fromStepId) {
          return false
        }
        const edgeKey = edgeSourceKey(edge, sourceStep)
        return sourceKey ? edgeKey === sourceKey : !edgeKey && !edgeLabel(edge)
      })

      if (existingIndex >= 0) {
        return {
          ...current,
          edges: current.edges.map((edge, index) =>
            index === existingIndex
              ? {
                  ...edge,
                  to_step_id: toStepId,
                  condition_json,
                }
              : edge,
          ),
        }
      }

      return {
        ...current,
        edges: [
          ...current.edges,
          {
            id: crypto.randomUUID(),
            from_step_id: fromStepId,
            to_step_id: toStepId,
            condition_json,
            priority: 0,
          },
        ],
      }
    })
  }

  const saveDraft = async () => {
    if (!graph || !activeVersionId || isSaving || !isEditableDraft) {
      return
    }
    setIsSaving(true)
    try {
      const saved = await saveGraph(funnelId, activeVersionId, projectId, graph)
      setGraph(graphWithDefaults(saved))
      void fetchVersions(funnelId, projectId).then(setVersions)
      notify({ tone: 'success', message: 'Черновик сохранён.' })
    } catch (error) {
      notify({
        tone: 'error',
        message: getFunnelApiErrorMessage(error, 'Не удалось сохранить черновик.'),
      })
    } finally {
      setIsSaving(false)
    }
  }

  const validate = async () => {
    if (!activeVersionId || isValidating || !isEditableDraft) {
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
    } catch (error) {
      notify({
        tone: 'error',
        message: getFunnelApiErrorMessage(error, 'Не удалось проверить воронку.'),
      })
    } finally {
      setIsValidating(false)
    }
  }

  const openPublish = async () => {
    if (!isEditableDraft) {
      return
    }
    if (graph && activeVersionId) {
      try {
        await saveGraph(funnelId, activeVersionId, projectId, graph)
      } catch (error) {
        notify({
          tone: 'error',
          message: getFunnelApiErrorMessage(
            error,
            'Не удалось сохранить черновик перед публикацией.',
          ),
        })
        return
      }
    }
    setIsPublishOpen(true)
  }

  const handlePublished = (publishedVersion: { id: string; version_number: number }) => {
    notify({
      tone: 'success',
      message: `Версия v${publishedVersion.version_number} опубликована. Выберите её активной на странице «Воронки».`,
    })
    setIsPublishOpen(false)
    void Promise.all([
      fetchFunnel(funnelId, projectId),
      fetchVersions(funnelId, projectId),
      fetchGraph(funnelId, publishedVersion.id, projectId),
    ]).then(([loadedFunnel, loadedVersions, loadedGraph]) => {
      setFunnel(loadedFunnel)
      setVersions(loadedVersions)
      setActiveVersionId(publishedVersion.id)
      onVersionReady(publishedVersion.id)
      setGraph(graphWithDefaults(loadedGraph))
      setSelectedStepId(loadedGraph.steps[0]?.id ?? null)
      setSelectedEdgeId(null)
    })
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
    if (!activeVersionId || isEditableDraft) {
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
      <div className="flex min-h-[420px] items-center justify-center rounded-lg border border-white/8 bg-surface/90 text-sm text-gray-400 md:h-full">
        <LoaderCircle size={18} className="mr-2 animate-spin" />
        Загрузка конструктора
      </div>
    )
  }

  return (
    <div className="flex min-h-[calc(100dvh-5rem)] flex-col overflow-visible rounded-xl border border-white/8 bg-[#090d18]/80 md:min-h-[calc(100dvh-8rem)] lg:h-full lg:min-h-0 lg:overflow-hidden">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/8 bg-[#0d1324]/95 px-3 py-3 shadow-card md:px-4">
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
              {!isEditableDraft ? (
                <button
                  type="button"
                  onClick={() => void createDraftFromCurrent()}
                  className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 text-xs text-gray-300 transition hover:border-accent-300/35"
                >
                  <CopyPlus size={13} />
                  Создать черновик
                </button>
              ) : null}
            </div>
          </div>
        </div>
        <div className="-mx-1 flex w-full shrink-0 gap-2 overflow-x-auto px-1 pb-1 md:mx-0 md:w-auto md:flex-wrap md:overflow-visible md:px-0 md:pb-0">
          {[
            { key: 'editor' as const, label: 'Редактор', icon: GitBranch },
            { key: 'analytics' as const, label: 'Аналитика', icon: BarChart3 },
            { key: 'versions' as const, label: 'История версий', icon: History },
          ].map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key)}
                className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border px-3 text-sm transition ${
                  activeTab === tab.key
                    ? 'border-accent-300/35 bg-accent-300/10 text-accent-50'
                    : 'border-white/10 bg-white/[0.04] text-gray-100 hover:border-white/20'
                }`}
              >
                <Icon size={15} />
                {tab.label}
              </button>
            )
          })}
          {isEditableDraft ? (
            <>
              <button
                type="button"
                onClick={() => void validate()}
                disabled={isValidating}
                className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-amber-300/20 bg-amber-300/10 px-3 text-sm text-amber-50 transition hover:border-amber-300/40 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isValidating ? <LoaderCircle size={15} className="animate-spin" /> : <PlayCircle size={15} />}
                Проверить
              </button>
              <button
                type="button"
                onClick={() => void saveDraft()}
                disabled={isSaving}
                className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />}
                Сохранить
              </button>
              <button
                type="button"
                onClick={() => void openPublish()}
                className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-3 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent"
              >
                <Send size={15} />
                Опубликовать
              </button>
            </>
          ) : (
            <span className="flex h-9 shrink-0 items-center px-2 text-xs text-gray-500">
              Версия доступна только для просмотра
            </span>
          )}
        </div>
      </header>

      {activeTab === 'analytics' && (
        <div className="border-b border-white/8 bg-[#0d1324]/95 px-4 py-3">
          <HoldModeToggle
            funnelId={funnelId}
            versionId={activeVersionId}
            projectId={projectId}
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
              projectId={projectId}
              isHoldActive={selectedVersion?.is_hold_active ?? false}
              onToggle={() => void loadVersions()}
            />
          </div>

          <div className="grid grid-cols-3 gap-2 border-b border-white/8 bg-[#0d1324]/80 p-2 lg:hidden">
            {[
              { key: 'canvas' as const, label: 'Холст', icon: GitBranch },
              { key: 'library' as const, label: 'Блоки', icon: PanelLeft },
              { key: 'inspector' as const, label: 'Настройки', icon: Settings2 },
            ].map((panel) => {
              const Icon = panel.icon
              const isActive = compactPanel === panel.key
              return (
                <button
                  key={panel.key}
                  type="button"
                  onClick={() => setCompactPanel(panel.key)}
                  className={`inline-flex h-10 min-w-0 items-center justify-center gap-2 rounded-xl border px-2 text-sm font-semibold transition ${
                    isActive
                      ? 'border-accent-300/40 bg-accent-300/12 text-accent-50'
                      : 'border-white/10 bg-white/[0.04] text-gray-300'
                  }`}
                >
                  <Icon size={15} />
                  <span className="truncate">{panel.label}</span>
                </button>
              )
            })}
          </div>

          <div className="grid min-h-0 flex-1 gap-3 overflow-visible p-2 sm:p-3 lg:grid-cols-[240px_minmax(0,1fr)_280px] lg:gap-0 lg:overflow-hidden lg:p-0 xl:grid-cols-[280px_minmax(0,1fr)_320px]">
            <div
              className={`h-[min(72dvh,760px)] min-h-[420px] lg:block lg:h-full lg:min-h-0 lg:overflow-hidden ${
                compactPanel === 'library' ? 'block' : 'hidden'
              }`}
            >
              <BlockLibrary onAdd={addBlock} readOnly={!isEditableDraft} />
            </div>
            <div
              className={`min-h-0 lg:block lg:overflow-hidden ${
                compactPanel === 'canvas' ? 'block' : 'hidden'
              }`}
            >
              <FunnelCanvas
                steps={graph.steps}
                edges={graph.edges}
                selectedStepId={selectedStepId}
                selectedEdgeId={selectedEdgeId}
                onSelectStep={handleSelectStep}
                onSelectEdge={handleSelectEdge}
                onMoveStep={(stepId, position) =>
                  updateStep(stepId, { position_x: position.x, position_y: position.y })
                }
                onConnect={connectSteps}
                onDeleteStep={deleteStep}
                readOnly={!isEditableDraft}
              />
            </div>
            <div
              className={`h-[min(78dvh,820px)] min-h-[460px] lg:block lg:h-full lg:min-h-0 lg:overflow-hidden ${
                compactPanel === 'inspector' ? 'block' : 'hidden'
              }`}
            >
              <InspectorPanel
                selectedStep={selectedStep}
                projectId={projectId}
                selectedEdge={selectedEdge}
                steps={graph.steps}
                edges={graph.edges}
                fieldMappings={graph.field_mappings}
                pushRules={graph.push_rules}
                hasPublishedVersion={Boolean(funnel.published_version_id)}
                readOnly={!isEditableDraft}
                onUpdateStep={updateStep}
                onDeleteStep={deleteStep}
                onUpdateEdge={updateEdge}
                onRemoveEdge={removeEdge}
                onSelectEdge={handleSelectEdge}
                onFieldMappingsChange={(field_mappings) => {
                  if (isEditableDraft) {
                    setGraph((current) => (current ? { ...current, field_mappings } : current))
                  }
                }}
                onPushRulesChange={(push_rules) => {
                  if (isEditableDraft) {
                    setGraph((current) => (current ? { ...current, push_rules } : current))
                  }
                }}
              />
            </div>
          </div>
        </>
      ) : activeTab === 'analytics' ? (
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
      ) : (
        <VersionHistoryPanel
          versions={versions}
          users={versionUsers}
          activeVersionId={activeVersionId}
          onOpenVersion={(nextVersionId) => void switchVersion(nextVersionId)}
        />
      )}

      {isPublishOpen ? (
        <PublishReviewModal
          funnelId={funnelId}
          versionId={activeVersionId}
          projectId={projectId}
          graph={graph}
          onClose={() => setIsPublishOpen(false)}
          onPublished={handlePublished}
        />
      ) : null}
    </div>
  )
}

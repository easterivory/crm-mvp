import { LoaderCircle, Send, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Modal } from '../../../shared/ui'
import { useNotificationStore } from '../../../shared/lib'
import { publishFunnelVersion, validateFunnelGraph, validateFunnelVersion } from '../api'
import { getFunnelApiErrorMessage } from '../errors'
import type {
  FunnelGraph,
  FunnelGraphValidatePayload,
  FunnelGraphValidationResult,
  FunnelValidationIssue,
  FunnelValidationResult,
} from '../types'

type PublishReviewModalProps = {
  funnelId: string
  versionId: string
  projectId: string
  graph: FunnelGraph
  onClose: () => void
  onPublished: (version: { id: string; version_number: number }) => void
}

type PublishValidationState = {
  graph: FunnelGraphValidationResult
  version: FunnelValidationResult | null
}

function buildGraphValidationPayload(graph: FunnelGraph): FunnelGraphValidatePayload {
  return {
    nodes: graph.steps.map((step) => ({
      id: step.id,
      type: step.step_type,
      step_type: step.step_type,
      block_type: step.block_type,
      title: step.title,
      data: {
        id: step.id,
        step_type: step.step_type,
        block_type: step.block_type,
        title: step.title,
        label: step.title,
        config_json: step.config_json,
      },
    })),
    edges: graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.from_step_id,
      target: edge.to_step_id,
      from_step_id: edge.from_step_id,
      to_step_id: edge.to_step_id,
      data: edge.condition_json ?? {},
    })),
  }
}

function issueKey(issue: FunnelValidationIssue, index: number) {
  return `${issue.code}:${issue.step_id ?? issue.edge_id ?? index}`
}

function issueMeta(issue: FunnelValidationIssue) {
  return [
    issue.step_id ? `step_id: ${issue.step_id}` : null,
    issue.step_key ? `key: ${issue.step_key}` : null,
    issue.step_title ? `title: ${issue.step_title}` : null,
    issue.block_type ? `block: ${issue.block_type}` : null,
    issue.edge_id ? `edge_id: ${issue.edge_id}` : null,
  ].filter((item): item is string => Boolean(item))
}

export default function PublishReviewModal({
  funnelId,
  versionId,
  projectId,
  graph,
  onClose,
  onPublished,
}: PublishReviewModalProps) {
  const [validation, setValidation] = useState<PublishValidationState | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isPublishing, setIsPublishing] = useState(false)
  const notify = useNotificationStore((state) => state.notify)

  const graphErrors = validation?.graph.errors ?? []
  const graphWarnings = validation?.graph.warnings ?? []
  const versionErrors = validation?.version?.errors ?? []
  const versionWarnings = validation?.version?.warnings ?? []
  const canPublish = Boolean(
    validation?.graph.is_valid &&
      graphErrors.length === 0 &&
      (validation.version?.can_publish ?? false),
  )

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    const runValidation = async () => {
      const graphValidation = await validateFunnelGraph(
        funnelId,
        projectId,
        buildGraphValidationPayload(graph),
      )
      const versionValidation = graphValidation.is_valid
        ? await validateFunnelVersion(funnelId, versionId, projectId)
        : null
      return {
        graph: graphValidation,
        version: versionValidation,
      }
    }
    runValidation()
      .then((data) => {
        if (isMounted) {
          setValidation(data)
        }
      })
      .catch((error) => {
        if (isMounted) {
          notify({
            tone: 'error',
            message: getFunnelApiErrorMessage(
              error,
              'Не удалось выполнить проверку перед публикацией.',
            ),
          })
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })
    return () => {
      isMounted = false
    }
  }, [funnelId, graph, notify, projectId, versionId])

  const publish = async () => {
    if (!canPublish || isPublishing) {
      return
    }
    setIsPublishing(true)
    try {
      const published = await publishFunnelVersion(funnelId, versionId, projectId)
      onPublished(published)
    } catch (error) {
      notify({
        tone: 'error',
        message: getFunnelApiErrorMessage(error, 'Не удалось опубликовать воронку.'),
      })
    } finally {
      setIsPublishing(false)
    }
  }

  return (
    <Modal
      title="Проверка перед публикацией"
      description="Ошибки блокируют публикацию. Предупреждения можно оставить, если сценарий так задуман."
      maxWidthClassName="max-w-2xl"
      onClose={onClose}
    >
      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <LoaderCircle size={16} className="animate-spin" />
          Проверяем граф
        </div>
      ) : null}

      {validation ? (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-red-300/20 bg-red-500/10 p-3">
              <p className="text-sm font-semibold text-red-100">
                Ошибки: {graphErrors.length + versionErrors.length}
              </p>
            </div>
            <div className="rounded-lg border border-amber-300/20 bg-amber-500/10 p-3">
              <p className="text-sm font-semibold text-amber-100">
                Предупреждения: {graphWarnings.length + versionWarnings.length}
              </p>
            </div>
          </div>

          {graphErrors.length + graphWarnings.length + versionErrors.length + versionWarnings.length > 0 ? (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {graphErrors.map((message, index) => (
                <div
                  key={`graph-error:${index}:${message}`}
                  className="rounded-lg border border-red-300/20 bg-red-500/10 p-3 text-sm text-red-50"
                >
                  <div className="flex items-center gap-2 font-medium">
                    <TriangleAlert size={15} />
                    Критическая ошибка графа
                  </div>
                  <p className="mt-1 leading-5 opacity-90">{message}</p>
                </div>
              ))}
              {versionErrors.map((issue, index) => (
                <div
                  key={issueKey(issue, index)}
                  className="rounded-lg border border-red-300/20 bg-red-500/10 p-3 text-sm text-red-50"
                >
                  <div className="flex items-center gap-2 font-medium">
                    <TriangleAlert size={15} />
                    Ошибка конфигурации
                  </div>
                  <p className="mt-1 leading-5 opacity-90">{issue.message}</p>
                  {issueMeta(issue).length > 0 ? (
                    <p className="mt-2 break-all font-mono text-xs leading-5 opacity-70">
                      {issueMeta(issue).join(' · ')}
                    </p>
                  ) : null}
                </div>
              ))}
              {graphWarnings.map((message, index) => (
                <div
                  key={`graph-warning:${index}:${message}`}
                  className="rounded-lg border border-amber-300/20 bg-amber-500/10 p-3 text-sm text-amber-50"
                >
                  <div className="flex items-center gap-2 font-medium">
                    <TriangleAlert size={15} />
                    Предупреждение графа
                  </div>
                  <p className="mt-1 leading-5 opacity-90">{message}</p>
                </div>
              ))}
              {versionWarnings.map((issue, index) => (
                <div
                  key={issueKey(issue, index)}
                  className="rounded-lg border border-amber-300/20 bg-amber-500/10 p-3 text-sm text-amber-50"
                >
                  <div className="flex items-center gap-2 font-medium">
                    <TriangleAlert size={15} />
                    Предупреждение конфигурации
                  </div>
                  <p className="mt-1 leading-5 opacity-90">{issue.message}</p>
                  {issueMeta(issue).length > 0 ? (
                    <p className="mt-2 break-all font-mono text-xs leading-5 opacity-70">
                      {issueMeta(issue).join(' · ')}
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-lg border border-emerald-300/20 bg-emerald-500/10 p-3 text-sm text-emerald-50">
              Граф готов к публикации.
            </p>
          )}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm text-gray-200 transition hover:border-white/20"
            >
              Закрыть
            </button>
            <button
              type="button"
              onClick={() => void publish()}
              disabled={!canPublish || isPublishing}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPublishing ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
              Опубликовать
            </button>
          </div>
        </div>
      ) : null}
    </Modal>
  )
}

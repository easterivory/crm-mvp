import { LoaderCircle, Send, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Modal } from '../../../shared/ui'
import { useNotificationStore } from '../../../shared/lib'
import { publishFunnelVersion, validateFunnelVersion } from '../api'
import type { FunnelValidationResult } from '../types'

type PublishReviewModalProps = {
  funnelId: string
  versionId: string
  projectId: string
  onClose: () => void
  onPublished: () => void
}

export default function PublishReviewModal({
  funnelId,
  versionId,
  projectId,
  onClose,
  onPublished,
}: PublishReviewModalProps) {
  const [validation, setValidation] = useState<FunnelValidationResult | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isPublishing, setIsPublishing] = useState(false)
  const notify = useNotificationStore((state) => state.notify)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    validateFunnelVersion(funnelId, versionId, projectId)
      .then((data) => {
        if (isMounted) {
          setValidation(data)
        }
      })
      .catch(() => {
        if (isMounted) {
          notify({ tone: 'error', message: 'Не удалось выполнить проверку перед публикацией.' })
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
  }, [funnelId, notify, projectId, versionId])

  const publish = async () => {
    if (!validation?.can_publish || isPublishing) {
      return
    }
    setIsPublishing(true)
    try {
      await publishFunnelVersion(funnelId, versionId, projectId)
      onPublished()
    } catch {
      notify({ tone: 'error', message: 'Не удалось опубликовать воронку.' })
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
                Ошибки: {validation.errors.length}
              </p>
            </div>
            <div className="rounded-lg border border-amber-300/20 bg-amber-500/10 p-3">
              <p className="text-sm font-semibold text-amber-100">
                Предупреждения: {validation.warnings.length}
              </p>
            </div>
          </div>

          {[...validation.errors, ...validation.warnings].length > 0 ? (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {[...validation.errors, ...validation.warnings].map((issue, index) => (
                <div
                  key={`${issue.code}:${index}`}
                  className={`rounded-lg border p-3 text-sm ${
                    issue.severity === 'error'
                      ? 'border-red-300/20 bg-red-500/10 text-red-50'
                      : 'border-amber-300/20 bg-amber-500/10 text-amber-50'
                  }`}
                >
                  <div className="flex items-center gap-2 font-medium">
                    <TriangleAlert size={15} />
                    {issue.severity === 'error' ? 'Ошибка' : 'Предупреждение'}
                  </div>
                  <p className="mt-1 leading-5 opacity-90">{issue.message}</p>
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
              disabled={!validation.can_publish || isPublishing}
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

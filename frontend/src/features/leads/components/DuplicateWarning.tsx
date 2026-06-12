import { AlertTriangle, ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'

import { fetchLeadDuplicates } from '../api'
import type { DuplicateLeadDetail, DuplicateSubmissionHistory } from '../types'

type DuplicateWarningProps = {
  leadId: string
  projectId: string
  className?: string
}

const MATCH_LABELS: Record<string, string> = {
  phone: 'Совпал телефон',
  telegram_id: 'Совпал Telegram ID',
  username: 'Совпал Telegram Username',
}

const STATUS_LABELS: Record<string, string> = {
  completed: 'Успешно',
  success: 'Успешно',
  duplicate: 'Дубль',
  failed: 'Ошибка',
  pending: 'В очереди',
  queued: 'В очереди',
}

function getCancelCode(err: unknown) {
  return typeof err === 'object' && err !== null && 'code' in err
    ? String((err as { code?: unknown }).code ?? '')
    : ''
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function matchCopy(duplicate: DuplicateLeadDetail) {
  const fields = duplicate.matched_fields.length > 0
    ? duplicate.matched_fields
    : [duplicate.match_type]

  return fields
    .map((field) => MATCH_LABELS[field] ?? field)
    .join(' · ')
}

function leadStatusCopy(duplicate: DuplicateLeadDetail) {
  if (duplicate.is_deleted) {
    return 'Удалён'
  }
  if (duplicate.is_trash) {
    return 'Треш'
  }
  return duplicate.lead_status ?? 'Активный'
}

function submissionStatusCopy(submission: DuplicateSubmissionHistory) {
  return STATUS_LABELS[submission.status.toLowerCase()] ?? submission.status
}

export default function DuplicateWarning({
  leadId,
  projectId,
  className = '',
}: DuplicateWarningProps) {
  const [duplicates, setDuplicates] = useState<DuplicateLeadDetail[]>([])
  const [isExpanded, setIsExpanded] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    let isMounted = true

    setDuplicates([])
    setIsExpanded(false)

    fetchLeadDuplicates(leadId, projectId, controller.signal)
      .then((items) => {
        if (isMounted) {
          setDuplicates(items)
        }
      })
      .catch((err: unknown) => {
        if (getCancelCode(err) !== 'ERR_CANCELED' && isMounted) {
          setDuplicates([])
        }
      })

    return () => {
      isMounted = false
      controller.abort()
    }
  }, [leadId, projectId])

  if (duplicates.length === 0) {
    return null
  }

  return (
    <section className={`rounded-xl border border-amber-300/45 bg-gradient-to-r from-amber-500/20 to-orange-500/15 shadow-[0_0_28px_rgba(245,158,11,0.18)] ${className}`}>
      <div className="animate-pulse px-4 py-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-200/35 bg-amber-300/15 text-amber-100">
              <AlertTriangle size={18} />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-amber-50">⚠️ Возможный дубль</p>
              <p className="truncate text-xs text-amber-100/75">
                Найдено совпадений: {duplicates.length}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsExpanded((current) => !current)}
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-xl border border-amber-100/25 bg-black/15 px-3 text-xs font-semibold text-amber-50 transition hover:border-amber-100/55"
          >
            {isExpanded ? 'Скрыть совпадения' : `Показать совпадения (${duplicates.length})`}
            <ChevronDown
              size={15}
              className={`transition ${isExpanded ? 'rotate-180' : ''}`}
            />
          </button>
        </div>
      </div>

      {isExpanded ? (
        <div className="border-t border-amber-100/15 bg-black/10 px-4 py-3">
          <div className="space-y-3">
            {duplicates.map((duplicate) => (
              <article
                key={`${duplicate.lead_id}-${duplicate.match_type}`}
                className="rounded-xl border border-amber-100/15 bg-[#0B0F19]/45 p-3"
              >
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-amber-50">
                      {matchCopy(duplicate)}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-amber-100/75">
                      Проект: {duplicate.project_name} | Бот: {duplicate.bot_name ?? 'Не указан'}
                    </p>
                  </div>
                  <span className="w-fit rounded-full border border-amber-100/20 bg-amber-300/10 px-2 py-1 text-xs font-medium text-amber-50">
                    Статус: {leadStatusCopy(duplicate)}
                  </span>
                </div>

                <p className="mt-2 text-xs text-amber-100/65">
                  Создан: {formatDateTime(duplicate.created_at)}
                </p>

                <div className="mt-3 rounded-lg border border-white/5 bg-black/15 p-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-amber-100/70">
                    История отправок клона
                  </p>
                  {duplicate.submission_history.length > 0 ? (
                    <div className="mt-2 space-y-2">
                      {duplicate.submission_history.map((submission) => (
                        <div
                          key={`${submission.partner_integration_id}-${submission.created_at}`}
                          className="text-xs leading-5 text-amber-50/90"
                        >
                          Отправлен партнеру {submission.partner_name} ({submissionStatusCopy(submission)})
                          {submission.partner_status ? ` · ${submission.partner_status}` : ''}
                          {submission.partner_feedback ? (
                            <p className="mt-1 rounded-md border border-white/5 bg-white/[0.04] px-2 py-1 text-amber-100/80">
                              {submission.partner_feedback}
                            </p>
                          ) : submission.error_message ? (
                            <p className="mt-1 rounded-md border border-red-300/20 bg-red-500/10 px-2 py-1 text-red-100">
                              {submission.error_message}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs text-amber-100/60">
                      Отправок партнерам не было.
                    </p>
                  )}
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

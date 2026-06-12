import axios from 'axios'
import { AlertTriangle, CheckCircle2, LoaderCircle, Send, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  fetchLeadSubmissionPreview,
  fetchLeadSubmissions,
  submitLeadToPartner,
} from '../api'
import type {
  LeadSubmission,
  LeadSubmissionPreview,
  PartnerIntegration,
} from '../types'
import {
  fetchLeadDuplicates,
  type DuplicateLeadDetail,
  type DuplicateSubmissionHistory,
  type Lead,
} from '../../leads'

type LeadSubmissionDrawerProps = {
  lead: Lead
  partners: PartnerIntegration[]
  projectId: string
  initialPartnerId?: string
  onClose: () => void
  onSubmitted: () => void
}

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.response?.status === 422) {
      return 'Проверьте обязательные поля лида и маппинг партнёра.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function formatDateTime(value: string | null) {
  if (!value) {
    return 'Не завершено'
  }
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function finalStatusCopy(submission: LeadSubmission | null) {
  if (!submission) {
    return null
  }
  if (submission.status === 'completed' || submission.status === 'success') {
    return {
      tone: 'success' as const,
      title: 'Лид успешно принят партнером',
      body: submission.partner_feedback ?? (submission.partner_status ? `Статус партнёра: ${submission.partner_status}` : null),
    }
  }
  if (submission.status === 'duplicate') {
    return {
      tone: 'duplicate' as const,
      title: 'Внимание: Лид отклонен как дубль',
      body: submission.partner_feedback ?? (submission.partner_status ? `Статус партнёра: ${submission.partner_status}` : null),
    }
  }
  if (submission.status === 'failed') {
    return {
      tone: 'failed' as const,
      title: 'Отправка не выполнена',
      body: submission.partner_feedback ?? submission.error_message ?? submission.partner_status ?? 'Партнёр вернул ошибку.',
    }
  }
  return {
    tone: 'pending' as const,
    title: 'Лид поставлен в очередь отправки',
    body: 'Ожидаем ответ postback-воркера.',
  }
}

type DuplicatePartnerConflict = {
  partner: PartnerIntegration
  duplicate: DuplicateLeadDetail
  submission: DuplicateSubmissionHistory
}

const SUCCESSFUL_DUPLICATE_STATUSES = new Set(['completed', 'success'])

function normalizePartnerName(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, ' ')
}

function findDuplicateConflictForPartner(
  partner: PartnerIntegration,
  duplicates: DuplicateLeadDetail[],
): DuplicatePartnerConflict | null {
  const partnerNameKey = normalizePartnerName(partner.name)

  for (const duplicate of duplicates) {
    for (const submission of duplicate.submission_history) {
      const samePartner =
        submission.partner_integration_id === partner.id ||
        normalizePartnerName(submission.partner_name) === partnerNameKey

      if (
        samePartner &&
        SUCCESSFUL_DUPLICATE_STATUSES.has(submission.status.toLowerCase())
      ) {
        return { partner, duplicate, submission }
      }
    }
  }

  return null
}

function duplicateRecommendationText(
  conflict: DuplicatePartnerConflict,
  recommendedPartner: PartnerIntegration | null,
) {
  const recommendation = recommendedPartner
    ? ` (например, ${recommendedPartner.name})`
    : ''

  return `⚠️ Этот контакт уже был успешно сдан рекламодателю ${conflict.partner.name} в проекте ${conflict.duplicate.project_name}. Рекомендуется направить лида другому партнеру${recommendation} во избежание штрафных санкций за дубли, либо перевести в Треш`
}

export default function LeadSubmissionDrawer({
  lead,
  partners,
  projectId,
  initialPartnerId,
  onClose,
  onSubmitted,
}: LeadSubmissionDrawerProps) {
  const activePartners = useMemo(
    () => partners.filter((partner) => partner.is_active),
    [partners],
  )
  const [partnerId, setPartnerId] = useState(
    initialPartnerId || activePartners[0]?.id || '',
  )
  const [preview, setPreview] = useState<LeadSubmissionPreview | null>(null)
  const [previewError, setPreviewError] = useState('')
  const [isPreviewLoading, setIsPreviewLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submission, setSubmission] = useState<LeadSubmission | null>(null)
  const [submissions, setSubmissions] = useState<LeadSubmission[]>([])
  const [isSubmissionsLoading, setIsSubmissionsLoading] = useState(false)
  const [duplicates, setDuplicates] = useState<DuplicateLeadDetail[]>([])
  const [isDuplicatesLoading, setIsDuplicatesLoading] = useState(false)
  const [submitError, setSubmitError] = useState('')

  useEffect(() => {
    setPartnerId((current) => {
      if (current && activePartners.some((partner) => partner.id === current)) {
        return current
      }
      return activePartners[0]?.id ?? ''
    })
  }, [activePartners])

  const loadSubmissions = useCallback(async () => {
    setIsSubmissionsLoading(true)
    try {
      const rows = await fetchLeadSubmissions(lead.id, projectId)
      setSubmissions(rows)
      setSubmission((current) => current ? rows.find((item) => item.id === current.id) ?? current : rows[0] ?? null)
    } catch {
      setSubmissions([])
    } finally {
      setIsSubmissionsLoading(false)
    }
  }, [lead.id, projectId])

  useEffect(() => {
    void loadSubmissions()
  }, [loadSubmissions])

  useEffect(() => {
    const controller = new AbortController()
    let isMounted = true

    setIsDuplicatesLoading(true)
    fetchLeadDuplicates(lead.id, projectId, controller.signal)
      .then((items) => {
        if (isMounted) {
          setDuplicates(items)
        }
      })
      .catch((err: unknown) => {
        if (axios.isCancel(err)) {
          return
        }
        if (isMounted) {
          setDuplicates([])
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsDuplicatesLoading(false)
        }
      })

    return () => {
      isMounted = false
      controller.abort()
    }
  }, [lead.id, projectId])

  const loadPreview = useCallback(async () => {
    if (!partnerId) {
      setPreview(null)
      setPreviewError('')
      return
    }
    setIsPreviewLoading(true)
    setPreviewError('')
    setPreview(null)
    try {
      const data = await fetchLeadSubmissionPreview(lead.id, partnerId, projectId)
      setPreview(data)
    } catch (err) {
      setPreviewError(getErrorMessage(err, 'Не удалось построить preview отправки.'))
    } finally {
      setIsPreviewLoading(false)
    }
  }, [lead.id, partnerId, projectId])

  useEffect(() => {
    void loadPreview()
  }, [loadPreview])

  const pollSubmission = useCallback(
    async (submissionId: string) => {
      for (let attempt = 0; attempt < 12; attempt += 1) {
        const rows = await fetchLeadSubmissions(lead.id, projectId)
        setSubmissions(rows)
        const current = rows.find((item) => item.id === submissionId) ?? rows[0] ?? null
        if (current) {
          setSubmission(current)
          if (['completed', 'success', 'duplicate', 'failed'].includes(current.status)) {
            onSubmitted()
            return
          }
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
      }
    },
    [lead.id, onSubmitted, projectId],
  )

  const statusCopy = finalStatusCopy(submission)
  const selectedPartner = activePartners.find((partner) => partner.id === partnerId) ?? null
  const duplicateSubmission = submissions.find((item) => item.partner_integration_id === partnerId)
  const duplicateConflictByPartnerId = useMemo(() => {
    const conflicts = new Map<string, DuplicatePartnerConflict>()

    for (const partner of activePartners) {
      const conflict = findDuplicateConflictForPartner(partner, duplicates)
      if (conflict) {
        conflicts.set(partner.id, conflict)
      }
    }

    return conflicts
  }, [activePartners, duplicates])
  const duplicatePartnerConflict = partnerId
    ? duplicateConflictByPartnerId.get(partnerId) ?? null
    : null
  const recommendedPartner = useMemo(
    () =>
      activePartners.find(
        (partner) =>
          partner.id !== partnerId &&
          !duplicateConflictByPartnerId.has(partner.id) &&
          !submissions.some((item) => item.partner_integration_id === partner.id),
      ) ?? null,
    [activePartners, duplicateConflictByPartnerId, partnerId, submissions],
  )
  const canSubmit = Boolean(
    partnerId &&
      preview &&
      !previewError &&
      !isPreviewLoading &&
      !isSubmitting &&
      !duplicateSubmission &&
      !duplicatePartnerConflict,
  )

  const handleSubmit = async () => {
    if (
      !partnerId ||
      previewError ||
      !preview ||
      isSubmitting ||
      duplicateSubmission ||
      duplicatePartnerConflict
    ) {
      return
    }
    setIsSubmitting(true)
    setSubmitError('')
    setSubmission(null)
    try {
      const queued = await submitLeadToPartner(lead.id, partnerId, projectId)
      setSubmission({
        id: queued.submission_id,
        lead_id: lead.id,
        partner_integration_id: partnerId,
        status: queued.status,
        request_payload: preview.payload,
        response_payload: null,
        error_message: null,
        partner_feedback: null,
        partner_status: null,
        partner_status_updated_at: null,
        submitted_at: new Date().toISOString(),
        completed_at: null,
      })
      await pollSubmission(queued.submission_id)
    } catch (err) {
      setSubmitError(getErrorMessage(err, 'Не удалось отправить лида партнёру.'))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm">
      <button
        type="button"
        aria-label="Закрыть панель"
        className="hidden flex-1 cursor-default md:block"
        onClick={onClose}
      />
      <aside className="flex h-full w-full max-w-2xl flex-col border-l border-white/10 bg-[#080D17] text-gray-100 shadow-2xl">
        <header className="shrink-0 border-b border-white/5 px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-accent-300/70">
                Partner CRM
              </p>
              <h2 className="mt-1 text-xl font-semibold text-white">
                Подать лида в CRM партнера
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                {lead.name || lead.phone || lead.username || lead.id}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-gray-400 transition hover:border-white/20 hover:text-white"
            >
              <X size={17} />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="space-y-5">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-gray-300">
                Партнёр
              </span>
              <select
                value={partnerId}
                onChange={(event) => {
                  setPartnerId(event.target.value)
                  setSubmission(null)
                  setSubmitError('')
                }}
                className="h-11 w-full rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-gray-100 outline-none transition focus:border-accent-300/60"
              >
                {activePartners.map((partner) => {
                  const hasDuplicateConflict = duplicateConflictByPartnerId.has(partner.id)

                  return (
                    <option
                      key={partner.id}
                      value={partner.id}
                      disabled={hasDuplicateConflict}
                    >
                      {partner.name}{hasDuplicateConflict ? ' — дубль уже сдан' : ''}
                    </option>
                  )
                })}
              </select>
            </label>

            {activePartners.length === 0 ? (
              <div className="rounded-xl border border-amber-400/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                В проекте нет активных партнёрских интеграций.
              </div>
            ) : null}

            {isDuplicatesLoading ? (
              <div className="flex items-center gap-2 rounded-xl border border-white/5 bg-white/[0.02] px-4 py-3 text-sm text-gray-400">
                <LoaderCircle size={16} className="animate-spin" />
                Проверка кросс-проектных дублей
              </div>
            ) : null}

            {duplicateSubmission && selectedPartner ? (
              <div className="rounded-xl border border-orange-400/35 bg-orange-500/15 px-4 py-3 text-sm text-orange-100">
                <div className="flex items-center gap-2 font-semibold">
                  <AlertTriangle size={17} />
                  Повторная отправка заблокирована
                </div>
                <p className="mt-2 leading-6">
                  Этот лид уже отправлялся рекламодателю {selectedPartner.name}. Повторная отправка заблокирована во избежание дублей.
                </p>
                {duplicateSubmission.partner_feedback ? (
                  <p className="mt-2 rounded-lg border border-orange-300/20 bg-black/15 px-3 py-2 text-xs leading-5">
                    {duplicateSubmission.partner_feedback}
                  </p>
                ) : null}
              </div>
            ) : null}

            {duplicatePartnerConflict ? (
              <div className="rounded-xl border border-amber-300/45 bg-amber-500/15 px-4 py-3 text-sm text-amber-50 shadow-[0_0_26px_rgba(245,158,11,0.14)]">
                <div className="flex items-center gap-2 font-semibold">
                  <AlertTriangle size={17} />
                  Найден успешный дубль у рекламодателя
                </div>
                <p className="mt-2 leading-6">
                  {duplicateRecommendationText(duplicatePartnerConflict, recommendedPartner)}
                </p>
                <div className="mt-3 rounded-lg border border-amber-100/15 bg-black/15 px-3 py-2 text-xs leading-5 text-amber-100/80">
                  Клон: проект {duplicatePartnerConflict.duplicate.project_name}
                  {duplicatePartnerConflict.duplicate.bot_name
                    ? ` · бот ${duplicatePartnerConflict.duplicate.bot_name}`
                    : ''}
                  {' · '}
                  статус отправки {duplicatePartnerConflict.submission.status}
                  {duplicatePartnerConflict.submission.partner_status
                    ? ` · ${duplicatePartnerConflict.submission.partner_status}`
                    : ''}
                </div>
              </div>
            ) : null}

            {previewError ? (
              <div className="rounded-xl border border-red-400/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                <div className="flex items-center gap-2 font-semibold">
                  <AlertTriangle size={17} />
                  Нельзя отправить лида
                </div>
                <p className="mt-2 leading-6">{previewError}</p>
              </div>
            ) : null}

            <section className="rounded-xl border border-white/5 bg-white/[0.02]">
              <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">Live JSON Preview</h3>
                  <p className="text-xs text-gray-500">
                    {selectedPartner ? selectedPartner.postback_url : 'Выберите партнёра'}
                  </p>
                </div>
                {isPreviewLoading ? (
                  <LoaderCircle size={17} className="animate-spin text-gray-500" />
                ) : null}
              </div>
              <pre className="max-h-[420px] overflow-auto rounded-b-xl bg-[#0a0f1d] p-3 text-xs leading-5 text-gray-200">
                {preview ? formatJson(preview.payload) : isPreviewLoading ? 'Загрузка preview...' : '{}'}
              </pre>
            </section>

            {submitError ? (
              <div className="rounded-xl border border-red-400/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                {submitError}
              </div>
            ) : null}

            {statusCopy ? (
              <div
                className={`rounded-xl border px-4 py-3 text-sm ${
                  statusCopy.tone === 'success'
                    ? 'border-emerald-400/25 bg-emerald-500/10 text-emerald-100'
                    : statusCopy.tone === 'duplicate'
                      ? 'border-orange-400/25 bg-orange-500/10 text-orange-100'
                      : statusCopy.tone === 'failed'
                        ? 'border-red-400/25 bg-red-500/10 text-red-100'
                        : 'border-sky-400/25 bg-sky-500/10 text-sky-100'
                }`}
              >
                <div className="flex items-center gap-2 font-semibold">
                  {statusCopy.tone === 'success' ? (
                    <CheckCircle2 size={17} />
                  ) : statusCopy.tone === 'pending' ? (
                    <LoaderCircle size={17} className="animate-spin" />
                  ) : (
                    <AlertTriangle size={17} />
                  )}
                  {statusCopy.title}
                </div>
                {statusCopy.body ? <p className="mt-2 leading-6">{statusCopy.body}</p> : null}
              </div>
            ) : null}

            <section className="rounded-xl border border-white/5 bg-white/[0.02]">
              <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
                <h3 className="text-sm font-semibold text-white">История отправок</h3>
                {isSubmissionsLoading ? <LoaderCircle size={16} className="animate-spin text-gray-500" /> : null}
              </div>
              {submissions.length === 0 ? (
                <div className="px-4 py-5 text-sm text-gray-500">Отправок по этому лиду ещё нет.</div>
              ) : (
                <div className="divide-y divide-white/5">
                  {submissions.map((item) => {
                    const partner = partners.find((partnerItem) => partnerItem.id === item.partner_integration_id)
                    return (
                      <div key={item.id} className="px-4 py-3 text-sm">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-medium text-gray-100">{partner?.name ?? 'Партнёр'}</span>
                          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs text-gray-300">
                            {item.status}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-gray-500">
                          {formatDateTime(item.completed_at ?? item.submitted_at)}
                          {item.partner_status ? ` · ${item.partner_status}` : ''}
                        </div>
                        {item.partner_feedback ? (
                          <p className="mt-2 rounded-lg border border-white/5 bg-black/15 px-3 py-2 text-xs leading-5 text-gray-300">
                            {item.partner_feedback}
                          </p>
                        ) : item.error_message ? (
                          <p className="mt-2 rounded-lg border border-red-300/15 bg-red-500/10 px-3 py-2 text-xs leading-5 text-red-100">
                            {item.error_message}
                          </p>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              )}
            </section>
          </div>
        </div>

        <footer className="shrink-0 border-t border-white/5 px-5 py-4">
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="inline-flex min-h-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] px-4 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white disabled:opacity-50"
            >
              Закрыть
            </button>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              disabled={!canSubmit}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSubmitting ? <LoaderCircle size={17} className="animate-spin" /> : <Send size={17} />}
              Подтвердить и отправить
            </button>
          </div>
        </footer>
      </aside>
    </div>
  )
}

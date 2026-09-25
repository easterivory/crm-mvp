import { AlertTriangle, ChevronDown, ExternalLink, MessageSquare, UsersRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useProjectBotSelection } from '../../../shared/lib'

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
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Дата неизвестна'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
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

function TelegramAddress({ username }: { username: string | null | undefined }) {
  const normalized = username?.trim().replace(/^@/, '')
  if (!normalized || !/^[a-zA-Z0-9_]+$/.test(normalized)) return null
  return <a href={`https://telegram.me/${encodeURIComponent(normalized)}`} target="_blank" rel="noopener noreferrer"
    className="inline-flex max-w-full items-center gap-1 text-accent-200 underline underline-offset-2">
    <span className="break-all">@{normalized}</span><ExternalLink size={12} className="shrink-0" />
  </a>
}

export default function DuplicateWarning({
  leadId,
  projectId,
  className = '',
}: DuplicateWarningProps) {
  const navigate = useNavigate()
  const { setSelectedProjectId, setSelectedBotIds } = useProjectBotSelection()
  const [duplicates, setDuplicates] = useState<DuplicateLeadDetail[]>([])
  const [isExpanded, setIsExpanded] = useState(false)
  const [hasError, setHasError] = useState(false)
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let isMounted = true

    setDuplicates([])
    setIsExpanded(false)
    setHasError(false)

    fetchLeadDuplicates(leadId, projectId, controller.signal)
      .then((items) => {
        if (isMounted) {
          setDuplicates(items)
          setIsExpanded(items.length === 1)
        }
      })
      .catch((err: unknown) => {
        if (getCancelCode(err) !== 'ERR_CANCELED' && isMounted) {
          setDuplicates([])
          setHasError(true)
        }
      })

    return () => {
      isMounted = false
      controller.abort()
    }
  }, [leadId, projectId, retry])

  if (hasError) {
    return <div role="status" className={`min-w-0 text-xs text-gray-400 ${className}`}>
      Не удалось проверить совпадения.{' '}
      <button type="button" onClick={() => setRetry((value) => value + 1)} className="underline underline-offset-2">Повторить</button>
    </div>
  }

  if (duplicates.length === 0) {
    return null
  }

  const hasSameTelegramUser = duplicates.some((item) => item.matched_fields.includes('telegram_id'))
  const openDialog = (duplicate: DuplicateLeadDetail) => {
    if (!duplicate.chat_id || !duplicate.project_id) return
    // Finish scope-change effects before opening the destination chat.
    flushSync(() => {
      setSelectedProjectId(duplicate.project_id!)
      setSelectedBotIds([])
    })
    navigate(`/chats?chat_id=${encodeURIComponent(duplicate.chat_id)}`)
  }

  return (
    <section aria-label="Совпадения лида" className={`min-w-0 border-y border-amber-300/25 bg-amber-400/5 [overflow-wrap:anywhere] ${className}`}>
      <div className="px-3 py-3">
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex min-w-0 items-center gap-3">
            <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-200/35 bg-amber-300/15 text-amber-100">
              {hasSameTelegramUser ? <UsersRound size={18} /> : <AlertTriangle size={18} />}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-amber-50">{hasSameTelegramUser ? 'Другие диалоги и совпадения' : 'Возможный дубль'}</p>
              <p className="truncate text-xs text-amber-100/75">
                Найдено совпадений: {duplicates.length}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsExpanded((current) => !current)}
            aria-expanded={isExpanded}
            className="inline-flex min-h-8 w-full items-center justify-between gap-2 text-left text-xs font-medium text-amber-100"
          >
            {isExpanded ? 'Скрыть совпадения' : `Показать совпадения (${duplicates.length})`}
            <ChevronDown
              size={15}
              className={`shrink-0 transition ${isExpanded ? 'rotate-180' : ''}`}
            />
          </button>
        </div>
      </div>

      {isExpanded ? (
        <div className="max-h-80 overflow-y-auto border-t border-amber-100/15 px-3 py-3">
          <div className="space-y-3">
            {duplicates.map((duplicate) => (
              <article
                key={`${duplicate.lead_id}-${duplicate.match_type}`}
                className="min-w-0 border-b border-amber-100/15 pb-3 last:border-0 last:pb-0"
              >
                <div className="flex min-w-0 flex-col gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-100">{duplicate.lead_name || duplicate.username || 'Лид без имени'}</p>
                    <p className="mt-1 text-xs text-gray-300">
                      {duplicate.matched_fields.includes('telegram_id') ? 'Тот же Telegram-пользователь' : 'Совпадение данных, личность не подтверждена'}
                    </p>
                    <p className="text-sm font-semibold text-amber-50">
                      {matchCopy(duplicate)}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-amber-100/75">
                      Проект: {duplicate.project_name}
                    </p>
                    <p className="text-xs leading-5 text-amber-100/75">
                      {duplicate.transport_type === 'user_mtproto' ? 'Именной аккаунт' : 'Бот'}: {duplicate.bot_name ?? 'Не указан'}
                    </p>
                    <div className="text-xs"><TelegramAddress username={duplicate.bot_username} /></div>
                    <div className="mt-2 space-y-1 text-xs text-gray-300">
                      <p>Telegram ID лида: {duplicate.telegram_id || 'Не сохранён'}</p>
                      <div>Лид: <TelegramAddress username={duplicate.username} />{!duplicate.username ? 'username не сохранён' : null}</div>
                    </div>
                  </div>
                  <span className="w-fit rounded-full border border-amber-100/20 bg-amber-300/10 px-2 py-1 text-xs font-medium text-amber-50">
                    Статус: {leadStatusCopy(duplicate)}
                  </span>
                </div>

                <div className="mt-3 border-l-2 border-accent-300/40 pl-2 text-xs leading-5">
                  <p className="text-gray-400">Рекламный источник этого диалога</p>
                  <p className="text-gray-100">{duplicate.tracking_title || duplicate.tracking_code || (duplicate.tracking_source === 'ambiguous' ? 'В истории несколько ссылок' : 'Не сохранён')}</p>
                  {duplicate.tracking_code ? <p className="break-all text-gray-300">Код: {duplicate.tracking_code}</p> : null}
                  {duplicate.tracking_source === 'message_history' ? <p className="text-gray-400">По истории текущего обращения</p> : null}
                </div>
                {duplicate.chat_id && duplicate.project_id && !duplicate.is_deleted && !duplicate.is_trash ? (
                  <button type="button" onClick={() => openDialog(duplicate)} className="mt-2 inline-flex min-h-8 items-center gap-2 text-xs font-medium text-accent-200">
                    <MessageSquare size={14} className="shrink-0" />Открыть диалог
                  </button>
                ) : null}

                <p className="mt-2 text-xs text-amber-100/65">
                  Создан: {formatDateTime(duplicate.created_at)}
                </p>

                <div className="mt-3 border-t border-white/5 pt-2">
                  <p className="text-xs font-medium uppercase tracking-wide text-amber-100/70">
                    История подач совпавшего лида
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

import {
  AlertTriangle,
  CheckCircle2,
  GitBranch,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import axios from 'axios'

import { fetchFunnelTrace } from '../api'
import type { FunnelRuntimeLog } from '../types'

type FunnelTraceWidgetProps = {
  chatId: string | null
  projectId: string | null
  currentStepId?: string | null
  currentStepTitle?: string | null
  isPaused?: boolean
  isManualReview?: boolean
  refreshKey?: number
  actions?: ReactNode
}

function formatTraceTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
  }).format(new Date(value))
}

function getTraceError(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail) {
      return detail
    }
    if (err.response?.status === 404) {
      return 'История воронки для этого чата не найдена.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return 'Не удалось загрузить путь в воронке.'
}

export default function FunnelTraceWidget({
  chatId,
  projectId,
  currentStepId = null,
  currentStepTitle = null,
  isPaused = false,
  isManualReview = false,
  refreshKey = 0,
  actions,
}: FunnelTraceWidgetProps) {
  const [logs, setLogs] = useState<FunnelRuntimeLog[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [isOpen, setIsOpen] = useState(true)

  const latestStatus = logs[logs.length - 1]?.status ?? null
  const currentSuccessIndex = useMemo(() => {
    if (latestStatus !== 'success') {
      return -1
    }
    for (let index = logs.length - 1; index >= 0; index -= 1) {
      if (logs[index].status === 'success') {
        return index
      }
    }
    return -1
  }, [latestStatus, logs])

  const loadTrace = useCallback(async () => {
    if (!chatId || !projectId) {
      setLogs([])
      setError('')
      return
    }

    setIsLoading(true)
    setError('')
    try {
      setLogs(await fetchFunnelTrace(chatId, projectId))
    } catch (err) {
      setLogs([])
      setError(getTraceError(err))
    } finally {
      setIsLoading(false)
    }
  }, [chatId, projectId])

  useEffect(() => {
    void loadTrace()
  }, [loadTrace, refreshKey])

  return (
    <section className="rounded-xl border border-white/5 bg-white/[0.03]">
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="inline-flex min-w-0 items-center gap-2">
          <GitBranch size={16} className="shrink-0 text-accent-200" />
          <span className="truncate text-sm font-medium text-white">Путь в воронке</span>
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-xs text-gray-400">
          {logs.length}
        </span>
      </button>

      {isOpen ? (
        <div className="border-t border-white/5 px-4 py-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-xs leading-5 text-gray-500">
              Хронология переходов клиента по шагам сценария.
            </p>
            <button
              type="button"
              title="Обновить путь"
              onClick={() => void loadTrace()}
              disabled={!chatId || !projectId || isLoading}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-gray-400 transition hover:border-accent-300/40 hover:text-accent-100 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isLoading ? (
                <LoaderCircle size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )}
            </button>
          </div>

          {currentStepId ? (
            <div className={`mb-3 rounded-lg border p-3 ${
              isManualReview
                ? 'border-amber-300/25 bg-amber-300/10'
                : isPaused
                  ? 'border-yellow-300/20 bg-yellow-300/[0.07]'
                  : 'border-sky-300/20 bg-sky-300/[0.07]'
            }`}>
              <p className="text-xs font-medium uppercase tracking-wide text-gray-400">
                Текущий шаг
              </p>
              <p className="mt-1 text-sm font-semibold text-white">
                {currentStepTitle || currentStepId}
              </p>
              <p className="mt-1 text-xs text-gray-400">
                {isManualReview
                  ? 'На ручной проверке менеджером'
                  : isPaused
                    ? 'Воронка приостановлена'
                    : 'Воронка выполняется'}
              </p>
            </div>
          ) : null}

          {isLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <LoaderCircle size={15} className="animate-spin" />
              Загрузка пути
            </div>
          ) : null}

          {!isLoading && error ? (
            <div className="rounded-lg border border-red-300/20 bg-red-500/10 p-3 text-sm text-red-100">
              {error}
            </div>
          ) : null}

          {!isLoading && !error && logs.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] p-3 text-sm text-gray-500">
              Клиент еще не проходил активную воронку.
            </div>
          ) : null}

          {!isLoading && !error && logs.length > 0 ? (
            <ol className="space-y-0">
              {logs.map((log, index) => {
                const isCurrent = currentStepId
                  ? log.step_id === currentStepId
                    && !logs.slice(index + 1).some((item) => item.step_id === currentStepId)
                  : index === currentSuccessIndex
                const isFailed = log.status === 'failed'
                const isLast = index === logs.length - 1
                const title = log.step_title || log.step_key
                return (
                  <li key={`${log.step_id}:${log.created_at}:${index}`} className="relative flex gap-3 pb-4 last:pb-0">
                    {!isLast ? (
                      <span
                        className={`absolute left-[13px] top-8 h-[calc(100%-2rem)] w-px ${
                          isFailed ? 'bg-red-300/30' : 'bg-white/10'
                        }`}
                      />
                    ) : null}
                    <span
                      className={`relative z-10 mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
                        isFailed
                          ? 'border-red-300/40 bg-red-500/15 text-red-100'
                          : isCurrent
                            ? 'border-sky-300/60 bg-sky-400/15 text-sky-100 shadow-[0_0_18px_rgba(56,189,248,0.25)]'
                            : 'border-emerald-300/30 bg-emerald-400/10 text-emerald-100'
                      }`}
                    >
                      {isFailed ? (
                        <AlertTriangle size={14} />
                      ) : (
                        <CheckCircle2 size={14} className={isCurrent ? 'animate-pulse' : ''} />
                      )}
                    </span>
                    <div
                      className={`min-w-0 flex-1 rounded-lg border p-3 ${
                        isFailed
                          ? 'border-red-300/20 bg-red-500/10'
                          : isCurrent
                            ? 'border-sky-300/25 bg-sky-400/10'
                            : 'border-white/5 bg-white/[0.025]'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p
                            className={`truncate text-sm font-medium ${
                              isFailed
                                ? 'text-red-50'
                                : isCurrent
                                  ? 'text-sky-50'
                                  : 'text-gray-100'
                            }`}
                          >
                            {title}
                          </p>
                          <p className="mt-1 truncate text-xs text-gray-500">{log.step_key}</p>
                        </div>
                        <span className="shrink-0 text-xs text-gray-500">
                          {formatTraceTime(log.created_at)}
                        </span>
                      </div>
                      {isCurrent ? (
                        <p className="mt-2 text-xs leading-5 text-sky-100/85">
                          Клиент сейчас находится на этом шаге.
                        </p>
                      ) : null}
                      {isFailed && log.error_message ? (
                        <p className="mt-2 rounded-md border border-red-300/20 bg-red-950/30 p-2 text-xs leading-5 text-red-100">
                          {log.error_message}
                        </p>
                      ) : null}
                    </div>
                  </li>
                )
              })}
            </ol>
          ) : null}

          {actions ? (
            <div className="mt-4 border-t border-white/5 pt-4">
              {actions}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

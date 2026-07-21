import axios from 'axios'
import {
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  FileSpreadsheet,
  Import as ImportIcon,
  LoaderCircle,
  Plus,
  RefreshCw,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import Modal from '../../../shared/ui/Modal'
import {
  createBotLeadImportTemplate,
  executeBotLeadImport,
  fetchBotLeadImports,
  previewBotLeadImport,
} from '../api'
import type { Bot, BotLeadImport, LeadImportPreview } from '../types'

type LeadImportModalProps = {
  bot: Bot
  projectId: string
  onClose: () => void
}

const statusLabels: Record<BotLeadImport['status'], string> = {
  created: 'Ожидает проверки',
  validated: 'Проверена',
  completed: 'Импорт завершён',
  failed: 'Ошибка',
}

function getErrorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (error.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')
}

export default function LeadImportModal({ bot, projectId, onClose }: LeadImportModalProps) {
  const [imports, setImports] = useState<BotLeadImport[]>([])
  const [selectedImportId, setSelectedImportId] = useState<string | null>(null)
  const [preview, setPreview] = useState<LeadImportPreview | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [isImporting, setIsImporting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const selectedImport = useMemo(
    () => imports.find((item) => item.id === selectedImportId) ?? null,
    [imports, selectedImportId],
  )

  const loadImports = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const nextImports = await fetchBotLeadImports(bot.id, projectId)
      setImports(nextImports)
      setSelectedImportId((current) => {
        if (current && nextImports.some((item) => item.id === current)) {
          return current
        }
        return nextImports.find((item) => item.status !== 'completed')?.id
          ?? nextImports[0]?.id
          ?? null
      })
    } catch (requestError) {
      setError(getErrorMessage(requestError, 'Не удалось загрузить историю переносов.'))
    } finally {
      setIsLoading(false)
    }
  }, [bot.id, projectId])

  useEffect(() => {
    void loadImports()
  }, [loadImports])

  useEffect(() => {
    setPreview(null)
    setNotice('')
  }, [selectedImportId])

  const handleCreateTemplate = async () => {
    if (isCreating) {
      return
    }
    const tableWindow = window.open('about:blank', '_blank')
    if (tableWindow) {
      tableWindow.opener = null
    }
    setIsCreating(true)
    setError('')
    setNotice('')
    try {
      const created = await createBotLeadImportTemplate(bot.id, projectId)
      setImports((current) => [created, ...current])
      setSelectedImportId(created.id)
      if (tableWindow) {
        tableWindow.location.replace(created.spreadsheet_url)
        setNotice('Таблица создана и открыта в новой вкладке.')
      } else {
        setNotice('Таблица создана. Откройте её кнопкой ниже.')
      }
    } catch (requestError) {
      tableWindow?.close()
      setError(getErrorMessage(requestError, 'Не удалось создать Google-таблицу.'))
    } finally {
      setIsCreating(false)
    }
  }

  const handlePreview = async () => {
    if (!selectedImport || isPreviewing || selectedImport.status === 'completed') {
      return
    }
    setIsPreviewing(true)
    setError('')
    setNotice('')
    try {
      const result = await previewBotLeadImport(bot.id, selectedImport.id, projectId)
      setPreview(result)
      await loadImports()
      setSelectedImportId(selectedImport.id)
      setNotice(result.can_import ? 'Таблица готова к импорту.' : 'Исправьте ошибки в таблице.')
    } catch (requestError) {
      setError(getErrorMessage(requestError, 'Не удалось проверить таблицу.'))
    } finally {
      setIsPreviewing(false)
    }
  }

  const handleExecute = async () => {
    if (!selectedImport || !preview?.can_import || isImporting) {
      return
    }
    if (!window.confirm(`Импортировать ${preview.create_count} лидов в бота «${bot.name}»?`)) {
      return
    }
    setIsImporting(true)
    setError('')
    setNotice('')
    try {
      const result = await executeBotLeadImport(
        bot.id,
        selectedImport.id,
        projectId,
        preview.checksum,
      )
      setPreview(null)
      await loadImports()
      setSelectedImportId(result.import_batch.id)
      setNotice(
        `Импорт завершён: создано ${result.created_count}, пропущено ${result.skipped_count}.`,
      )
    } catch (requestError) {
      setError(getErrorMessage(requestError, 'Не удалось выполнить импорт.'))
    } finally {
      setIsImporting(false)
    }
  }

  return (
    <Modal
      title={`Перенос лидов · ${bot.name}`}
      description="Импорт из Chatterfy без повторного запуска воронки"
      onClose={onClose}
      maxWidthClassName="max-w-4xl"
    >
      <div className="space-y-4">
        {error ? (
          <div className="rounded-lg border border-red-400/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="rounded-lg border border-emerald-400/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
            {notice}
          </div>
        ) : null}

        <div className="flex flex-col gap-3 border-b border-white/10 pb-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm leading-6 text-gray-400">
            Теги указываются через запятую. Для связывания обязателен Telegram ID или username.
            Таблицу смогут редактировать все, у кого есть ссылка.
          </p>
          <button
            type="button"
            onClick={() => void handleCreateTemplate()}
            disabled={isCreating}
            className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-semibold text-[#071019] transition hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isCreating ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
            Создать таблицу
          </button>
        </div>

        {isLoading ? (
          <div className="flex min-h-40 items-center justify-center text-sm text-gray-500">
            <LoaderCircle size={18} className="mr-2 animate-spin" />
            Загрузка
          </div>
        ) : null}

        {!isLoading && imports.length === 0 ? (
          <div className="rounded-lg border border-dashed border-white/10 px-4 py-10 text-center text-sm text-gray-500">
            Создайте первую таблицу переноса.
          </div>
        ) : null}

        {imports.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.7fr)]">
            <div className="space-y-2">
              {imports.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelectedImportId(item.id)}
                  className={`w-full rounded-lg border px-3 py-3 text-left transition ${
                    selectedImportId === item.id
                      ? 'border-cyan-400/60 bg-cyan-500/10'
                      : 'border-white/10 bg-white/[0.02] hover:border-white/20'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <FileSpreadsheet size={16} className="shrink-0 text-cyan-300" />
                    <span className="min-w-0 truncate text-sm font-medium text-white">
                      {formatDate(item.created_at)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">{statusLabels[item.status]}</div>
                </button>
              ))}
            </div>

            {selectedImport ? (
              <div className="min-w-0 space-y-4 rounded-lg border border-white/10 bg-white/[0.02] p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-white">{statusLabels[selectedImport.status]}</div>
                    {selectedImport.status === 'completed' ? (
                      <div className="mt-1 text-xs text-gray-500">
                        Создано {selectedImport.imported_count} · пропущено {selectedImport.skipped_count}
                      </div>
                    ) : null}
                  </div>
                  <a
                    href={selectedImport.spreadsheet_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-white/10 px-3 text-sm font-medium text-gray-200 transition hover:border-cyan-300/50 hover:text-white"
                  >
                    <ExternalLink size={15} />
                    Открыть таблицу
                  </a>
                </div>

                {selectedImport.status !== 'completed' ? (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => void handlePreview()}
                      disabled={isPreviewing || isImporting}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-cyan-300/30 bg-cyan-500/10 px-4 text-sm font-semibold text-cyan-100 transition hover:border-cyan-300/60 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isPreviewing ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                      Проверить
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleExecute()}
                      disabled={!preview?.can_import || isImporting || isPreviewing}
                      className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-[#07120d] transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {isImporting ? <LoaderCircle size={16} className="animate-spin" /> : <ImportIcon size={16} />}
                      Импортировать
                    </button>
                  </div>
                ) : null}

                {preview ? (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {[
                        ['Строк', preview.total_rows],
                        ['Будет создано', preview.create_count],
                        ['Пропущено', preview.skip_count],
                        ['Ошибок', preview.error_count],
                      ].map(([label, value]) => (
                        <div key={String(label)} className="rounded-lg border border-white/10 bg-[#090d16] px-3 py-2">
                          <div className="text-[11px] text-gray-500">{label}</div>
                          <div className="mt-1 text-lg font-semibold text-white">{value}</div>
                        </div>
                      ))}
                    </div>

                    {preview.new_tags.length > 0 || preview.new_statuses.length > 0 ? (
                      <div className="rounded-lg border border-cyan-400/20 bg-cyan-500/5 px-3 py-2 text-xs leading-5 text-cyan-100">
                        {preview.new_tags.length > 0 ? `Новые теги: ${preview.new_tags.join(', ')}. ` : ''}
                        {preview.new_statuses.length > 0 ? `Новые статусы: ${preview.new_statuses.join(', ')}.` : ''}
                      </div>
                    ) : null}

                    {preview.issues.length > 0 ? (
                      <div className="max-h-64 space-y-2 overflow-y-auto">
                        {preview.issues.map((issue, index) => (
                          <div
                            key={`${issue.row}-${issue.field}-${index}`}
                            className={`flex gap-2 rounded-lg border px-3 py-2 text-xs leading-5 ${
                              issue.level === 'error'
                                ? 'border-red-400/20 bg-red-500/10 text-red-100'
                                : 'border-amber-400/20 bg-amber-500/10 text-amber-100'
                            }`}
                          >
                            {issue.level === 'error'
                              ? <AlertCircle size={15} className="mt-0.5 shrink-0" />
                              : <CheckCircle2 size={15} className="mt-0.5 shrink-0" />}
                            <span>Строка {issue.row}, {issue.field}: {issue.message}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

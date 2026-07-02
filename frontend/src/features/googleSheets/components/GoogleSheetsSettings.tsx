import axios from 'axios'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  LoaderCircle,
  Save,
  SendHorizontal,
} from 'lucide-react'
import { type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useState } from 'react'

import {
  fetchGoogleSheetsConfig,
  fetchLeadStatusOptions,
  testGoogleSheetsConnection,
  updateGoogleSheetsConfig,
} from '../api'
import type { GoogleSheetsConfig, LeadStatusOption } from '../types'
import { fetchBots, type Bot } from '../../bots'

type GoogleSheetsSettingsProps = {
  projectId: string | null
}

type Banner = {
  tone: 'success' | 'error'
  message: string
}

const exportFieldOptions = [
  ['created_at', 'Дата создания'],
  ['name', 'Имя'],
  ['phone', 'Телефон'],
  ['telegram', 'Telegram'],
  ['country', 'Страна'],
  ['age', 'Возраст'],
  ['tracking_link', 'Трекинг-ссылка'],
  ['buyer', 'Баер'],
  ['status', 'Статус'],
  ['cpl', 'CPL'],
  ['score', 'Качество лида'],
  ['manager', 'Менеджер'],
  ['bot', 'Бот'],
  ['chat_id', 'CRM Chat ID'],
  ['telegram_id', 'Telegram ID'],
] as const

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function emptyForm(config?: GoogleSheetsConfig | null) {
  return {
    spreadsheetId: config?.spreadsheet_id ?? '',
    sheetName: config?.sheet_name ?? 'Лиды',
    isEnabled: config?.is_enabled ?? false,
    triggerStatuses: config?.trigger_statuses ?? [],
    botIds: config?.bot_ids ?? [],
    exportFields: config?.export_fields ?? exportFieldOptions.slice(0, 11).map(([key]) => key),
    customFieldKeys: config?.custom_field_keys?.join(', ') ?? '',
  }
}

export default function GoogleSheetsSettings({ projectId }: GoogleSheetsSettingsProps) {
  const [config, setConfig] = useState<GoogleSheetsConfig | null>(null)
  const [statuses, setStatuses] = useState<LeadStatusOption[]>([])
  const [bots, setBots] = useState<Bot[]>([])
  const [spreadsheetId, setSpreadsheetId] = useState('')
  const [sheetName, setSheetName] = useState('Лиды')
  const [isEnabled, setIsEnabled] = useState(false)
  const [triggerStatuses, setTriggerStatuses] = useState<string[]>([])
  const [botIds, setBotIds] = useState<string[]>([])
  const [exportFields, setExportFields] = useState<string[]>([])
  const [customFieldKeys, setCustomFieldKeys] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [isStatusesOpen, setIsStatusesOpen] = useState(false)
  const [banner, setBanner] = useState<Banner | null>(null)
  const [copyNotice, setCopyNotice] = useState('')

  const serviceAccountEmail = config?.service_account_email ?? ''

  const selectedStatusLabels = useMemo(() => {
    if (triggerStatuses.length === 0) {
      return 'Выберите статусы'
    }
    const names = statuses
      .filter((status) => triggerStatuses.includes(status.id))
      .map((status) => status.name)
    return names.length > 0 ? names.join(', ') : `${triggerStatuses.length} выбрано`
  }, [statuses, triggerStatuses])

  const loadSettings = useCallback(async () => {
    if (!projectId) {
      setConfig(null)
      setStatuses([])
      setBots([])
      const form = emptyForm(null)
      setSpreadsheetId(form.spreadsheetId)
      setSheetName(form.sheetName)
      setIsEnabled(form.isEnabled)
      setTriggerStatuses(form.triggerStatuses)
      setBotIds(form.botIds)
      setExportFields(form.exportFields)
      setCustomFieldKeys(form.customFieldKeys)
      return
    }

    setIsLoading(true)
    setBanner(null)
    try {
      const [configData, statusItems, botItems] = await Promise.all([
        fetchGoogleSheetsConfig(projectId),
        fetchLeadStatusOptions(),
        fetchBots(projectId),
      ])
      setConfig(configData)
      setStatuses(statusItems)
      setBots(botItems)
      const form = emptyForm(configData)
      setSpreadsheetId(form.spreadsheetId)
      setSheetName(form.sheetName)
      setIsEnabled(form.isEnabled)
      setTriggerStatuses(form.triggerStatuses)
      setBotIds(form.botIds)
      setExportFields(form.exportFields)
      setCustomFieldKeys(form.customFieldKeys)
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось загрузить настройки Google Таблиц.'),
      })
    } finally {
      setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadSettings()
  }, [loadSettings])

  const toggleStatus = (statusId: string) => {
    setTriggerStatuses((current) => {
      if (current.includes(statusId)) {
        return current.filter((item) => item !== statusId)
      }
      return [...current, statusId]
    })
  }

  const toggleListValue = (
    value: string,
    setter: Dispatch<SetStateAction<string[]>>,
  ) => setter((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value])

  const handleCopyEmail = async () => {
    if (!serviceAccountEmail) {
      return
    }
    await navigator.clipboard.writeText(serviceAccountEmail)
    setCopyNotice('Email скопирован.')
    window.setTimeout(() => setCopyNotice(''), 1800)
  }

  const handleSave = async () => {
    if (!projectId || isSaving) {
      return
    }
    if (!sheetName.trim()) {
      setBanner({ tone: 'error', message: 'Название листа не может быть пустым.' })
      return
    }

    setIsSaving(true)
    setBanner(null)
    try {
      const updated = await updateGoogleSheetsConfig(projectId, {
        spreadsheet_id: spreadsheetId.trim() || null,
        sheet_name: sheetName.trim(),
        is_enabled: isEnabled,
        trigger_statuses: triggerStatuses,
        bot_ids: botIds,
        export_fields: exportFields,
        custom_field_keys: customFieldKeys.split(',').map((item) => item.trim()).filter(Boolean),
      })
      setConfig(updated)
      const form = emptyForm(updated)
      setSpreadsheetId(form.spreadsheetId)
      setSheetName(form.sheetName)
      setIsEnabled(form.isEnabled)
      setTriggerStatuses(form.triggerStatuses)
      setBotIds(form.botIds)
      setExportFields(form.exportFields)
      setCustomFieldKeys(form.customFieldKeys)
      setBanner({ tone: 'success', message: 'Настройки Google Таблиц сохранены.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось сохранить настройки Google Таблиц.'),
      })
    } finally {
      setIsSaving(false)
    }
  }

  const handleTest = async () => {
    if (!projectId || isTesting) {
      return
    }

    setIsTesting(true)
    setBanner(null)
    try {
      const updated = await updateGoogleSheetsConfig(projectId, {
        spreadsheet_id: spreadsheetId.trim() || null,
        sheet_name: sheetName.trim(),
        is_enabled: isEnabled,
        trigger_statuses: triggerStatuses,
        bot_ids: botIds,
        export_fields: exportFields,
        custom_field_keys: customFieldKeys.split(',').map((item) => item.trim()).filter(Boolean),
      })
      setConfig(updated)
      const result = await testGoogleSheetsConnection(projectId)
      setBanner({
        tone: result.success ? 'success' : 'error',
        message: result.message,
      })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Ошибка подключения к Google Таблице.'),
      })
    } finally {
      setIsTesting(false)
    }
  }

  if (!projectId) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-5 text-sm text-zinc-500">
        Выберите проект для настройки Google Таблиц.
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-zinc-100">Google Таблицы</h2>
        <p className="mt-1 text-sm text-zinc-500">
          Автоматический экспорт лидов при переходе в выбранные статусы. Включите
          интеграцию, выберите статусы и проверьте подключение после сохранения.
        </p>
      </div>

      <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-emerald-100">
              Для интеграции расшарьте вашу Google Таблицу на email:
            </p>
            <p className="mt-2 break-all rounded-lg border border-emerald-400/20 bg-zinc-950/60 px-3 py-2 font-mono text-sm text-emerald-200">
              {serviceAccountEmail || 'GOOGLE_SERVICE_ACCOUNT_JSON не настроен'}
            </p>
            <p className="mt-2 text-sm text-emerald-100/70">
              Дайте сервисному аккаунту права Редактора (Editor). Если email не показан,
              переменная GOOGLE_SERVICE_ACCOUNT_JSON не настроена на сервере.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void handleCopyEmail()}
            disabled={!serviceAccountEmail}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg border border-emerald-400/30 px-4 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-400/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Copy size={16} />
            {copyNotice || 'Скопировать'}
          </button>
        </div>
      </div>

      {banner ? (
        <div
          className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${
            banner.tone === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
              : 'border-red-500/30 bg-red-500/10 text-red-100'
          }`}
        >
          {banner.tone === 'success' ? (
            <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          )}
          <span>{banner.message}</span>
        </div>
      ) : null}

      <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-10 text-sm text-zinc-500">
            <LoaderCircle size={18} className="mr-2 animate-spin" />
            Загрузка Google Таблиц
          </div>
        ) : (
          <>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                ID Google Таблицы (Spreadsheet ID)
              </span>
              <input
                value={spreadsheetId}
                onChange={(event) => setSpreadsheetId(event.target.value)}
                maxLength={255}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                placeholder="1AbCDeFg..."
              />
              <p className="mt-1 text-xs text-zinc-500">
                ID находится в URL между /d/ и /edit.
              </p>
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">
                  Название листа
                </span>
                <input
                  value={sheetName}
                  onChange={(event) => setSheetName(event.target.value)}
                  maxLength={255}
                  required
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                  placeholder="Лиды"
                />
              </label>

              <div>
                <span className="mb-1 block text-sm font-medium text-zinc-300">
                  Активность интеграции
                </span>
                <button
                  type="button"
                  onClick={() => setIsEnabled((value) => !value)}
                  aria-pressed={isEnabled}
                  className={`flex h-10 w-full items-center justify-between rounded-lg border px-3 text-sm transition ${
                    isEnabled
                      ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-100'
                      : 'border-zinc-700 bg-zinc-950 text-zinc-400'
                  }`}
                >
                  <span>{isEnabled ? 'Включена' : 'Выключена'}</span>
                  <span
                    className={`relative h-5 w-9 rounded-full transition ${
                      isEnabled ? 'bg-emerald-400' : 'bg-zinc-700'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-4 w-4 rounded-full bg-zinc-950 transition ${
                        isEnabled ? 'left-4' : 'left-0.5'
                      }`}
                    />
                  </span>
                </button>
              </div>
            </div>

            <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
              <div>
                <p className="text-sm font-medium text-zinc-200">Боты для экспорта</p>
                <p className="mt-1 text-xs text-zinc-500">
                  Пустой выбор означает все боты проекта.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {bots.map((bot) => (
                  <label key={bot.id} className="flex cursor-pointer items-center gap-3 rounded-lg border border-zinc-800 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-700">
                    <input type="checkbox" checked={botIds.includes(bot.id)} onChange={() => toggleListValue(bot.id, setBotIds)} className="h-4 w-4 accent-emerald-500" />
                    <span className="min-w-0 truncate">{bot.name}{bot.bot_username ? ` · @${bot.bot_username}` : ''}</span>
                  </label>
                ))}
                {bots.length === 0 ? <p className="text-sm text-zinc-500">В проекте пока нет ботов.</p> : null}
              </div>
            </div>

            <div className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
              <div>
                <p className="text-sm font-medium text-zinc-200">Колонки выгрузки</p>
                <p className="mt-1 text-xs text-zinc-500">
                  Порядок колонок соответствует порядку ниже. Для изменённого набора используйте пустой лист.
                </p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {exportFieldOptions.map(([key, label]) => (
                  <label key={key} className="flex cursor-pointer items-center gap-3 rounded-lg border border-zinc-800 px-3 py-2 text-sm text-zinc-200 transition hover:border-zinc-700">
                    <input type="checkbox" checked={exportFields.includes(key)} onChange={() => toggleListValue(key, setExportFields)} className="h-4 w-4 accent-emerald-500" />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Дополнительные поля лида</span>
                <input
                  value={customFieldKeys}
                  onChange={(event) => setCustomFieldKeys(event.target.value)}
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                  placeholder="city, budget, source_detail"
                />
                <p className="mt-1 text-xs text-zinc-500">Ключи custom_fields через запятую.</p>
              </label>
            </div>

            <div className="relative">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Статусы для выгрузки
              </span>
              <button
                type="button"
                onClick={() => setIsStatusesOpen((value) => !value)}
                className="flex min-h-10 w-full items-center justify-between gap-3 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-left text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
              >
                <span className="min-w-0 truncate">{selectedStatusLabels}</span>
                <ChevronDown
                  size={16}
                  className={`shrink-0 text-zinc-500 transition ${
                    isStatusesOpen ? 'rotate-180' : ''
                  }`}
                />
              </button>
              {isStatusesOpen ? (
                <div className="absolute z-20 mt-2 max-h-72 w-full overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-950 p-2 shadow-2xl">
                  {statuses.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-zinc-500">
                      Статусы пока не настроены.
                    </div>
                  ) : (
                    statuses.map((status) => (
                      <label
                        key={status.id}
                        className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-zinc-200 transition hover:bg-zinc-900"
                      >
                        <input
                          type="checkbox"
                          checked={triggerStatuses.includes(status.id)}
                          onChange={() => toggleStatus(status.id)}
                          className="h-4 w-4 accent-emerald-500"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{status.name}</span>
                          <span className="block truncate font-mono text-xs text-zinc-500">
                            {status.code}
                          </span>
                        </span>
                      </label>
                    ))
                  )}
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-3 pt-2">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={isSaving || !sheetName.trim() || exportFields.length === 0}
                className="inline-flex h-10 items-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSaving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                Сохранить настройки
              </button>
              <button
                type="button"
                onClick={() => void handleTest()}
                disabled={isTesting || !spreadsheetId.trim()}
                className="inline-flex h-10 items-center gap-2 rounded-lg border border-zinc-700 px-4 text-sm font-semibold text-zinc-200 transition hover:border-emerald-500/60 hover:text-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isTesting ? (
                  <LoaderCircle size={16} className="animate-spin" />
                ) : (
                  <SendHorizontal size={16} />
                )}
                Проверить подключение
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

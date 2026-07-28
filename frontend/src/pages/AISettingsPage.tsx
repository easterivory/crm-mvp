import axios from 'axios'
import {
  BrainCircuit,
  CheckCircle2,
  CircleDollarSign,
  KeyRound,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  X,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  createAIProvider,
  deleteAIProvider,
  fetchAIProviderModels,
  fetchAIProviders,
  fetchAIProjectSettings,
  fetchAIUsage,
  fetchAIUsageSummary,
  testAIProvider,
  updateAIProjectSettings,
  updateAIProvider,
  type AIAPIStyle,
  type AIProjectSettings,
  type AIProjectSettingsInput,
  type AIProviderConnection,
  type AIProviderConnectionInput,
  type AIUsageList,
  type AIUsageSummary,
} from '../features/ai'
import { isSuperAdminRole, useNotificationStore, useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type PricingRow = {
  id: string
  model: string
  input: string
  output: string
}

type ProviderDraft = {
  id: string | null
  preset: string
  name: string
  provider: string
  apiStyle: AIAPIStyle
  baseUrl: string
  apiKey: string
  clearApiKey: boolean
  defaultModel: string
  isActive: boolean
  timeout: string
  supportsJsonMode: boolean
  pricingRows: PricingRow[]
}

const providerPresets = [
  {
    id: 'openai',
    label: 'OpenAI',
    provider: 'openai',
    apiStyle: 'openai_compatible' as const,
    baseUrl: 'https://api.openai.com/v1',
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    provider: 'deepseek',
    apiStyle: 'openai_compatible' as const,
    baseUrl: 'https://api.deepseek.com',
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    provider: 'openrouter',
    apiStyle: 'openai_compatible' as const,
    baseUrl: 'https://openrouter.ai/api/v1',
  },
  {
    id: 'qwen',
    label: 'Qwen / DashScope',
    provider: 'qwen',
    apiStyle: 'openai_compatible' as const,
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  },
  {
    id: 'gemini',
    label: 'Google Gemini',
    provider: 'gemini',
    apiStyle: 'gemini' as const,
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta',
  },
  {
    id: 'custom',
    label: 'Другой провайдер',
    provider: 'custom',
    apiStyle: 'openai_compatible' as const,
    baseUrl: '',
  },
] as const

const fieldClass =
  'w-full rounded-lg border border-white/10 bg-background/75 px-3 py-2.5 text-base text-gray-100 outline-none ring-cyan-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm'

function dateInputValue(value: Date) {
  return value.toISOString().slice(0, 10)
}

function initialDateRange() {
  const now = new Date()
  return {
    from: dateInputValue(new Date(now.getFullYear(), now.getMonth(), 1)),
    to: dateInputValue(now),
  }
}

function emptyProviderDraft(): ProviderDraft {
  return {
    id: null,
    preset: 'openai',
    name: '',
    provider: 'openai',
    apiStyle: 'openai_compatible',
    baseUrl: 'https://api.openai.com/v1',
    apiKey: '',
    clearApiKey: false,
    defaultModel: '',
    isActive: true,
    timeout: '20',
    supportsJsonMode: true,
    pricingRows: [],
  }
}

function providerDraftFromConnection(connection: AIProviderConnection): ProviderDraft {
  const matchingPreset = providerPresets.find(
    (preset) =>
      preset.provider === connection.provider &&
      preset.apiStyle === connection.api_style,
  )
  return {
    id: connection.id,
    preset: matchingPreset?.id ?? 'custom',
    name: connection.name,
    provider: connection.provider,
    apiStyle: connection.api_style,
    baseUrl: connection.base_url,
    apiKey: '',
    clearApiKey: false,
    defaultModel: connection.default_model ?? '',
    isActive: connection.is_active,
    timeout: String(connection.request_timeout_seconds),
    supportsJsonMode: connection.supports_json_mode,
    pricingRows: Object.entries(connection.pricing).map(([model, pricing]) => ({
      id: crypto.randomUUID(),
      model,
      input: String(pricing.input_usd_per_million),
      output: String(pricing.output_usd_per_million),
    })),
  }
}

function getErrorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (Array.isArray(detail)) {
      const first = detail.find((item) => typeof item?.msg === 'string')
      if (first?.msg) return first.msg
    }
    if (error.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function settingsDraft(settings: AIProjectSettings): AIProjectSettingsInput {
  return {
    is_enabled: settings.is_enabled,
    primary_connection_id: settings.primary_connection_id,
    primary_model: settings.primary_model,
    fallback_connection_id: settings.fallback_connection_id,
    fallback_model: settings.fallback_model,
    master_prompt: settings.master_prompt,
    history_message_limit: settings.history_message_limit,
    max_context_chars: settings.max_context_chars,
    default_temperature: settings.default_temperature,
    default_max_output_tokens: settings.default_max_output_tokens,
    typing_delay_per_char_ms: settings.typing_delay_per_char_ms,
    min_delay_ms: settings.min_delay_ms,
    max_delay_ms: settings.max_delay_ms,
    daily_budget_usd: settings.daily_budget_usd,
    monthly_budget_usd: settings.monthly_budget_usd,
  }
}

function optionalNumber(value: number | string | null) {
  return value === null ? '' : String(value)
}

function money(value: number | string | null | undefined, digits = 4) {
  const parsed = Number(value ?? 0)
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: digits,
  }).format(Number.isFinite(parsed) ? parsed : 0)
}

function integer(value: number) {
  return new Intl.NumberFormat('ru-RU').format(value)
}

export default function AISettingsPage() {
  const currentUser = useAuthStore((state) => state.user)
  const { selectedProjectId } = useProjectBotSelection()
  const notify = useNotificationStore((state) => state.notify)
  const activeProjectId = selectedProjectId ?? currentUser?.project_id ?? null
  const canManageCredentials = isSuperAdminRole(currentUser?.role_name)

  const initialRange = useMemo(initialDateRange, [])
  const [providers, setProviders] = useState<AIProviderConnection[]>([])
  const [projectSettings, setProjectSettings] = useState<AIProjectSettingsInput | null>(null)
  const [usage, setUsage] = useState<AIUsageList | null>(null)
  const [usageSummary, setUsageSummary] = useState<AIUsageSummary | null>(null)
  const [dateFrom, setDateFrom] = useState(initialRange.from)
  const [dateTo, setDateTo] = useState(initialRange.to)
  const [providerDraft, setProviderDraft] = useState<ProviderDraft | null>(null)
  const [modelsByConnection, setModelsByConnection] = useState<Record<string, string[]>>({})
  const [isLoading, setIsLoading] = useState(true)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [isSavingProvider, setIsSavingProvider] = useState(false)
  const [testingProviderId, setTestingProviderId] = useState<string | null>(null)
  const [loadingModelsId, setLoadingModelsId] = useState<string | null>(null)
  const [isLoadingUsage, setIsLoadingUsage] = useState(false)
  const [error, setError] = useState('')

  const loadUsage = useCallback(async () => {
    if (!activeProjectId) {
      setUsage(null)
      setUsageSummary(null)
      return
    }
    setIsLoadingUsage(true)
    try {
      const [items, summary] = await Promise.all([
        fetchAIUsage(activeProjectId, dateFrom, dateTo),
        fetchAIUsageSummary(activeProjectId, dateFrom, dateTo),
      ])
      setUsage(items)
      setUsageSummary(summary)
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Не удалось загрузить расход AI.'))
    } finally {
      setIsLoadingUsage(false)
    }
  }, [activeProjectId, dateFrom, dateTo])

  const loadPage = useCallback(async () => {
    if (!activeProjectId) {
      setProjectSettings(null)
      setProviders([])
      setUsage(null)
      setUsageSummary(null)
      setIsLoading(false)
      return
    }
    setIsLoading(true)
    setError('')
    try {
      const [connections, settings, usageItems, summary] = await Promise.all([
        fetchAIProviders(),
        fetchAIProjectSettings(activeProjectId),
        fetchAIUsage(activeProjectId, dateFrom, dateTo),
        fetchAIUsageSummary(activeProjectId, dateFrom, dateTo),
      ])
      setProviders(connections)
      setProjectSettings(settingsDraft(settings))
      setUsage(usageItems)
      setUsageSummary(summary)
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Не удалось загрузить настройки AI.'))
    } finally {
      setIsLoading(false)
    }
  }, [activeProjectId, dateFrom, dateTo])

  useEffect(() => {
    void loadPage()
  }, [loadPage])

  const loadModels = async (connectionId: string) => {
    setLoadingModelsId(connectionId)
    try {
      const result = await fetchAIProviderModels(connectionId)
      setModelsByConnection((current) => ({
        ...current,
        [connectionId]: result.models,
      }))
      if (result.warning) {
        notify({ tone: 'warning', message: result.warning })
      }
    } catch (loadError) {
      notify({
        tone: 'warning',
        message: getErrorMessage(
          loadError,
          'Список моделей недоступен. Название можно ввести вручную.',
        ),
      })
    } finally {
      setLoadingModelsId(null)
    }
  }

  const updateSettings = <K extends keyof AIProjectSettingsInput>(
    key: K,
    value: AIProjectSettingsInput[K],
  ) => {
    setProjectSettings((current) => current ? { ...current, [key]: value } : current)
  }

  const handleSaveSettings = async () => {
    if (!activeProjectId || !projectSettings) return
    setIsSavingSettings(true)
    setError('')
    try {
      const payload: AIProjectSettingsInput = {
        ...projectSettings,
        primary_model: projectSettings.primary_model?.trim() || null,
        fallback_model: projectSettings.fallback_model?.trim() || null,
        master_prompt: projectSettings.master_prompt?.trim() || null,
        daily_budget_usd:
          projectSettings.daily_budget_usd === '' ? null : projectSettings.daily_budget_usd,
        monthly_budget_usd:
          projectSettings.monthly_budget_usd === '' ? null : projectSettings.monthly_budget_usd,
      }
      const saved = await updateAIProjectSettings(activeProjectId, payload)
      setProjectSettings(settingsDraft(saved))
      notify({ tone: 'success', message: 'Настройки AI сохранены.' })
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Не удалось сохранить настройки AI.'))
    } finally {
      setIsSavingSettings(false)
    }
  }

  const handleProviderPreset = (presetId: string) => {
    const preset = providerPresets.find((item) => item.id === presetId)
    if (!preset) return
    setProviderDraft((current) => current ? {
      ...current,
      preset: preset.id,
      provider: preset.provider,
      apiStyle: preset.apiStyle,
      baseUrl: preset.baseUrl,
      name: current.name || preset.label,
    } : current)
  }

  const updatePricingRow = (rowId: string, patch: Partial<PricingRow>) => {
    setProviderDraft((current) => current ? {
      ...current,
      pricingRows: current.pricingRows.map((row) =>
        row.id === rowId ? { ...row, ...patch } : row,
      ),
    } : current)
  }

  const handleSaveProvider = async () => {
    if (!providerDraft) return
    const timeout = Number(providerDraft.timeout)
    if (!providerDraft.name.trim() || !providerDraft.provider.trim() || !providerDraft.baseUrl.trim()) {
      setError('Заполните название, провайдера и Base URL.')
      return
    }
    if (!providerDraft.id && !providerDraft.apiKey.trim()) {
      setError('Для нового подключения нужен API-ключ.')
      return
    }
    if (!Number.isInteger(timeout) || timeout < 1 || timeout > 120) {
      setError('Таймаут должен быть целым числом от 1 до 120 секунд.')
      return
    }
    const pricing: AIProviderConnectionInput['pricing'] = {}
    for (const row of providerDraft.pricingRows) {
      const model = row.model.trim()
      if (!model) continue
      const inputPrice = Number(row.input)
      const outputPrice = Number(row.output)
      if (
        !Number.isFinite(inputPrice) ||
        inputPrice < 0 ||
        !Number.isFinite(outputPrice) ||
        outputPrice < 0
      ) {
        setError(`Проверьте цену модели ${model}.`)
        return
      }
      if (pricing[model]) {
        setError(`Модель ${model} указана в ценах дважды.`)
        return
      }
      pricing[model] = {
        input_usd_per_million: inputPrice,
        output_usd_per_million: outputPrice,
      }
    }
    const payload: AIProviderConnectionInput = {
      name: providerDraft.name.trim(),
      provider: providerDraft.provider.trim().toLowerCase(),
      api_style: providerDraft.apiStyle,
      base_url: providerDraft.baseUrl.trim(),
      default_model: providerDraft.defaultModel.trim() || null,
      is_active: providerDraft.isActive,
      request_timeout_seconds: timeout,
      supports_json_mode: providerDraft.supportsJsonMode,
      pricing,
    }
    if (providerDraft.apiKey.trim()) {
      payload.api_key = providerDraft.apiKey.trim()
    }
    if (providerDraft.clearApiKey) {
      payload.clear_api_key = true
    }
    setIsSavingProvider(true)
    setError('')
    try {
      const saved = providerDraft.id
        ? await updateAIProvider(providerDraft.id, payload)
        : await createAIProvider(payload)
      const nextProviders = await fetchAIProviders()
      setProviders(nextProviders)
      setProviderDraft(providerDraftFromConnection(saved))
      notify({ tone: 'success', message: 'Подключение AI сохранено.' })
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Не удалось сохранить подключение.'))
    } finally {
      setIsSavingProvider(false)
    }
  }

  const handleDeleteProvider = async (connection: AIProviderConnection) => {
    if (!window.confirm(`Удалить подключение «${connection.name}»?`)) return
    try {
      await deleteAIProvider(connection.id)
      setProviders(await fetchAIProviders())
      if (providerDraft?.id === connection.id) setProviderDraft(null)
      notify({ tone: 'success', message: 'Подключение удалено.' })
    } catch (deleteError) {
      setError(getErrorMessage(deleteError, 'Не удалось удалить подключение.'))
    }
  }

  const handleTestProvider = async (connection: AIProviderConnection) => {
    setTestingProviderId(connection.id)
    try {
      const result = await testAIProvider(connection.id, connection.default_model)
      notify({
        tone: 'success',
        message: `${result.model}: подключение работает, ${result.latency_ms} мс.`,
      })
    } catch (testError) {
      setError(getErrorMessage(testError, 'Проверка подключения не прошла.'))
    } finally {
      setTestingProviderId(null)
    }
  }

  if (!activeProjectId) {
    return (
      <section className="flex h-full min-h-0 items-center justify-center rounded-xl border border-white/5 bg-[#0B0F19]/80 p-6 text-center">
        <div>
          <BrainCircuit className="mx-auto text-cyan-300" size={28} />
          <h1 className="mt-3 text-xl font-semibold text-white">AI и модели</h1>
          <p className="mt-2 text-sm text-gray-500">Выберите проект в верхней панели.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0B0F19]/80 text-gray-200 shadow-card">
      <header className="shrink-0 border-b border-white/5 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-200">
              <BrainCircuit size={19} />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-semibold text-white">AI и модели</h1>
              <p className="truncate text-sm text-gray-500">Провайдеры, поведение и расход проекта</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void loadPage()}
            disabled={isLoading}
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-gray-200 disabled:opacity-50"
            title="Обновить"
          >
            {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          </button>
        </div>
      </header>

      {error ? (
        <div className="flex items-start justify-between gap-3 border-b border-red-400/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
          <span>{error}</span>
          <button type="button" onClick={() => setError('')} className="shrink-0" aria-label="Закрыть">
            <X size={15} />
          </button>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-3 sm:p-5">
        {isLoading || !projectSettings ? (
          <div className="flex min-h-48 items-center justify-center text-gray-500">
            <LoaderCircle size={22} className="animate-spin" />
          </div>
        ) : (
          <>
            <div className="overflow-hidden rounded-xl border border-white/8 bg-surface">
              <div className="flex flex-col gap-3 border-b border-white/8 px-4 py-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-white">Настройки проекта</h2>
                  <p className="mt-1 text-sm text-gray-500">По умолчанию AI не участвует в воронках.</p>
                </div>
                <label className="flex min-h-11 items-center justify-between gap-4 rounded-lg border border-white/10 bg-background/60 px-3 text-sm text-gray-200">
                  <span>{projectSettings.is_enabled ? 'AI включён' : 'AI выключен'}</span>
                  <input
                    type="checkbox"
                    checked={projectSettings.is_enabled}
                    onChange={(event) => updateSettings('is_enabled', event.target.checked)}
                  />
                </label>
              </div>

              <div className="grid gap-5 p-4 xl:grid-cols-2">
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-white">Основная модель</h3>
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">Подключение</span>
                    <select
                      value={projectSettings.primary_connection_id ?? ''}
                      onChange={(event) => {
                        const id = event.target.value || null
                        const provider = providers.find((item) => item.id === id)
                        updateSettings('primary_connection_id', id)
                        updateSettings('primary_model', provider?.default_model ?? null)
                      }}
                      className={fieldClass}
                    >
                      <option value="">Не выбрано</option>
                      {providers.filter((item) => item.is_active).map((provider) => (
                        <option key={provider.id} value={provider.id}>{provider.name}</option>
                      ))}
                    </select>
                  </label>
                  <ModelField
                    id="primary-ai-model"
                    connectionId={projectSettings.primary_connection_id}
                    value={projectSettings.primary_model ?? ''}
                    models={projectSettings.primary_connection_id
                      ? modelsByConnection[projectSettings.primary_connection_id] ?? []
                      : []}
                    isLoading={loadingModelsId === projectSettings.primary_connection_id}
                    onChange={(value) => updateSettings('primary_model', value || null)}
                    onRefresh={loadModels}
                  />
                </div>

                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-white">Резервная модель</h3>
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">Подключение</span>
                    <select
                      value={projectSettings.fallback_connection_id ?? ''}
                      onChange={(event) => {
                        const id = event.target.value || null
                        const provider = providers.find((item) => item.id === id)
                        updateSettings('fallback_connection_id', id)
                        updateSettings('fallback_model', provider?.default_model ?? null)
                      }}
                      className={fieldClass}
                    >
                      <option value="">Без резервной модели</option>
                      {providers.filter((item) => item.is_active).map((provider) => (
                        <option key={provider.id} value={provider.id}>{provider.name}</option>
                      ))}
                    </select>
                  </label>
                  <ModelField
                    id="fallback-ai-model"
                    connectionId={projectSettings.fallback_connection_id}
                    value={projectSettings.fallback_model ?? ''}
                    models={projectSettings.fallback_connection_id
                      ? modelsByConnection[projectSettings.fallback_connection_id] ?? []
                      : []}
                    isLoading={loadingModelsId === projectSettings.fallback_connection_id}
                    onChange={(value) => updateSettings('fallback_model', value || null)}
                    onRefresh={loadModels}
                  />
                </div>
              </div>
              <div className="border-t border-cyan-300/10 bg-cyan-300/[0.04] px-4 py-3 text-sm leading-6 text-cyan-50/80">
                При включении AI выбранному провайдеру передаются контекст лида и ограниченная
                история чата. Полные промпты и переписка в журнале расхода CRM не сохраняются.
              </div>

              <div className="border-t border-white/8 p-4">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                    Мастер-промпт проекта
                  </span>
                  <textarea
                    value={projectSettings.master_prompt ?? ''}
                    onChange={(event) => updateSettings('master_prompt', event.target.value)}
                    rows={7}
                    className={`${fieldClass} resize-y`}
                    placeholder="Роль, тон общения, ограничения и обязательные правила проекта"
                  />
                </label>
              </div>

              <div className="grid gap-3 border-t border-white/8 p-4 sm:grid-cols-2 xl:grid-cols-4">
                <NumberField
                  label="История, сообщений"
                  value={projectSettings.history_message_limit}
                  min={1}
                  max={100}
                  onChange={(value) => updateSettings('history_message_limit', value)}
                />
                <NumberField
                  label="Контекст, символов"
                  value={projectSettings.max_context_chars}
                  min={1000}
                  max={100000}
                  onChange={(value) => updateSettings('max_context_chars', value)}
                />
                <NumberField
                  label="Temperature"
                  value={projectSettings.default_temperature}
                  min={0}
                  max={2}
                  step={0.05}
                  onChange={(value) => updateSettings('default_temperature', value)}
                />
                <NumberField
                  label="Макс. токенов ответа"
                  value={projectSettings.default_max_output_tokens}
                  min={1}
                  max={32000}
                  onChange={(value) => updateSettings('default_max_output_tokens', value)}
                />
                <NumberField
                  label="мс на символ"
                  value={projectSettings.typing_delay_per_char_ms}
                  min={0}
                  max={250}
                  onChange={(value) => updateSettings('typing_delay_per_char_ms', value)}
                />
                <NumberField
                  label="Мин. задержка, мс"
                  value={projectSettings.min_delay_ms}
                  min={0}
                  max={30000}
                  onChange={(value) => updateSettings('min_delay_ms', value)}
                />
                <NumberField
                  label="Макс. задержка, мс"
                  value={projectSettings.max_delay_ms}
                  min={0}
                  max={30000}
                  onChange={(value) => updateSettings('max_delay_ms', value)}
                />
                <div className="grid grid-cols-2 gap-2">
                  <OptionalMoneyField
                    label="Лимит / день"
                    value={projectSettings.daily_budget_usd}
                    onChange={(value) => updateSettings('daily_budget_usd', value)}
                  />
                  <OptionalMoneyField
                    label="Лимит / месяц"
                    value={projectSettings.monthly_budget_usd}
                    onChange={(value) => updateSettings('monthly_budget_usd', value)}
                  />
                </div>
              </div>

              <div className="flex justify-end border-t border-white/8 p-4">
                <button
                  type="button"
                  onClick={() => void handleSaveSettings()}
                  disabled={isSavingSettings}
                  className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:opacity-50"
                >
                  {isSavingSettings
                    ? <LoaderCircle size={16} className="animate-spin" />
                    : <Save size={16} />}
                  Сохранить настройки
                </button>
              </div>
            </div>

            <div className="overflow-hidden rounded-xl border border-white/8 bg-surface">
              <div className="flex flex-col gap-3 border-b border-white/8 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-white">Подключения</h2>
                  <p className="mt-1 text-sm text-gray-500">Ключи хранятся зашифрованными и не показываются повторно.</p>
                </div>
                {canManageCredentials ? (
                  <button
                    type="button"
                    onClick={() => setProviderDraft(emptyProviderDraft())}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-cyan-300/30 px-3 text-sm font-medium text-cyan-100"
                  >
                    <Plus size={15} />
                    Добавить
                  </button>
                ) : null}
              </div>

              <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
                {providers.map((provider) => (
                  <article key={provider.id} className="rounded-lg border border-white/8 bg-background/55 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-white">{provider.name}</p>
                        <p className="mt-1 truncate text-xs text-gray-500">
                          {provider.provider} · {provider.default_model || 'модель не выбрана'}
                        </p>
                      </div>
                      <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                        provider.is_active ? 'bg-emerald-400' : 'bg-gray-600'
                      }`} title={provider.is_active ? 'Активно' : 'Выключено'} />
                    </div>
                    <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
                      <KeyRound size={13} />
                      <span>{provider.api_key_mask ?? 'ключ не задан'}</span>
                      <span>·</span>
                      <span>{Object.keys(provider.pricing).length} цен</span>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void handleTestProvider(provider)}
                        disabled={!provider.default_model || testingProviderId === provider.id}
                        className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-xs text-gray-200 disabled:opacity-40"
                      >
                        {testingProviderId === provider.id
                          ? <LoaderCircle size={13} className="animate-spin" />
                          : <Zap size={13} />}
                        Проверить
                      </button>
                      <button
                        type="button"
                        onClick={() => void loadModels(provider.id)}
                        disabled={loadingModelsId === provider.id}
                        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                        title="Загрузить модели"
                      >
                        <RefreshCw size={13} className={loadingModelsId === provider.id ? 'animate-spin' : ''} />
                      </button>
                      {canManageCredentials ? (
                        <>
                          <button
                            type="button"
                            onClick={() => setProviderDraft(providerDraftFromConnection(provider))}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-gray-300"
                            title="Редактировать"
                          >
                            <Pencil size={13} />
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDeleteProvider(provider)}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
                            title="Удалить"
                          >
                            <Trash2 size={13} />
                          </button>
                        </>
                      ) : null}
                    </div>
                  </article>
                ))}
                {providers.length === 0 ? (
                  <p className="py-5 text-sm text-gray-500">Подключения ещё не добавлены.</p>
                ) : null}
              </div>

              {providerDraft && canManageCredentials ? (
                <ProviderEditor
                  draft={providerDraft}
                  models={providerDraft.id ? modelsByConnection[providerDraft.id] ?? [] : []}
                  isSaving={isSavingProvider}
                  isLoadingModels={loadingModelsId === providerDraft.id}
                  onChange={setProviderDraft}
                  onPresetChange={handleProviderPreset}
                  onPricingChange={updatePricingRow}
                  onLoadModels={() => providerDraft.id && void loadModels(providerDraft.id)}
                  onClose={() => setProviderDraft(null)}
                  onSave={() => void handleSaveProvider()}
                />
              ) : null}
            </div>

            <div className="overflow-hidden rounded-xl border border-white/8 bg-surface">
              <div className="flex flex-col gap-3 border-b border-white/8 px-4 py-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-white">Расход и стабильность</h2>
                  <p className="mt-1 text-sm text-gray-500">Токены, оценочная стоимость и ошибки вызовов.</p>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">С</span>
                    <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className={fieldClass} />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs text-gray-500">По</span>
                    <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className={fieldClass} />
                  </label>
                  <button
                    type="button"
                    onClick={() => void loadUsage()}
                    disabled={isLoadingUsage}
                    className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-white/10 text-gray-200 disabled:opacity-50"
                    title="Обновить период"
                  >
                    {isLoadingUsage
                      ? <LoaderCircle size={15} className="animate-spin" />
                      : <RefreshCw size={15} />}
                  </button>
                </div>
              </div>

              {usageSummary ? (
                <>
                  <div className="grid gap-px bg-white/8 sm:grid-cols-2 xl:grid-cols-4">
                    <Metric label="Запросы" value={integer(usageSummary.requests)} icon={<BrainCircuit size={16} />} />
                    <Metric label="Токены" value={integer(usageSummary.total_tokens)} icon={<Zap size={16} />} />
                    <Metric label="Расход" value={money(usageSummary.estimated_cost_usd)} icon={<CircleDollarSign size={16} />} />
                    <Metric label="Средняя задержка" value={`${integer(usageSummary.average_latency_ms)} мс`} icon={<CheckCircle2 size={16} />} />
                  </div>
                  {usageSummary.unknown_cost_requests > 0 ? (
                    <div className="border-t border-amber-300/15 bg-amber-300/[0.06] px-4 py-3 text-sm text-amber-100">
                      Для {usageSummary.unknown_cost_requests} вызовов цена модели не настроена, поэтому итоговый расход неполный.
                    </div>
                  ) : null}
                  {(usageSummary.by_connection ?? []).length > 0 ? (
                    <div className="border-t border-white/8">
                      <div className="px-4 py-3">
                        <h3 className="text-sm font-semibold text-white">Расход по подключениям</h3>
                        <p className="mt-1 text-xs text-gray-500">
                          При замене ключа его новая версия учитывается отдельно.
                        </p>
                      </div>
                      <div className="divide-y divide-white/5 border-t border-white/5">
                        {usageSummary.by_connection.map((item, index) => (
                          <div
                            key={`${item.connection_id ?? item.provider}-${item.api_key_mask ?? 'no-key'}-${index}`}
                            className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1fr)_auto_auto_auto] sm:items-center sm:gap-5"
                          >
                            <div className="min-w-0">
                              <p className="truncate font-medium text-gray-100">{item.connection_name}</p>
                              <p className="truncate text-xs text-gray-500">
                                {item.provider}{item.api_key_mask ? ` · ${item.api_key_mask}` : ''}
                              </p>
                            </div>
                            <span className="text-gray-400">{integer(item.requests)} запросов</span>
                            <span className="text-gray-400">{integer(item.total_tokens)} токенов</span>
                            <span className="font-medium text-gray-100">
                              {money(item.estimated_cost_usd, 6)}
                              {item.unknown_cost_requests > 0 ? ' + неизвестно' : ''}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </>
              ) : null}

              <div className="overflow-x-auto">
                <table className="hidden w-full min-w-[760px] text-left text-sm md:table">
                  <thead className="border-y border-white/8 bg-background/50 text-xs uppercase text-gray-500">
                    <tr>
                      <th className="px-4 py-3">Время</th>
                      <th className="px-4 py-3">Провайдер / модель</th>
                      <th className="px-4 py-3">Статус</th>
                      <th className="px-4 py-3 text-right">Токены</th>
                      <th className="px-4 py-3 text-right">Стоимость</th>
                      <th className="px-4 py-3 text-right">Задержка</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {usage?.items.map((item) => (
                      <tr key={item.id}>
                        <td className="whitespace-nowrap px-4 py-3 text-gray-400">
                          {new Date(item.created_at).toLocaleString('ru-RU')}
                        </td>
                        <td className="max-w-[300px] px-4 py-3">
                          <p className="truncate font-medium text-gray-100">{item.model}</p>
                          <p className="truncate text-xs text-gray-500">
                            {item.connection_name ?? item.provider}
                            {item.api_key_mask ? ` · ${item.api_key_mask}` : ''}
                            {item.used_fallback ? ' · fallback' : ''}
                          </p>
                        </td>
                        <td className="px-4 py-3">
                          <UsageStatus status={item.status} error={item.error_message} />
                        </td>
                        <td className="px-4 py-3 text-right text-gray-300">{integer(item.total_tokens ?? 0)}</td>
                        <td className="px-4 py-3 text-right text-gray-300">
                          {item.estimated_cost_usd === null ? '—' : money(item.estimated_cost_usd, 6)}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-400">
                          {item.latency_ms === null ? '—' : `${item.latency_ms} мс`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="divide-y divide-white/5 md:hidden">
                  {usage?.items.map((item) => (
                    <div key={item.id} className="space-y-2 px-4 py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-white">{item.model}</p>
                          <p className="truncate text-xs text-gray-500">
                            {item.connection_name ?? item.provider}
                            {item.api_key_mask ? ` · ${item.api_key_mask}` : ''}
                          </p>
                          <p className="text-xs text-gray-500">{new Date(item.created_at).toLocaleString('ru-RU')}</p>
                        </div>
                        <UsageStatus status={item.status} error={item.error_message} />
                      </div>
                      <div className="flex justify-between gap-3 text-xs text-gray-400">
                        <span>{integer(item.total_tokens ?? 0)} токенов</span>
                        <span>{item.estimated_cost_usd === null ? 'Цена неизвестна' : money(item.estimated_cost_usd, 6)}</span>
                      </div>
                    </div>
                  ))}
                </div>
                {usage && usage.items.length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-gray-500">За период вызовов не было.</p>
                ) : null}
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function ModelField({
  id,
  connectionId,
  value,
  models,
  isLoading,
  onChange,
  onRefresh,
}: {
  id: string
  connectionId: string | null
  value: string
  models: string[]
  isLoading: boolean
  onChange: (value: string) => void
  onRefresh: (connectionId: string) => Promise<void>
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-center justify-between gap-2 text-xs text-gray-500">
        <span>Модель</span>
        {connectionId ? (
          <button
            type="button"
            onClick={() => void onRefresh(connectionId)}
            disabled={isLoading}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/10 text-gray-300 disabled:opacity-50"
            title="Получить модели"
          >
            <RefreshCw size={12} className={isLoading ? 'animate-spin' : ''} />
          </button>
        ) : null}
      </span>
      <input
        list={`${id}-list`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={!connectionId}
        placeholder={connectionId ? 'Название модели' : 'Сначала выберите подключение'}
        className={`${fieldClass} disabled:cursor-not-allowed disabled:opacity-60`}
      />
      <datalist id={`${id}-list`}>
        {models.map((model) => <option key={model} value={model} />)}
      </datalist>
    </label>
  )
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string
  value: number | string
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-gray-500">{label}</span>
      <input
        type="number"
        value={String(value)}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className={fieldClass}
      />
    </label>
  )
}

function OptionalMoneyField({
  label,
  value,
  onChange,
}: {
  label: string
  value: number | string | null
  onChange: (value: string | null) => void
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block truncate text-xs text-gray-500">{label}</span>
      <input
        type="number"
        value={optionalNumber(value)}
        min="0"
        step="0.01"
        placeholder="Нет"
        onChange={(event) => onChange(event.target.value === '' ? null : event.target.value)}
        className={fieldClass}
      />
    </label>
  )
}

function Metric({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="bg-surface px-4 py-4">
      <div className="flex items-center gap-2 text-xs uppercase text-gray-500">
        <span className="text-cyan-300">{icon}</span>
        {label}
      </div>
      <p className="mt-2 text-xl font-semibold text-white">{value}</p>
    </div>
  )
}

function UsageStatus({
  status,
  error,
}: {
  status: 'success' | 'failed'
  error: string | null
}) {
  return (
    <span
      title={error ?? undefined}
      className={`inline-flex rounded-md px-2 py-1 text-xs font-medium ${
        status === 'success'
          ? 'bg-emerald-400/10 text-emerald-200'
          : 'bg-red-400/10 text-red-200'
      }`}
    >
      {status === 'success' ? 'Успешно' : 'Ошибка'}
    </span>
  )
}

function ProviderEditor({
  draft,
  models,
  isSaving,
  isLoadingModels,
  onChange,
  onPresetChange,
  onPricingChange,
  onLoadModels,
  onClose,
  onSave,
}: {
  draft: ProviderDraft
  models: string[]
  isSaving: boolean
  isLoadingModels: boolean
  onChange: (draft: ProviderDraft) => void
  onPresetChange: (presetId: string) => void
  onPricingChange: (rowId: string, patch: Partial<PricingRow>) => void
  onLoadModels: () => void
  onClose: () => void
  onSave: () => void
}) {
  return (
    <div className="border-t border-white/8 bg-background/30 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white">
            {draft.id ? 'Редактирование подключения' : 'Новое подключение'}
          </h3>
          <p className="mt-1 text-xs text-gray-500">Модель не фиксируется списком и может быть введена вручную.</p>
        </div>
        <button type="button" onClick={onClose} className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-gray-300">
          <X size={15} />
        </button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Профиль</span>
          <select value={draft.preset} onChange={(event) => onPresetChange(event.target.value)} className={fieldClass}>
            {providerPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Название в CRM</span>
          <input value={draft.name} onChange={(event) => onChange({ ...draft, name: event.target.value })} className={fieldClass} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Техническое имя</span>
          <input value={draft.provider} onChange={(event) => onChange({ ...draft, provider: event.target.value.toLowerCase() })} className={fieldClass} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">API-формат</span>
          <select value={draft.apiStyle} onChange={(event) => onChange({ ...draft, apiStyle: event.target.value as AIAPIStyle })} className={fieldClass}>
            <option value="openai_compatible">OpenAI-compatible</option>
            <option value="gemini">Gemini native</option>
          </select>
        </label>
        <label className="block md:col-span-2">
          <span className="mb-1 block text-xs text-gray-500">Base URL</span>
          <input value={draft.baseUrl} onChange={(event) => onChange({ ...draft, baseUrl: event.target.value })} className={fieldClass} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">API-ключ</span>
          <input
            type="password"
            value={draft.apiKey}
            onChange={(event) => onChange({ ...draft, apiKey: event.target.value, clearApiKey: false })}
            placeholder={draft.id ? 'Оставьте пустым без замены' : 'Введите ключ'}
            autoComplete="new-password"
            className={fieldClass}
          />
        </label>
        <label className="block">
          <span className="mb-1 flex items-center justify-between gap-2 text-xs text-gray-500">
            <span>Модель по умолчанию</span>
            {draft.id ? (
              <button
                type="button"
                onClick={onLoadModels}
                disabled={isLoadingModels}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/10 text-gray-300 disabled:opacity-50"
                title="Получить модели"
              >
                <RefreshCw size={12} className={isLoadingModels ? 'animate-spin' : ''} />
              </button>
            ) : null}
          </span>
          <input
            list={`provider-models-${draft.id ?? 'new'}`}
            value={draft.defaultModel}
            onChange={(event) => onChange({ ...draft, defaultModel: event.target.value })}
            placeholder="Название модели"
            className={fieldClass}
          />
          <datalist id={`provider-models-${draft.id ?? 'new'}`}>
            {models.map((model) => <option key={model} value={model} />)}
          </datalist>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Таймаут, сек.</span>
          <input type="number" min="1" max="120" value={draft.timeout} onChange={(event) => onChange({ ...draft, timeout: event.target.value })} className={fieldClass} />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-4 border-y border-white/8 py-3">
        <label className="flex min-h-9 items-center gap-2 text-sm text-gray-200">
          <input type="checkbox" checked={draft.isActive} onChange={(event) => onChange({ ...draft, isActive: event.target.checked })} />
          Подключение активно
        </label>
        <label className="flex min-h-9 items-center gap-2 text-sm text-gray-200">
          <input type="checkbox" checked={draft.supportsJsonMode} onChange={(event) => onChange({ ...draft, supportsJsonMode: event.target.checked })} />
          JSON mode поддерживается
        </label>
        {draft.id ? (
          <label className="flex min-h-9 items-center gap-2 text-sm text-red-200">
            <input
              type="checkbox"
              checked={draft.clearApiKey}
              disabled={Boolean(draft.apiKey)}
              onChange={(event) => onChange({ ...draft, clearApiKey: event.target.checked })}
            />
            Удалить сохранённый ключ
          </label>
        ) : null}
      </div>

      <div className="mt-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h4 className="text-sm font-semibold text-white">Цена за 1 млн токенов, USD</h4>
            <p className="mt-1 text-xs text-gray-500">Нужна для точного расхода и бюджетных лимитов.</p>
          </div>
          <button
            type="button"
            onClick={() => onChange({
              ...draft,
              pricingRows: [
                ...draft.pricingRows,
                { id: crypto.randomUUID(), model: '', input: '', output: '' },
              ],
            })}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-xs text-gray-200"
          >
            <Plus size={13} />
            Модель
          </button>
        </div>
        <div className="mt-3 space-y-2">
          {draft.pricingRows.map((row) => (
            <div key={row.id} className="grid gap-2 md:grid-cols-[minmax(0,2fr)_minmax(120px,1fr)_minmax(120px,1fr)_40px]">
              <input value={row.model} onChange={(event) => onPricingChange(row.id, { model: event.target.value })} placeholder="Название модели" className={fieldClass} />
              <input type="number" min="0" step="0.000001" value={row.input} onChange={(event) => onPricingChange(row.id, { input: event.target.value })} placeholder="Вход" className={fieldClass} />
              <input type="number" min="0" step="0.000001" value={row.output} onChange={(event) => onPricingChange(row.id, { output: event.target.value })} placeholder="Выход" className={fieldClass} />
              <button
                type="button"
                onClick={() => onChange({ ...draft, pricingRows: draft.pricingRows.filter((item) => item.id !== row.id) })}
                className="inline-flex h-11 w-10 items-center justify-center rounded-lg border border-red-300/15 text-red-200"
                title="Удалить цену"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {draft.pricingRows.length === 0 ? (
            <p className="rounded-lg border border-dashed border-white/10 px-3 py-3 text-xs text-gray-500">Цены не заданы.</p>
          ) : null}
        </div>
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-slate-950 disabled:opacity-50"
        >
          {isSaving ? <LoaderCircle size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
          Сохранить подключение
        </button>
      </div>
    </div>
  )
}

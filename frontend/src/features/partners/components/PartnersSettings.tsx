import axios from 'axios'
import {
  AlertTriangle,
  CheckCircle2,
  KeyRound,
  LoaderCircle,
  Pencil,
  PlugZap,
  Plus,
  Save,
  Trash2,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import {
  createPartnerIntegration,
  deletePartnerIntegration,
  fetchPartnerIntegrations,
  testPartnerConnection,
  updatePartnerIntegration,
} from '../api'
import type {
  AuthType,
  PartnerConnectionTestResult,
  PartnerIntegration,
  PartnerIntegrationPayload,
} from '../types'

type PartnersSettingsProps = {
  projectId: string | null
}

type MappingRow = {
  id: string
  partnerKey: string
  leadPath: string
  isRequired: boolean
}

type PartnerFormState = {
  name: string
  postback_url: string
  auth_type: AuthType
  header_name: string
  query_param_name: string
  token: string
  is_active: boolean
  mappingRows: MappingRow[]
  success_key: string
  success_value: string
  duplicate_key: string
  duplicate_value: string
  rejected_value: string
  error_path: string
  external_id_path: string
  partner_status_path: string
  max_attempts: string
  timeout_seconds: string
  delays_seconds: string
}

const leadFieldOptions = [
  { value: 'id', label: 'Lead ID' },
  { value: 'name', label: 'Имя' },
  { value: 'phone', label: 'Телефон' },
  { value: 'username', label: 'Username' },
  { value: 'age', label: 'Возраст' },
  { value: 'country', label: 'Страна' },
  { value: 'call_time_text', label: 'Удобное время' },
  { value: 'has_card', label: 'Карта' },
  { value: 'score_percent', label: 'Скоринг' },
  { value: 'created_at', label: 'Дата создания' },
  { value: 'custom_fields.click_id', label: 'custom_fields.click_id' },
  { value: 'custom_fields.tracker_link_id', label: 'custom_fields.tracker_link_id' },
  { value: 'custom_fields.deposit', label: 'custom_fields.deposit' },
  { value: 'custom_fields.source', label: 'custom_fields.source' },
  { value: '__custom__', label: 'Другой путь...' },
] as const

const emptyMappingRow = (): MappingRow => ({
  id: crypto.randomUUID(),
  partnerKey: '',
  leadPath: 'phone',
  isRequired: false,
})

const emptyForm = (): PartnerFormState => ({
  name: '',
  postback_url: '',
  auth_type: 'bearer',
  header_name: 'Authorization',
  query_param_name: 'token',
  token: '',
  is_active: true,
  mappingRows: [
    { ...emptyMappingRow(), partnerKey: 'phone', leadPath: 'phone', isRequired: true },
    { ...emptyMappingRow(), partnerKey: 'name', leadPath: 'name', isRequired: false },
  ],
  success_key: 'status',
  success_value: 'ok',
  duplicate_key: 'error',
  duplicate_value: 'already_exists',
  rejected_value: 'error',
  error_path: 'error',
  external_id_path: '',
  partner_status_path: '',
  max_attempts: '3',
  timeout_seconds: '30',
  delays_seconds: '60,300,900',
})

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.response?.status === 403) {
      return 'Недостаточно прав для управления партнёрами.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function formFromPartner(partner: PartnerIntegration): PartnerFormState {
  const fieldMapping = partner.field_mapping ?? {}
  const required = new Set(partner.required_fields ?? [])
  const mappingRows = Object.entries(fieldMapping).map(([partnerKey, leadPath]) => ({
    id: crypto.randomUUID(),
    partnerKey,
    leadPath,
    isRequired: required.has(partnerKey),
  }))

  return {
    name: partner.name,
    postback_url: partner.postback_url,
    auth_type: partner.auth_type,
    header_name: partner.auth_config?.header_name ?? 'Authorization',
    query_param_name: partner.auth_config?.query_param_name ?? 'token',
    token: partner.auth_config?.token ?? '',
    is_active: partner.is_active,
    mappingRows: mappingRows.length > 0 ? mappingRows : [emptyMappingRow()],
    success_key: partner.response_mapping?.success_key ?? partner.response_mapping?.status_path ?? 'status',
    success_value: partner.response_mapping?.success_value ?? partner.response_mapping?.success_values?.[0] ?? 'ok',
    duplicate_key: partner.response_mapping?.duplicate_key ?? 'error',
    duplicate_value: partner.response_mapping?.duplicate_value ?? partner.response_mapping?.duplicate_values?.[0] ?? 'already_exists',
    rejected_value: partner.response_mapping?.rejected_value ?? partner.response_mapping?.rejected_values?.[0] ?? 'error',
    error_path: partner.response_mapping?.error_path ?? 'error',
    external_id_path: partner.response_mapping?.external_id_path ?? '',
    partner_status_path: partner.response_mapping?.partner_status_path ?? '',
    max_attempts: String(partner.retry_config?.max_attempts ?? 3),
    timeout_seconds: String(partner.retry_config?.timeout_seconds ?? 30),
    delays_seconds: (partner.retry_config?.delays_seconds ?? [60, 300, 900]).join(','),
  }
}

function toPayload(projectId: string, form: PartnerFormState): PartnerIntegrationPayload {
  const field_mapping: Record<string, string> = {}
  const required_fields: string[] = []

  for (const row of form.mappingRows) {
    const partnerKey = row.partnerKey.trim()
    const leadPath = row.leadPath.trim()
    if (!partnerKey || !leadPath || leadPath === '__custom__') {
      continue
    }
    field_mapping[partnerKey] = leadPath
    if (row.isRequired) {
      required_fields.push(partnerKey)
    }
  }

  const delays = form.delays_seconds
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item >= 0)

  return {
    project_id: projectId,
    name: form.name.trim(),
    postback_url: form.postback_url.trim(),
    auth_type: form.auth_type,
    auth_config: {
      header_name: form.auth_type === 'header' ? form.header_name.trim() : undefined,
      query_param_name: form.auth_type === 'query_param' ? form.query_param_name.trim() : undefined,
      token: form.token.trim() || undefined,
    },
    field_mapping,
    required_fields,
    response_mapping: {
      status_path: form.success_key.trim() || 'status',
      success_key: form.success_key.trim() || undefined,
      success_value: form.success_value.trim() || undefined,
      success_values: form.success_value.trim() ? [form.success_value.trim()] : ['success', 'accepted', 'ok'],
      duplicate_key: form.duplicate_key.trim() || undefined,
      duplicate_value: form.duplicate_value.trim() || undefined,
      duplicate_values: form.duplicate_value.trim() ? [form.duplicate_value.trim()] : ['duplicate'],
      rejected_value: form.rejected_value.trim() || undefined,
      rejected_values: form.rejected_value.trim() ? [form.rejected_value.trim()] : ['rejected', 'error'],
      error_path: form.error_path.trim() || undefined,
      external_id_path: form.external_id_path.trim() || undefined,
      partner_status_path: form.partner_status_path.trim() || undefined,
      status_mapping: {},
    },
    retry_config: {
      max_attempts: Number(form.max_attempts) || 1,
      timeout_seconds: Number(form.timeout_seconds) || 30,
      delays_seconds: delays.length > 0 ? delays : [60, 300, 900],
    },
    is_active: form.is_active,
  }
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

export default function PartnersSettings({ projectId }: PartnersSettingsProps) {
  const [partners, setPartners] = useState<PartnerIntegration[]>([])
  const [selectedPartnerId, setSelectedPartnerId] = useState<string | null>(null)
  const [form, setForm] = useState<PartnerFormState>(() => emptyForm())
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [testingPartnerId, setTestingPartnerId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<PartnerConnectionTestResult | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const selectedPartner = useMemo(
    () => partners.find((partner) => partner.id === selectedPartnerId) ?? null,
    [partners, selectedPartnerId],
  )

  const loadPartners = useCallback(async () => {
    if (!projectId) {
      setPartners([])
      setSelectedPartnerId(null)
      return
    }
    setIsLoading(true)
    setError('')
    try {
      const data = await fetchPartnerIntegrations(projectId, 100)
      setPartners(data.items)
      setSelectedPartnerId((current) => {
        if (current && data.items.some((partner) => partner.id === current)) {
          return current
        }
        return data.items[0]?.id ?? null
      })
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось загрузить партнёров.'))
    } finally {
      setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadPartners()
  }, [loadPartners])

  useEffect(() => {
    setTestResult(null)
    if (selectedPartner) {
      setForm(formFromPartner(selectedPartner))
    } else {
      setForm(emptyForm())
    }
  }, [selectedPartner])

  const patchForm = (patch: Partial<PartnerFormState>) => {
    setForm((current) => ({ ...current, ...patch }))
  }

  const updateMappingRow = (rowId: string, patch: Partial<MappingRow>) => {
    setForm((current) => ({
      ...current,
      mappingRows: current.mappingRows.map((row) =>
        row.id === rowId ? { ...row, ...patch } : row,
      ),
    }))
  }

  const savePartner = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isSaving) {
      return
    }
    setIsSaving(true)
    setError('')
    setNotice('')
    setTestResult(null)
    try {
      const payload = toPayload(projectId, form)
      const saved = selectedPartner
        ? await updatePartnerIntegration(selectedPartner.id, projectId, payload)
        : await createPartnerIntegration(payload)
      setNotice(selectedPartner ? 'Интеграция обновлена.' : 'Интеграция создана.')
      await loadPartners()
      setSelectedPartnerId(saved.id)
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось сохранить интеграцию.'))
    } finally {
      setIsSaving(false)
    }
  }

  const togglePartner = async (partner: PartnerIntegration) => {
    if (!projectId) {
      return
    }
    setError('')
    setNotice('')
    try {
      await updatePartnerIntegration(partner.id, projectId, { is_active: !partner.is_active })
      await loadPartners()
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось изменить активность интеграции.'))
    }
  }

  const deletePartner = async (partner: PartnerIntegration) => {
    if (!projectId || !window.confirm(`Удалить интеграцию "${partner.name}"?`)) {
      return
    }
    setError('')
    setNotice('')
    try {
      await deletePartnerIntegration(partner.id, projectId)
      setSelectedPartnerId(null)
      await loadPartners()
      setNotice('Интеграция удалена.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось удалить интеграцию.'))
    }
  }

  const runTest = async () => {
    if (!projectId || !selectedPartner || testingPartnerId) {
      return
    }
    setTestingPartnerId(selectedPartner.id)
    setError('')
    setNotice('')
    try {
      const result = await testPartnerConnection(selectedPartner.id, projectId)
      setTestResult(result)
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось протестировать соединение.'))
    } finally {
      setTestingPartnerId(null)
    }
  }

  if (!projectId) {
    return (
      <div className="rounded-lg border border-white/5 bg-white/[0.02] p-5 text-sm text-zinc-400">
        Выберите проект перед настройкой партнёров.
      </div>
    )
  }

  return (
    <div className="grid min-h-0 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
      <section className="min-h-0 rounded-lg border border-white/5 bg-white/[0.02]">
        <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Партнёры</h2>
            <p className="text-xs text-zinc-500">Интеграции текущего проекта</p>
          </div>
          <button
            type="button"
            onClick={() => {
              setSelectedPartnerId(null)
              setForm(emptyForm())
              setTestResult(null)
            }}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 text-sm font-medium text-zinc-200 transition hover:border-emerald-400/50 hover:text-white"
          >
            <Plus size={16} />
            Новый
          </button>
        </div>

        {error ? (
          <div className="m-4 rounded-lg border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="m-4 rounded-lg border border-emerald-400/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
            {notice}
          </div>
        ) : null}

        <div className="max-h-[560px] overflow-y-auto p-3">
          {isLoading ? (
            <div className="flex items-center justify-center py-10 text-sm text-zinc-500">
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Загрузка партнёров
            </div>
          ) : null}
          {!isLoading && partners.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/10 p-5 text-sm text-zinc-500">
              Интеграций пока нет.
            </div>
          ) : null}
          <div className="space-y-2">
            {partners.map((partner) => (
              <div
                key={partner.id}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedPartnerId(partner.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    setSelectedPartnerId(partner.id)
                  }
                }}
                className={`w-full rounded-lg border p-3 text-left transition ${
                  selectedPartnerId === partner.id
                    ? 'border-emerald-400/50 bg-emerald-500/10'
                    : 'border-white/5 bg-[#090E18] hover:border-white/15'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-zinc-100">
                      {partner.name}
                    </div>
                    <div className="mt-1 truncate text-xs text-zinc-500">
                      {partner.postback_url}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-1 text-[11px] font-semibold ${
                      partner.is_active
                        ? 'bg-emerald-400/10 text-emerald-300'
                        : 'bg-zinc-700/50 text-zinc-400'
                    }`}
                  >
                    {partner.is_active ? 'Активна' : 'Выкл'}
                  </span>
                </div>
                <div className="mt-3 flex items-center justify-between gap-2">
                  <label className="inline-flex items-center gap-2 text-xs text-zinc-400">
                    <input
                      type="checkbox"
                      checked={partner.is_active}
                      onChange={() => void togglePartner(partner)}
                      onClick={(event) => event.stopPropagation()}
                      className="h-4 w-4 accent-emerald-500"
                    />
                    Быстрая активация
                  </label>
                  <span className="font-mono text-[11px] text-zinc-600">{partner.auth_type}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <form className="min-w-0 space-y-5" onSubmit={savePartner}>
        <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-zinc-100">
                {selectedPartner ? 'Редактирование интеграции' : 'Новая интеграция'}
              </h3>
              <p className="text-sm text-zinc-500">URL, авторизация и правила postback.</p>
            </div>
            {selectedPartner ? (
              <button
                type="button"
                onClick={() => void deletePartner(selectedPartner)}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-400/30 px-3 text-sm font-medium text-red-200 transition hover:bg-red-500/10"
              >
                <Trash2 size={15} />
                Удалить
              </button>
            ) : null}
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                Название
              </span>
              <input
                value={form.name}
                onChange={(event) => patchForm({ name: event.target.value })}
                required
                maxLength={255}
                className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                API Endpoint URL
              </span>
              <input
                value={form.postback_url}
                onChange={(event) => patchForm({ postback_url: event.target.value })}
                required
                className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
              />
            </label>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-4">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                Тип авторизации
              </span>
              <select
                value={form.auth_type}
                onChange={(event) => patchForm({ auth_type: event.target.value as AuthType })}
                className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
              >
                <option value="bearer">Bearer</option>
                <option value="header">Header</option>
                <option value="query_param">Query param</option>
              </select>
            </label>
            {form.auth_type === 'header' ? (
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                  Header name
                </span>
                <input
                  value={form.header_name}
                  onChange={(event) => patchForm({ header_name: event.target.value })}
                  className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
                />
              </label>
            ) : null}
            {form.auth_type === 'query_param' ? (
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                  Param name
                </span>
                <input
                  value={form.query_param_name}
                  onChange={(event) => patchForm({ query_param_name: event.target.value })}
                  className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
                />
              </label>
            ) : null}
            <label className="block lg:col-span-2">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
                Токен
              </span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-600" size={15} />
                <input
                  type="password"
                  value={form.token}
                  onChange={(event) => patchForm({ token: event.target.value })}
                  className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] pl-9 pr-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
                />
              </div>
            </label>
          </div>
        </section>

        <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-zinc-100">Field Mapping</h3>
              <p className="text-sm text-zinc-500">Слева поле партнёра, справа путь в CRM-лиде.</p>
            </div>
            <button
              type="button"
              onClick={() => patchForm({ mappingRows: [...form.mappingRows, emptyMappingRow()] })}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-zinc-200 transition hover:border-emerald-400/50"
            >
              <Plus size={15} />
              Поле
            </button>
          </div>
          <div className="space-y-2">
            {form.mappingRows.map((row) => {
              const isKnownOption = leadFieldOptions.some((option) => option.value === row.leadPath)
              return (
                <div key={row.id} className="grid gap-2 rounded-lg border border-white/5 bg-[#090E18] p-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_120px_36px]">
                  <input
                    value={row.partnerKey}
                    onChange={(event) => updateMappingRow(row.id, { partnerKey: event.target.value })}
                    placeholder="partner_field"
                    className="h-9 rounded-lg border border-white/10 bg-[#050914] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
                  />
                  <div className="grid gap-2 sm:grid-cols-[180px_minmax(0,1fr)]">
                    <select
                      value={isKnownOption ? row.leadPath : '__custom__'}
                      onChange={(event) => {
                        const value = event.target.value
                        updateMappingRow(row.id, {
                          leadPath: value === '__custom__' ? 'custom_fields.' : value,
                        })
                      }}
                      className="h-9 rounded-lg border border-white/10 bg-[#050914] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60"
                    >
                      {leadFieldOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    <input
                      value={row.leadPath}
                      onChange={(event) => updateMappingRow(row.id, { leadPath: event.target.value })}
                      className="h-9 rounded-lg border border-white/10 bg-[#050914] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60"
                    />
                  </div>
                  <label className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-zinc-300">
                    <input
                      type="checkbox"
                      checked={row.isRequired}
                      onChange={(event) => updateMappingRow(row.id, { isRequired: event.target.checked })}
                      className="h-4 w-4 accent-emerald-500"
                    />
                    Required
                  </label>
                  <button
                    type="button"
                    title="Удалить поле"
                    onClick={() => patchForm({ mappingRows: form.mappingRows.filter((item) => item.id !== row.id) })}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-zinc-500 transition hover:border-red-400/40 hover:text-red-300"
                  >
                    <X size={15} />
                  </button>
                </div>
              )
            })}
          </div>
        </section>

        <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
          <h3 className="text-base font-semibold text-zinc-100">Response Mapping</h3>
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Success key</span>
              <input value={form.success_key} onChange={(event) => patchForm({ success_key: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Success value</span>
              <input value={form.success_value} onChange={(event) => patchForm({ success_value: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Error path</span>
              <input value={form.error_path} onChange={(event) => patchForm({ error_path: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Duplicate key</span>
              <input value={form.duplicate_key} onChange={(event) => patchForm({ duplicate_key: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Duplicate value</span>
              <input value={form.duplicate_value} onChange={(event) => patchForm({ duplicate_value: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Rejected value</span>
              <input value={form.rejected_value} onChange={(event) => patchForm({ rejected_value: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">External ID path</span>
              <input value={form.external_id_path} onChange={(event) => patchForm({ external_id_path: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Partner status path</span>
              <input value={form.partner_status_path} onChange={(event) => patchForm({ partner_status_path: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
          </div>
        </section>

        <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
          <div className="grid gap-3 lg:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Max attempts</span>
              <input type="number" min={1} max={10} value={form.max_attempts} onChange={(event) => patchForm({ max_attempts: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Timeout sec</span>
              <input type="number" min={1} max={120} value={form.timeout_seconds} onChange={(event) => patchForm({ timeout_seconds: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-sm text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Retry delays</span>
              <input value={form.delays_seconds} onChange={(event) => patchForm({ delays_seconds: event.target.value })} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-xs text-zinc-100 outline-none focus:border-emerald-400/60" />
            </label>
          </div>

          {testResult ? (
            <div className={`mt-4 rounded-lg border px-4 py-3 text-sm ${testResult.ok ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-100' : 'border-red-400/30 bg-red-500/10 text-red-100'}`}>
              <div className="flex items-center gap-2 font-semibold">
                {testResult.ok ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                {testResult.ok
                  ? `Соединение успешно, партнёр вернул статус ${testResult.status}.`
                  : testResult.error_message || `Партнёр вернул статус ${testResult.status}.`}
              </div>
              <pre className="mt-3 max-h-44 overflow-auto rounded-lg border border-white/5 bg-[#0a0f1d] p-3 text-xs text-zinc-300">
                {formatJson({
                  status_code: testResult.status_code,
                  request_payload: testResult.request_payload,
                  parsed_response: testResult.parsed_response,
                  response_payload: testResult.response_payload,
                })}
              </pre>
            </div>
          ) : null}

          <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={() => void runTest()}
              disabled={!selectedPartner || Boolean(testingPartnerId)}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-4 text-sm font-semibold text-zinc-100 transition hover:border-emerald-400/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {testingPartnerId ? <LoaderCircle size={16} className="animate-spin" /> : <PlugZap size={16} />}
              Тестировать соединение
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSaving ? <LoaderCircle size={16} className="animate-spin" /> : selectedPartner ? <Pencil size={16} /> : <Save size={16} />}
              {selectedPartner ? 'Сохранить изменения' : 'Создать интеграцию'}
            </button>
          </div>
        </section>
      </form>
    </div>
  )
}

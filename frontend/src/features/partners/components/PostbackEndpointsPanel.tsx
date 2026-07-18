import axios from 'axios'
import {
  Check,
  Copy,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Trash2,
  Webhook,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import api from '../../../api/client'

type IdentifierType =
  | 'lead_id'
  | 'chat_id'
  | 'telegram_id'
  | 'tracking_code'
  | 'external_id'
  | 'click_id'

type ParameterMapping = {
  identifier_type: IdentifierType
  identifier_param: string
  amount_param: string | null
  currency_param: string | null
  event_type_param: string | null
  external_event_id_param: string | null
}

type PostbackEndpoint = {
  id: string
  project_id: string
  partner_integration_id: string | null
  name: string
  event_type: string
  parameter_mapping: ParameterMapping
  is_active: boolean
  url: string
  created_at: string
  updated_at: string
}

type PostbackReceipt = {
  id: string
  lead_id: string | null
  request_method: string
  event_type: string
  status: 'processed' | 'unmatched' | 'duplicate' | string
  error_message: string | null
  created_at: string
}

type FormState = {
  name: string
  eventType: string
  identifierType: IdentifierType
  identifierParam: string
  amountParam: string
  currencyParam: string
  eventTypeParam: string
  externalEventIdParam: string
  isActive: boolean
}

const emptyForm = (): FormState => ({
  name: '',
  eventType: 'registration',
  identifierType: 'lead_id',
  identifierParam: 'lead_id',
  amountParam: 'amount',
  currencyParam: 'currency',
  eventTypeParam: '',
  externalEventIdParam: 'event_id',
  isActive: true,
})

function getErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    if (error.code === 'ERR_NETWORK') return 'API недоступен.'
  }
  return 'Не удалось выполнить операцию с постбеком.'
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export default function PostbackEndpointsPanel({
  projectId,
  partnerIntegrationId,
}: {
  projectId: string
  partnerIntegrationId: string | null
}) {
  const [endpoints, setEndpoints] = useState<PostbackEndpoint[]>([])
  const [selectedEndpointId, setSelectedEndpointId] = useState<string | null>(null)
  const [editingEndpointId, setEditingEndpointId] = useState<string | null>(null)
  const [receipts, setReceipts] = useState<PostbackReceipt[]>([])
  const [form, setForm] = useState<FormState>(() => emptyForm())
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isLoadingReceipts, setIsLoadingReceipts] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const selectedEndpoint = useMemo(
    () => endpoints.find((item) => item.id === selectedEndpointId) ?? null,
    [endpoints, selectedEndpointId],
  )

  const loadEndpoints = useCallback(async () => {
    if (!partnerIntegrationId) {
      setEndpoints([])
      setSelectedEndpointId(null)
      return
    }
    setIsLoading(true)
    setError('')
    try {
      const { data } = await api.get<PostbackEndpoint[]>('/postback-endpoints', {
        params: {
          project_id: projectId,
          partner_integration_id: partnerIntegrationId,
        },
      })
      setEndpoints(data)
      setSelectedEndpointId((current) => (
        current && data.some((item) => item.id === current)
          ? current
          : data[0]?.id ?? null
      ))
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setIsLoading(false)
    }
  }, [partnerIntegrationId, projectId])

  const loadReceipts = useCallback(async () => {
    if (!selectedEndpointId) {
      setReceipts([])
      return
    }
    setIsLoadingReceipts(true)
    try {
      const { data } = await api.get<PostbackReceipt[]>(
        `/postback-endpoints/${selectedEndpointId}/receipts`,
        { params: { project_id: projectId, limit: 30 } },
      )
      setReceipts(data)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setIsLoadingReceipts(false)
    }
  }, [projectId, selectedEndpointId])

  useEffect(() => {
    setEditingEndpointId(null)
    setForm(emptyForm())
    void loadEndpoints()
  }, [loadEndpoints])

  useEffect(() => {
    void loadReceipts()
  }, [loadReceipts])

  const startEdit = (endpoint: PostbackEndpoint) => {
    setEditingEndpointId(endpoint.id)
    setForm({
      name: endpoint.name,
      eventType: endpoint.event_type,
      identifierType: endpoint.parameter_mapping.identifier_type,
      identifierParam: endpoint.parameter_mapping.identifier_param,
      amountParam: endpoint.parameter_mapping.amount_param ?? '',
      currencyParam: endpoint.parameter_mapping.currency_param ?? '',
      eventTypeParam: endpoint.parameter_mapping.event_type_param ?? '',
      externalEventIdParam: endpoint.parameter_mapping.external_event_id_param ?? '',
      isActive: endpoint.is_active,
    })
  }

  const saveEndpoint = async () => {
    if (!partnerIntegrationId || isSaving || !form.name.trim() || !form.eventType.trim()) return
    setIsSaving(true)
    setError('')
    setNotice('')
    const payload = {
      partner_integration_id: partnerIntegrationId,
      name: form.name.trim(),
      event_type: form.eventType.trim().toLowerCase(),
      parameter_mapping: {
        identifier_type: form.identifierType,
        identifier_param: form.identifierParam.trim(),
        amount_param: form.amountParam.trim() || null,
        currency_param: form.currencyParam.trim() || null,
        event_type_param: form.eventTypeParam.trim() || null,
        external_event_id_param: form.externalEventIdParam.trim() || null,
      },
      is_active: form.isActive,
    }
    try {
      const { data } = editingEndpointId
        ? await api.patch<PostbackEndpoint>(
            `/postback-endpoints/${editingEndpointId}`,
            payload,
            { params: { project_id: projectId } },
          )
        : await api.post<PostbackEndpoint>('/postback-endpoints', payload, {
            params: { project_id: projectId },
          })
      setNotice(editingEndpointId ? 'Endpoint обновлён.' : 'Endpoint создан.')
      setEditingEndpointId(null)
      setForm(emptyForm())
      await loadEndpoints()
      setSelectedEndpointId(data.id)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setIsSaving(false)
    }
  }

  const toggleEndpoint = async (endpoint: PostbackEndpoint) => {
    try {
      await api.patch(
        `/postback-endpoints/${endpoint.id}`,
        { is_active: !endpoint.is_active },
        { params: { project_id: projectId } },
      )
      await loadEndpoints()
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
  }

  const rotateSecret = async (endpoint: PostbackEndpoint) => {
    if (!window.confirm('Старый URL сразу перестанет принимать постбеки. Продолжить?')) return
    try {
      const { data } = await api.post<PostbackEndpoint>(
        `/postback-endpoints/${endpoint.id}/rotate-secret`,
        null,
        { params: { project_id: projectId } },
      )
      setEndpoints((current) => current.map((item) => (item.id === data.id ? data : item)))
      setNotice('Секрет заменён. Передайте партнёру новый URL.')
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
  }

  const deleteEndpoint = async (endpoint: PostbackEndpoint) => {
    if (!window.confirm(`Удалить endpoint «${endpoint.name}» и его журнал?`)) return
    try {
      await api.delete(`/postback-endpoints/${endpoint.id}`, {
        params: { project_id: projectId },
      })
      setSelectedEndpointId(null)
      setEditingEndpointId(null)
      await loadEndpoints()
      setNotice('Endpoint удалён.')
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
  }

  if (!partnerIntegrationId) {
    return (
      <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4 text-sm text-zinc-500">
        Сначала сохраните интеграцию партнёра, затем настройте URL для входящих постбеков.
      </section>
    )
  }

  return (
    <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Webhook size={17} className="text-cyan-200" />
            <h3 className="text-base font-semibold text-zinc-100">Входящие постбеки</h3>
          </div>
          <p className="mt-1 text-sm leading-5 text-zinc-500">
            Регистрации, депозиты, RD и кастомные события из CRM партнёра.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditingEndpointId(null)
            setForm(emptyForm())
          }}
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-zinc-200 transition hover:border-cyan-300/40"
        >
          <Plus size={15} /> Новый endpoint
        </button>
      </div>

      {error ? <p className="mt-3 rounded-lg border border-red-300/20 bg-red-500/10 px-3 py-2 text-sm text-red-100">{error}</p> : null}
      {notice ? <p className="mt-3 rounded-lg border border-emerald-300/20 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">{notice}</p> : null}

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(260px,0.8fr)_minmax(0,1.2fr)]">
        <div className="space-y-2">
          {isLoading ? <div className="flex items-center gap-2 py-4 text-sm text-zinc-500"><LoaderCircle size={15} className="animate-spin" /> Загрузка</div> : null}
          {!isLoading && endpoints.length === 0 ? (
            <div className="rounded-lg border border-dashed border-white/10 px-3 py-4 text-sm text-zinc-500">Endpoint пока не создан.</div>
          ) : null}
          {endpoints.map((endpoint) => (
            <div
              key={endpoint.id}
              className={`rounded-lg border p-3 ${selectedEndpointId === endpoint.id ? 'border-cyan-300/35 bg-cyan-400/[0.06]' : 'border-white/5 bg-[#090E18]'}`}
            >
              <button type="button" onClick={() => setSelectedEndpointId(endpoint.id)} className="w-full text-left">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-zinc-100">{endpoint.name}</span>
                  <span className={`shrink-0 text-xs ${endpoint.is_active ? 'text-emerald-300' : 'text-zinc-600'}`}>{endpoint.is_active ? 'Активен' : 'Выключен'}</span>
                </div>
                <p className="mt-1 truncate font-mono text-xs text-zinc-500">{endpoint.event_type}</p>
              </button>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <button type="button" title="Редактировать" onClick={() => startEdit(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 hover:text-white"><Pencil size={14} /></button>
                <button type="button" title={endpoint.is_active ? 'Выключить' : 'Включить'} onClick={() => void toggleEndpoint(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 hover:text-white">{endpoint.is_active ? <X size={14} /> : <Check size={14} />}</button>
                <button type="button" title="Заменить секрет" onClick={() => void rotateSecret(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 hover:text-white"><RotateCw size={14} /></button>
                <button type="button" title="Удалить endpoint" onClick={() => void deleteEndpoint(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-red-300/15 text-red-200/70 hover:text-red-100"><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="mb-1 block text-xs uppercase text-zinc-500">Название endpoint</span>
              <input value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder="Депозиты партнёра" className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-base text-zinc-100 outline-none focus:border-cyan-300/40 md:text-sm" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs uppercase text-zinc-500">Тип события</span>
              <input list="postback-event-types" value={form.eventType} onChange={(event) => setForm((current) => ({ ...current, eventType: event.target.value }))} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-base text-zinc-100 outline-none focus:border-cyan-300/40 md:text-sm" />
              <datalist id="postback-event-types"><option value="registration" /><option value="deposit" /><option value="redeposit" /></datalist>
            </label>
            <label className="block">
              <span className="mb-1 block text-xs uppercase text-zinc-500">Как найти лида</span>
              <select value={form.identifierType} onChange={(event) => setForm((current) => ({ ...current, identifierType: event.target.value as IdentifierType }))} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 text-base text-zinc-100 outline-none focus:border-cyan-300/40 md:text-sm">
                <option value="lead_id">CRM Lead ID</option><option value="chat_id">CRM Chat ID</option><option value="telegram_id">Telegram ID</option><option value="tracking_code">Tracking code</option><option value="external_id">External submission ID</option><option value="click_id">Click ID</option>
              </select>
            </label>
            {([
              ['identifierParam', 'Параметр идентификатора'],
              ['amountParam', 'Параметр суммы'],
              ['currencyParam', 'Параметр валюты'],
              ['eventTypeParam', 'Параметр типа события'],
              ['externalEventIdParam', 'Уникальный ID события'],
            ] as const).map(([key, label]) => (
              <label key={key} className="block">
                <span className="mb-1 block text-xs uppercase text-zinc-500">{label}</span>
                <input value={form[key]} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-base text-zinc-100 outline-none focus:border-cyan-300/40 md:text-sm" />
              </label>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <label className="inline-flex items-center gap-2 text-sm text-zinc-300"><input type="checkbox" checked={form.isActive} onChange={(event) => setForm((current) => ({ ...current, isActive: event.target.checked }))} className="h-4 w-4 accent-emerald-500" /> Endpoint активен</label>
            <button type="button" onClick={() => void saveEndpoint()} disabled={isSaving || !form.name.trim() || !form.identifierParam.trim()} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-cyan-300 px-4 text-sm font-semibold text-[#071018] transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50">{isSaving ? <LoaderCircle size={15} className="animate-spin" /> : editingEndpointId ? <Pencil size={15} /> : <Plus size={15} />}{editingEndpointId ? 'Сохранить endpoint' : 'Создать endpoint'}</button>
          </div>
        </div>
      </div>

      {selectedEndpoint ? (
        <div className="mt-5 border-t border-white/5 pt-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-medium text-zinc-200">URL для партнёра</p>
              <code className="mt-1 block truncate text-xs text-cyan-100">{selectedEndpoint.url}</code>
            </div>
            <button type="button" onClick={() => void navigator.clipboard.writeText(selectedEndpoint.url)} className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-zinc-200"><Copy size={14} /> Копировать</button>
          </div>
          <div className="mt-4 flex items-center justify-between gap-3">
            <h4 className="text-sm font-semibold text-zinc-100">Последние запросы</h4>
            <button type="button" title="Обновить журнал" onClick={() => void loadReceipts()} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400">{isLoadingReceipts ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />}</button>
          </div>
          <div className="mt-2 max-h-72 overflow-y-auto rounded-lg border border-white/5">
            {receipts.length === 0 ? <div className="px-3 py-5 text-sm text-zinc-500">Запросов пока нет.</div> : receipts.map((receipt) => (
              <div key={receipt.id} className="grid gap-1 border-b border-white/5 px-3 py-2.5 text-xs last:border-b-0 sm:grid-cols-[90px_110px_minmax(0,1fr)_auto] sm:items-center">
                <span className={receipt.status === 'processed' ? 'text-emerald-300' : receipt.status === 'duplicate' ? 'text-amber-200' : 'text-red-200'}>{receipt.status}</span>
                <span className="font-mono text-zinc-400">{receipt.event_type}</span>
                <span className="truncate text-zinc-500">{receipt.error_message || (receipt.lead_id ? `Lead ${receipt.lead_id}` : 'Без ошибки')}</span>
                <span className="text-zinc-600">{formatDate(receipt.created_at)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

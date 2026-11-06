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
  | 'submission_id'
  | 'player_id'
  | 'offer_token'

type ParameterMapping = {
  offer_id?: string | null
  identifier_type: IdentifierType
  identifier_param: string
  amount_param: string | null
  currency_param: string | null
  event_type_param: string | null
  external_event_id_param: string | null
  occurred_at_param?: string | null
  time_format?: 'iso' | 'unix_seconds' | 'unix_ms'
  require_event_id?: boolean
  status_mapping?: Record<string, string>
  status_transitions?: Record<string, string[]>
  event_aliases?: Record<string, string>
  allowed_event_types?: string[]
  event_namespace?: string | null
  ack_text?: string | null
  bind_external_id_param?: string | null
  bind_external_type?: 'player_id' | 'click_id' | 'external_id'
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
  delivery_mode?: 'direct' | 'relay'
  processing_kind?: 'lifecycle_event' | 'submission_status'
  revision?: number
  is_archived?: boolean
  created_at: string
  updated_at: string
}

type PostbackReceipt = {
  received_at?: string
  occurred_at?: string
  endpoint_revision?: number
  processed_at?: string
  submission_id?: string | null
  query_payload?: Record<string, unknown>
  body_payload?: Record<string, unknown>
  attempt_log?: Record<string, unknown>[]
  id: string
  lead_id: string | null
  request_method: string
  event_type: string
  status: 'processed' | 'unmatched' | 'duplicate' | string
  error_message: string | null
  created_at: string
}

type FormState = {
  processingKind: 'lifecycle_event' | 'submission_status'
  partnerId: string
  name: string
  eventType: string
  identifierType: IdentifierType
  identifierParam: string
  amountParam: string
  currencyParam: string
  eventTypeParam: string
  externalEventIdParam: string
  isActive: boolean
  occurredAtParam: string
  timeFormat: 'iso' | 'unix_seconds' | 'unix_ms'
  requireEventId: boolean
  statusMapping: string
  transitions: string
  aliases: string
  eventNamespace: string
  ackText: string
  bindExternalIdParam: string
  allowedEventTypes: string[]
  bindExternalType: 'player_id' | 'click_id' | 'external_id'
}

const emptyForm = (): FormState => ({
  processingKind: 'lifecycle_event', partnerId: '',
  name: '',
  eventType: 'registration',
  identifierType: 'lead_id',
  identifierParam: 'lead_id',
  amountParam: 'amount',
  currencyParam: 'currency',
  eventTypeParam: '',
  externalEventIdParam: 'event_id',
  isActive: true,
  occurredAtParam: '', timeFormat: 'iso', requireEventId: true,
  statusMapping: '{}', transitions: '{}', aliases: '{}', eventNamespace: '',
  ackText: '', bindExternalIdParam: '', allowedEventTypes: ['registration', 'deposit', 'redeposit'],
  bindExternalType: 'player_id',
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
  partners = [],
}: {
  projectId: string
  partnerIntegrationId: string | null
  partners?: { id: string; name: string }[]
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
  const [transport, setTransport] = useState<{ origin: string; mode: string; configuration_status: string; gateway_reachable: boolean;
    last_heartbeat_age_seconds: number | null; queue?: { counts?: Record<string, number>; oldest_pending_seconds?: number }; legacy_status_route_enabled: boolean } | null>(null)
  const [sample, setSample] = useState('{}')
  const [preview, setPreview] = useState<unknown>(null)
  const [isTesting, setIsTesting] = useState(false)
  const [bindingType, setBindingType] = useState('player_id')
  const [bindingId, setBindingId] = useState('')
  const [bindingLeadId, setBindingLeadId] = useState('')
  const [followups, setFollowups] = useState<{ id: string; kind: string; error: string }[]>([])
  const [includeArchived, setIncludeArchived] = useState(false)
  const loadFollowups = useCallback(() => {
    void api.get('/postback-endpoints/followups', { params: { project_id: projectId } })
      .then(({ data }) => setFollowups(data)).catch(() => setError('Не удалось проверить внешние отправки постбэков'))
  }, [projectId])

  const selectedEndpoint = useMemo(
    () => endpoints.find((item) => item.id === selectedEndpointId) ?? null,
    [endpoints, selectedEndpointId],
  )

  const loadEndpoints = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const { data } = await api.get<PostbackEndpoint[]>('/postback-endpoints', {
        params: {
          project_id: projectId,
          partner_integration_id: partnerIntegrationId || undefined,
          include_archived: includeArchived,
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
  }, [partnerIntegrationId, projectId, includeArchived])

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
    const controller = new AbortController()
    const refresh = () => { void api.get('/postback-endpoints/transport', { params: { project_id: projectId }, signal: controller.signal })
      .then(({ data }) => { if (!controller.signal.aborted) setTransport(data) })
      .catch(() => { if (!controller.signal.aborted) { setTransport(null); setError('Не удалось загрузить домен и состояние приёмника') } })
      loadFollowups()
    }
    refresh()
    const interval = window.setInterval(refresh, 30000)
    return () => { controller.abort(); window.clearInterval(interval) }
  }, [projectId, loadFollowups])

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
      processingKind: endpoint.processing_kind ?? 'lifecycle_event', partnerId: endpoint.partner_integration_id ?? '',
      occurredAtParam: endpoint.parameter_mapping.occurred_at_param ?? '',
      timeFormat: endpoint.parameter_mapping.time_format ?? 'iso',
      requireEventId: endpoint.parameter_mapping.require_event_id ?? false,
      statusMapping: JSON.stringify(endpoint.parameter_mapping.status_mapping ?? {}, null, 2),
      transitions: JSON.stringify(endpoint.parameter_mapping.status_transitions ?? {}, null, 2),
      aliases: JSON.stringify(endpoint.parameter_mapping.event_aliases ?? {}, null, 2),
      eventNamespace: endpoint.parameter_mapping.event_namespace ?? '',
      ackText: endpoint.parameter_mapping.ack_text ?? '',
      bindExternalIdParam: endpoint.parameter_mapping.bind_external_id_param ?? '',
      allowedEventTypes: endpoint.parameter_mapping.allowed_event_types ?? [],
      bindExternalType: endpoint.parameter_mapping.bind_external_type ?? 'player_id',
    })
  }

  const saveEndpoint = async () => {
    if (isSaving || !form.name.trim() || !form.eventType.trim()) return
    let statusMapping, transitions, aliases
    try {
      statusMapping = JSON.parse(form.statusMapping); transitions = JSON.parse(form.transitions); aliases = JSON.parse(form.aliases)
    } catch { setError('Проверьте JSON правил статусов и событий'); return }
    setIsSaving(true)
    setError('')
    setNotice('')
    const payload = {
      partner_integration_id: form.partnerId || partnerIntegrationId || null,
      processing_kind: form.processingKind,
      name: form.name.trim(),
      event_type: form.eventType.trim().toLowerCase(),
      parameter_mapping: {
        identifier_type: form.identifierType,
        identifier_param: form.identifierParam.trim(),
        amount_param: form.amountParam.trim() || null,
        currency_param: form.currencyParam.trim() || null,
        event_type_param: form.eventTypeParam.trim() || null,
        external_event_id_param: form.externalEventIdParam.trim() || null,
        occurred_at_param: form.occurredAtParam.trim() || null,
        time_format: form.timeFormat, require_event_id: form.requireEventId,
        status_mapping: statusMapping, status_transitions: transitions, event_aliases: aliases,
        event_namespace: form.eventNamespace.trim() || null,
        allowed_event_types: form.processingKind === 'lifecycle_event' ? form.allowedEventTypes : [],
        ack_text: form.ackText || null,
        bind_external_id_param: form.bindExternalIdParam.trim() || null,
        bind_external_type: form.bindExternalType,
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
    if (!window.confirm('Заменить секрет? Старый адрес останется действующим на настроенный сервером период перехода.')) return
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
    if (!window.confirm(`Архивировать «${endpoint.name}»? Новый приём остановится, журнал сохранится.`)) return
    try {
      await api.delete(`/postback-endpoints/${endpoint.id}`, {
        params: { project_id: projectId },
      })
      setSelectedEndpointId(null)
      setEditingEndpointId(null)
      await loadEndpoints()
      setNotice('Endpoint архивирован. Журнал сохранён.')
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
  }

  return (
    <section className="min-w-0 space-y-4">
      <div className="space-y-2 border-b border-white/10 pb-4">
        <span className="text-xs uppercase text-zinc-400">Наш домен приёма</span>
        <div className="flex min-w-0 items-center gap-2"><strong className="min-w-0 break-all text-lg text-zinc-100">{transport?.origin ?? 'Не загружен'}</strong>
          <button type="button" title="Скопировать домен приёмника" disabled={!transport}
            onClick={() => transport && void navigator.clipboard.writeText(transport.origin)} className="shrink-0 p-2 disabled:opacity-40"><Copy size={16} /></button>
        </div>
        <p className="text-sm text-zinc-400">{transport?.mode === 'relay' ? `Отдельный сервер · ${transport.gateway_reachable ? 'Связь есть' : 'Нет свежего сигнала связи'}` : 'Прямой приём CRM'}</p>
        {transport?.configuration_status === 'relay_waiting_for_domain' && <p role="alert" className="text-sm text-amber-200">Для отдельного приёмника ещё не задан публичный домен. Сейчас отображается прямой адрес CRM.</p>}
        {transport?.queue && <p className="text-xs text-zinc-400">Очередь: {transport.queue.counts?.pending ?? 0} · Ошибки доставки: {transport.queue.counts?.dead ?? 0} · Возраст ожидания: {Math.round(transport.queue.oldest_pending_seconds ?? 0)} сек</p>}
        {transport?.legacy_status_route_enabled && <p className="text-xs text-amber-200">Режим совместимости старых обратных статусов включён на сервере.</p>}
      </div>
      {followups.length > 0 && <div role="alert" className="space-y-2 border-y border-amber-300/25 py-3 text-sm text-amber-100">
        <h4 className="font-semibold">Интеграции требуют сверки</h4>
        {followups.map(job => <div key={job.id} className="flex flex-wrap items-center gap-3">
          <span className="break-all">{job.kind} · {job.error}</span>
          {[false, true].map(retry => <button key={String(retry)} type="button" className="underline" onClick={() => {
            if (!window.confirm(retry ? 'Внешняя система проверена и сообщение точно не доставлено? Повтор может создать дубль, если оно уже доставлено.' : 'Подтвердить, что действие уже выполнено во внешней системе?')) return
            void api.post(`/postback-endpoints/followups/${job.id}/resolve`, null, { params: { project_id: projectId, retry } })
              .then(loadFollowups).catch(err => setError(getErrorMessage(err)))
          }}>{retry ? 'Повторить после сверки' : 'Подтвердить выполнено'}</button>)}
        </div>)}
      </div>}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Webhook size={17} className="text-cyan-200" />
            <h3 className="text-base font-semibold text-zinc-100">Входящие постбеки</h3>
          </div>
          <p className="mt-1 text-sm leading-5 text-zinc-500">
            События лида и обратные статусы подачи.
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
      <label className="flex items-center gap-2 text-sm text-zinc-400"><input type="checkbox" checked={includeArchived}
        onChange={e => setIncludeArchived(e.target.checked)} />Показывать архив</label>

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
                  <span className={`shrink-0 text-xs ${endpoint.is_active ? 'text-emerald-300' : 'text-zinc-600'}`}>{endpoint.is_archived ? 'Архив' : endpoint.is_active ? 'Активен' : 'Выключен'}</span>
                </div>
                <p className="mt-1 truncate font-mono text-xs text-zinc-500">{endpoint.event_type}</p>
                <p className="mt-1 text-xs text-zinc-400">{endpoint.delivery_mode === 'relay' ? 'Внешний приёмник' : 'Прямой приём CRM'}</p>
              </button>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {endpoint.is_archived ? <button type="button" className="text-xs text-cyan-200 underline" onClick={() => {
                  void api.post(`/postback-endpoints/${endpoint.id}/restore`, null, { params: { project_id: projectId } })
                    .then(() => loadEndpoints()).catch(err => setError(getErrorMessage(err)))
                }}>Восстановить выключенным</button> : <>
                <button type="button" disabled={!!endpoint.parameter_mapping.offer_id} title={endpoint.parameter_mapping.offer_id ? 'Правила редактируются в настройках оффера' : 'Редактировать'} onClick={() => startEdit(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 hover:text-white disabled:opacity-30"><Pencil size={14} /></button>
                <button type="button" title={endpoint.is_active ? 'Выключить' : 'Включить'} onClick={() => void toggleEndpoint(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 hover:text-white">{endpoint.is_active ? <X size={14} /> : <Check size={14} />}</button>
                <button type="button" title="Заменить секрет" onClick={() => void rotateSecret(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-zinc-400 hover:text-white"><RotateCw size={14} /></button>
                <button type="button" title="Удалить endpoint" onClick={() => void deleteEndpoint(endpoint)} className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-red-300/15 text-red-200/70 hover:text-red-100"><Trash2 size={14} /></button>
                </>}
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-3">
          <label className="block space-y-1 text-sm text-zinc-300">Обработка
            <select aria-label="Тип входящего постбэка" value={form.processingKind} onChange={e => setForm(current => ({ ...current, processingKind: e.target.value as FormState['processingKind'] }))}
              className="w-full rounded-md border border-white/10 bg-[#090E18] px-3 py-2">
              <option value="lifecycle_event">Событие лида · REG / FD / RD</option>
              <option value="submission_status">Обратный статус подачи</option>
            </select>
          </label>
          <label className="block space-y-1 text-sm text-zinc-300">Покупатель / интеграция
            <select aria-label="Покупатель постбэка" value={form.partnerId || partnerIntegrationId || ''}
              onChange={e => setForm(current => ({ ...current, partnerId: e.target.value }))}
              className="w-full rounded-md border border-white/10 bg-[#090E18] px-3 py-2">
              <option value="">Без исходящей подачи</option>
              {partners.map(partner => <option key={partner.id} value={partner.id}>{partner.name}</option>)}
            </select>
          </label>
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
                <option value="lead_id">CRM Lead ID</option><option value="chat_id">CRM Chat ID</option><option value="submission_id">CRM Submission ID</option><option value="telegram_id">Telegram ID · только точное единственное совпадение</option><option value="tracking_code" disabled>Tracking code · не идентифицирует человека</option><option value="external_id">External submission ID</option><option value="click_id">Click ID</option><option value="player_id">Player ID</option>
              </select>
            </label>
            {([
              ['identifierParam', 'Параметр идентификатора'],
              ['amountParam', 'Параметр суммы'],
              ['currencyParam', 'Параметр валюты'],
              ['eventTypeParam', 'Параметр типа события'],
              ['externalEventIdParam', 'Уникальный ID события'],
              ['occurredAtParam', 'Параметр времени события'],
              ['eventNamespace', 'Общее пространство ID событий'],
              ['bindExternalIdParam', 'Параметр Player ID для последующей привязки'],
              ['ackText', 'Текст ответа партнёру · необязательно'],
            ] as const).map(([key, label]) => (
              <label key={key} className="block">
                <span className="mb-1 block text-xs uppercase text-zinc-500">{label}</span>
                <input value={form[key]} onChange={(event) => setForm((current) => ({ ...current, [key]: event.target.value }))} className="h-10 w-full rounded-lg border border-white/10 bg-[#090E18] px-3 font-mono text-base text-zinc-100 outline-none focus:border-cyan-300/40 md:text-sm" />
              </label>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-300"><input type="checkbox" checked={form.requireEventId}
            onChange={e => setForm(current => ({ ...current, requireEventId: e.target.checked }))} />Требовать уникальный ID события</label>
          <label className="block space-y-1 text-sm text-zinc-300">Формат времени
            <select value={form.timeFormat} onChange={e => setForm(current => ({ ...current, timeFormat: e.target.value as FormState['timeFormat'] }))}
              className="w-full rounded-md border border-white/10 bg-[#090E18] px-3 py-2">
              <option value="iso">ISO 8601 с часовым поясом</option><option value="unix_seconds">Unix · секунды</option><option value="unix_ms">Unix · миллисекунды</option>
            </select>
          </label>
          {form.bindExternalIdParam && <label className="block space-y-1 text-sm text-zinc-300">Тип привязываемого ID
            <select value={form.bindExternalType} onChange={e => setForm(current => ({ ...current, bindExternalType: e.target.value as FormState['bindExternalType'] }))}
              className="w-full rounded-md border border-white/10 bg-[#090E18] p-2">
              <option value="player_id">Player ID</option><option value="click_id">Click ID</option><option value="external_id">External ID</option>
            </select>
          </label>}
          {(form.processingKind === 'submission_status' ? [['statusMapping', 'Статус партнёра → код статуса CRM'], ['transitions', 'Текущий статус → разрешённые следующие статусы']] : [['aliases', 'Алиасы событий']]).map(([key, label]) => (
            <label key={key} className="block space-y-1 text-sm text-zinc-300">{label} · JSON
              <textarea rows={3} value={form[key as 'statusMapping' | 'transitions' | 'aliases']} onChange={e => setForm(current => ({ ...current, [key]: e.target.value }))}
                className="w-full rounded-md border border-white/10 bg-[#090E18] p-2 font-mono text-sm" />
            </label>
          ))}
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
              <code className="mt-1 block break-all text-xs text-cyan-100">{selectedEndpoint.url}</code>
            </div>
            <button type="button" onClick={() => void navigator.clipboard.writeText(selectedEndpoint.url)} className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-zinc-200"><Copy size={14} /> Копировать</button>
          </div>
          <div className="mt-4 space-y-3 border-y border-white/10 py-4">
            <label className="block space-y-1 text-sm text-zinc-300">Образец входящего JSON
              <textarea aria-label="Образец постбэка" rows={4} value={sample} onChange={e => setSample(e.target.value)}
                className="w-full rounded-md border border-white/10 bg-[#090E18] p-2 font-mono text-sm" />
            </label>
            <button type="button" disabled={isTesting} onClick={() => {
              setIsTesting(true); setError(''); setPreview(null)
              void (async () => {
                try {
                  const payload = JSON.parse(sample)
                  const { data } = await api.post(`/postback-endpoints/${selectedEndpoint.id}/dry-run`, { body_payload: payload }, { params: { project_id: projectId } })
                  setPreview(data)
                } catch (err) { setError(getErrorMessage(err)) } finally { setIsTesting(false) }
              })()
            }} className="inline-flex items-center gap-2 rounded-md border border-white/15 px-3 py-2 text-sm disabled:opacity-40">
              {isTesting ? <LoaderCircle size={15} className="animate-spin" /> : <Check size={15} />}Проверить без записи
            </button>
            {preview !== null && <pre role="status" className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs text-cyan-100">{JSON.stringify(preview, null, 2)}</pre>}
            <details className="text-sm text-zinc-300"><summary>Привязка внешнего ID к карточке</summary>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <select aria-label="Тип внешнего ID" value={bindingType} onChange={e => setBindingType(e.target.value)} className="rounded-md bg-[#090E18] p-2">
                  <option value="player_id">Player ID</option><option value="click_id">Click ID</option><option value="external_id">External ID</option>
                </select>
                <input aria-label="Внешний ID" placeholder="Внешний ID" value={bindingId} onChange={e => setBindingId(e.target.value)} className="min-w-0 rounded-md bg-[#090E18] p-2" />
                <input aria-label="CRM Lead ID привязки" placeholder="CRM Lead ID" value={bindingLeadId} onChange={e => setBindingLeadId(e.target.value)} className="min-w-0 rounded-md bg-[#090E18] p-2" />
                <button type="button" disabled={!bindingId || !bindingLeadId} onClick={() => {
                  void api.post(`/postback-endpoints/${selectedEndpoint.id}/bindings`, { identifier_type: bindingType, external_id: bindingId, lead_id: bindingLeadId }, { params: { project_id: projectId } })
                    .then(() => setNotice('Привязка сохранена')).catch(err => setError(getErrorMessage(err)))
                }} className="rounded-md border border-white/15 px-3 py-2 disabled:opacity-40">Сохранить привязку</button>
              </div>
            </details>
            {selectedEndpoint.processing_kind === 'submission_status' && <button type="button" className="text-sm text-amber-200 underline"
              onClick={() => {
                if (!window.confirm('Партнёр уже переведён на новый секретный URL? Старый адрес обратных статусов будет закрыт.')) return
                void api.post(`/postback-endpoints/${selectedEndpoint.id}/close-legacy-status-route`, null, { params: { project_id: projectId } })
                  .then(() => setNotice('Старый адрес обратных статусов закрыт')).catch(err => setError(getErrorMessage(err)))
              }}>Закрыть старый адрес обратных статусов</button>}
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
                <span className="break-words text-zinc-500">{receipt.error_message || (receipt.lead_id ? `Lead ${receipt.lead_id}` : 'Без ошибки')}</span>
                <span className="text-zinc-600">{formatDate(receipt.created_at)}{receipt.endpoint_revision ? ` · v${receipt.endpoint_revision}` : ''}</span>
                {receipt.occurred_at && <span className="text-zinc-500 sm:col-span-4">Событие: {formatDate(receipt.occurred_at)} · Приём: {formatDate(receipt.received_at ?? receipt.created_at)}</span>}
                <details className="min-w-0 text-zinc-400 sm:col-span-4"><summary className="cursor-pointer">Детали запроса</summary>
                  <p className="mt-2 break-all">Квитанция: {receipt.id}{receipt.submission_id ? ` · Подача: ${receipt.submission_id}` : ''}</p>
                  {receipt.processed_at && <p>Обработано: {formatDate(receipt.processed_at)}</p>}
                  <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify({ query: receipt.query_payload ?? {}, body: receipt.body_payload ?? {}, attempts: receipt.attempt_log ?? [] }, null, 2)}</pre>
                </details>
                {['unmatched', 'ambiguous', 'invalid'].includes(receipt.status) && <button type="button" className="justify-self-start text-cyan-200 underline sm:col-span-4" onClick={() => {
                  if (!window.confirm('Повторно разобрать запрос по текущим сохранённым настройкам? История предыдущей попытки сохранится.')) return
                  void api.post(`/postback-endpoints/${selectedEndpoint.id}/receipts/${receipt.id}/reprocess`, null,
                    { params: { project_id: projectId, use_current_contract: true } }).then(() => loadReceipts()).catch(err => setError(getErrorMessage(err)))
                }}>Повторно разобрать</button>}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}

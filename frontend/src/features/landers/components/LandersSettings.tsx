import axios from 'axios'
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Copy,
  ExternalLink,
  Globe2,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Upload,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { fetchBots, type Bot } from '../../bots'
import { Modal } from '../../../shared/ui'
import {
  createProjectDomain,
  createProjectLander,
  deleteProjectDomain,
  deleteProjectLander,
  fetchActiveTrackingLinks,
  fetchLanderTargetSteps,
  fetchLanderRuntimeConfig,
  fetchProjectDomains,
  fetchProjectLanders,
  updateProjectLander,
  uploadProjectLanderZip,
} from '../api'
import type {
  LanderType,
  LanderPixel,
  LanderMetaEvent,
  FacebookEventMapping,
  FacebookSourceEvent,
  LanderRuntimeConfig,
  LanderTargetStep,
  ProjectDomain,
  ProjectLander,
  TrackingLinkOption,
} from '../types'

type LandersSettingsProps = {
  projectId: string | null
}

type Banner = {
  tone: 'success' | 'error'
  message: string
}

type LanderForm = {
  name: string
  domainId: string
  slug: string
  trackingMode: 'campaign' | 'existing'
  trackingLinkId: string
  campaignBotId: string
  campaignTitle: string
  campaignCode: string
  campaignBuyerName: string
  campaignAdType: string
  campaignPaymentType: string
  campaignFbPixelId: string
  campaignFbCapiToken: string
  campaignFbProxyUrl: string
  campaignFbTestEventCode: string
  campaignEventMappings: FacebookEventMapping[]
  campaignTargetStepKey: string
  metaPixelId: string
  metaEvents: string
  autoRedirectEnabled: boolean
  utmSource: string
  utmMedium: string
  utmCampaign: string
  utmTerm: string
  utmContent: string
  type: LanderType
  zipFile: File | null
}

const emptyLanderForm: LanderForm = {
  name: '',
  domainId: '',
  slug: '',
  trackingMode: 'campaign',
  trackingLinkId: '',
  campaignBotId: '',
  campaignTitle: '',
  campaignCode: '',
  campaignBuyerName: '',
  campaignAdType: '',
  campaignPaymentType: '',
  campaignFbPixelId: '',
  campaignFbCapiToken: '',
  campaignFbProxyUrl: '',
  campaignFbTestEventCode: '',
  campaignEventMappings: [],
  campaignTargetStepKey: '',
  metaPixelId: '',
  metaEvents: '',
  autoRedirectEnabled: true,
  utmSource: '',
  utmMedium: '',
  utmCampaign: '',
  utmTerm: '',
  utmContent: '',
  type: 'default_tg_redirect',
  zipFile: null,
}

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      if (detail === 'Invalid lander slug' || detail.includes('slug may contain only')) {
        return 'Slug может содержать только латинские буквы, цифры, дефис и подчёркивание.'
      }
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function landerTypeLabel(type: LanderType) {
  return type === 'custom_upload' ? 'Кастомный' : 'Дефолтный'
}

function generateSlug() {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'
  const bytes = new Uint8Array(10)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => alphabet[byte % alphabet.length]).join('')
}

function normalizeSlugInput(value: string) {
  return value.trim().replace(/[^A-Za-z0-9_-]/g, '').slice(0, 100)
}

function isValidLanderSlug(value: string) {
  return /^[A-Za-z0-9_-]{1,100}$/.test(value.trim())
}

function normalizeDomainInput(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .split('/')[0]
    .split(':')[0]
    .replace(/\.$/, '')
}

function buildPixels(form: LanderForm): LanderPixel[] {
  const pixelId = (
    form.trackingMode === 'campaign' ? form.campaignFbPixelId : form.metaPixelId
  ).trim()
  return pixelId ? [{ provider: 'meta', pixel_id: pixelId }] : []
}

function cloneEventMappings(mappings: FacebookEventMapping[]): FacebookEventMapping[] {
  return mappings.map((mapping) => ({
    ...mapping,
    parameters: { ...mapping.parameters },
  }))
}

type FacebookEventMappingsEditorProps = {
  mappings: FacebookEventMapping[]
  sourceEvents: FacebookSourceEvent[]
  onChange: (mappings: FacebookEventMapping[]) => void
}

function FacebookEventMappingsEditor({
  mappings,
  sourceEvents,
  onChange,
}: FacebookEventMappingsEditorProps) {
  const sourceByKey = useMemo(
    () => new Map(sourceEvents.map((source) => [source.key, source])),
    [sourceEvents],
  )

  const patchMapping = (index: number, patch: Partial<FacebookEventMapping>) => {
    onChange(
      mappings.map((mapping, mappingIndex) =>
        mappingIndex === index
          ? {
              ...mapping,
              ...patch,
              parameters: patch.parameters ?? mapping.parameters,
            }
          : mapping,
      ),
    )
  }

  return (
    <div className="divide-y divide-white/10 rounded-lg border border-white/10 bg-zinc-950/40">
      {mappings.map((mapping, index) => {
        const source = sourceByKey.get(mapping.source_event)
        const hasValueParameters =
          mapping.event_name.toLowerCase() === 'purchase' ||
          Boolean(mapping.parameters.value || mapping.parameters.currency)
        return (
          <div
            key={mapping.source_event}
            className={`grid gap-3 px-3 py-3 lg:items-center ${
              hasValueParameters
                ? 'lg:grid-cols-[minmax(170px,0.9fr)_minmax(180px,1fr)_minmax(220px,1.2fr)]'
                : 'lg:grid-cols-[minmax(170px,0.9fr)_minmax(180px,2.2fr)]'
            }`}
          >
            <label className="flex min-w-0 items-center gap-3">
              <input
                type="checkbox"
                checked={mapping.enabled}
                onChange={(event) => patchMapping(index, { enabled: event.target.checked })}
                className="h-5 w-5 shrink-0 accent-emerald-400"
              />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-zinc-100">
                  {source?.label ?? mapping.source_event}
                </span>
                <span className="mt-0.5 block text-xs text-zinc-500">
                  {source?.delivery === 'browser' ? 'Pixel · браузер' : 'CAPI · сервер'}
                  {source?.trigger === 'funnel' ? ' · из CRM-действия' : ' · автоматически'}
                </span>
              </span>
            </label>
            <label className="block min-w-0">
              <span className="mb-1 block text-xs text-zinc-500">Meta event</span>
              <input
                list="facebook-standard-events"
                value={mapping.event_name}
                disabled={!mapping.enabled}
                onChange={(event) => patchMapping(index, { event_name: event.target.value })}
                maxLength={40}
                pattern="[A-Za-z][A-Za-z0-9_]*"
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 disabled:opacity-45 md:text-sm"
              />
            </label>
            {hasValueParameters ? (
              <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_110px]">
                <label className="block min-w-0">
                  <span className="mb-1 block text-xs text-zinc-500">value</span>
                  <input
                    value={mapping.parameters.value ?? ''}
                    disabled={!mapping.enabled}
                    onChange={(event) => patchMapping(index, {
                      parameters: { ...mapping.parameters, value: event.target.value },
                    })}
                    placeholder="{{lead.expected_start_amount}}"
                    className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 disabled:opacity-45 md:text-sm"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-zinc-500">currency</span>
                  <input
                    value={mapping.parameters.currency ?? ''}
                    disabled={!mapping.enabled}
                    onChange={(event) => patchMapping(index, {
                      parameters: { ...mapping.parameters, currency: event.target.value.toUpperCase() },
                    })}
                    placeholder="USD"
                    maxLength={3}
                    className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base uppercase text-zinc-100 outline-none ring-emerald-500 focus:ring-2 disabled:opacity-45 md:text-sm"
                  />
                </label>
              </div>
            ) : null}
          </div>
        )
      })}
      <datalist id="facebook-standard-events">
        <option value="ViewContent" />
        <option value="Lead" />
        <option value="CompleteRegistration" />
        <option value="Subscribe" />
        <option value="Search" />
        <option value="Purchase" />
        <option value="Schedule" />
        <option value="Contact" />
        <option value="AddToWishlist" />
        <option value="SubmitApplication" />
      </datalist>
    </div>
  )
}

function buildMetaEvents(value: string): LanderMetaEvent[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item, index, items) => item.length > 0 && items.indexOf(item) === index)
    .map((name) => ({ name }))
}

function buildUtmDefaults(form: LanderForm): Record<string, string> {
  const values: Array<[string, string]> = [
    ['utm_source', form.utmSource],
    ['utm_medium', form.utmMedium],
    ['utm_campaign', form.utmCampaign],
    ['utm_term', form.utmTerm],
    ['utm_content', form.utmContent],
  ]
  return Object.fromEntries(
    values
      .map(([key, value]) => [key, value.trim()] as const)
      .filter(([, value]) => value.length > 0),
  )
}

export default function LandersSettings({ projectId }: LandersSettingsProps) {
  const [domains, setDomains] = useState<ProjectDomain[]>([])
  const [landers, setLanders] = useState<ProjectLander[]>([])
  const [trackingLinks, setTrackingLinks] = useState<TrackingLinkOption[]>([])
  const [runtimeConfig, setRuntimeConfig] = useState<LanderRuntimeConfig | null>(null)
  const [bots, setBots] = useState<Bot[]>([])
  const [targetSteps, setTargetSteps] = useState<LanderTargetStep[]>([])
  const [isTargetStepsLoading, setIsTargetStepsLoading] = useState(false)
  const [newDomainName, setNewDomainName] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isAddingDomain, setIsAddingDomain] = useState(false)
  const [deletingDomainId, setDeletingDomainId] = useState<string | null>(null)
  const [deletingLanderId, setDeletingLanderId] = useState<string | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isSavingLander, setIsSavingLander] = useState(false)
  const [editingLander, setEditingLander] = useState<ProjectLander | null>(null)
  const [editingMetaPixelId, setEditingMetaPixelId] = useState('')
  const [editingMetaEvents, setEditingMetaEvents] = useState('')
  const [editingCapiToken, setEditingCapiToken] = useState('')
  const [editingProxyUrl, setEditingProxyUrl] = useState('')
  const [editingTestEventCode, setEditingTestEventCode] = useState('')
  const [editingEventMappings, setEditingEventMappings] = useState<FacebookEventMapping[]>([])
  const [clearEditingCapiToken, setClearEditingCapiToken] = useState(false)
  const [clearEditingProxyUrl, setClearEditingProxyUrl] = useState(false)
  const [editingAutoRedirectEnabled, setEditingAutoRedirectEnabled] = useState(true)
  const [isUpdatingLander, setIsUpdatingLander] = useState(false)
  const [banner, setBanner] = useState<Banner | null>(null)
  const [copiedValue, setCopiedValue] = useState('')
  const [form, setForm] = useState<LanderForm>(emptyLanderForm)

  const trackingLinkById = useMemo(
    () => new Map(trackingLinks.map((link) => [link.id, link])),
    [trackingLinks],
  )

  const loadData = useCallback(async () => {
    if (!projectId) {
      setDomains([])
      setLanders([])
      setTrackingLinks([])
      setBots([])
      setRuntimeConfig(null)
      return
    }

    setIsLoading(true)
    setBanner(null)
    try {
      const [domainItems, landerItems, linkItems, botItems, config] = await Promise.all([
        fetchProjectDomains(projectId),
        fetchProjectLanders(projectId),
        fetchActiveTrackingLinks(projectId),
        fetchBots(projectId),
        fetchLanderRuntimeConfig(projectId),
      ])
      setDomains(domainItems)
      setLanders(landerItems)
      setTrackingLinks(linkItems)
      setBots(botItems)
      setRuntimeConfig(config)
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось загрузить лендинги и домены.'),
      })
    } finally {
      setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const resetForm = useCallback(() => {
    setForm({
      ...emptyLanderForm,
      domainId: '',
      trackingLinkId: trackingLinks[0]?.id ?? '',
      campaignBotId: bots[0]?.id ?? '',
      slug: generateSlug(),
      campaignEventMappings: cloneEventMappings(runtimeConfig?.default_event_mappings ?? []),
    })
  }, [bots, domains, runtimeConfig, trackingLinks])

  useEffect(() => {
    if (!isModalOpen || !projectId || form.trackingMode !== 'campaign' || !form.campaignBotId) {
      setTargetSteps([])
      setIsTargetStepsLoading(false)
      return
    }

    let isMounted = true
    setIsTargetStepsLoading(true)
    void fetchLanderTargetSteps(projectId, form.campaignBotId)
      .then((items) => {
        if (!isMounted) {
          return
        }
        setTargetSteps(items)
        setForm((current) =>
          current.campaignTargetStepKey && !items.some((item) => item.key === current.campaignTargetStepKey)
            ? { ...current, campaignTargetStepKey: '' }
            : current,
        )
      })
      .catch(() => {
        if (isMounted) {
          setTargetSteps([])
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsTargetStepsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [form.campaignBotId, form.trackingMode, isModalOpen, projectId])

  const openCreateModal = () => {
    resetForm()
    setBanner(null)
    setIsModalOpen(true)
  }

  const openEditLander = (lander: ProjectLander) => {
    const metaPixel = lander.pixels_json.find((pixel) => pixel.provider === 'meta')
    setEditingLander(lander)
    setEditingMetaPixelId(lander.fb_pixel_id ?? metaPixel?.pixel_id ?? '')
    setEditingMetaEvents((lander.meta_events_json ?? []).map((event) => event.name).join(', '))
    setEditingAutoRedirectEnabled(lander.auto_redirect_enabled)
    setEditingCapiToken('')
    setEditingProxyUrl('')
    setEditingTestEventCode(lander.fb_test_event_code ?? '')
    setEditingEventMappings(cloneEventMappings(
      lander.fb_event_mappings_json.length > 0
        ? lander.fb_event_mappings_json
        : runtimeConfig?.default_event_mappings ?? [],
    ))
    setClearEditingCapiToken(false)
    setClearEditingProxyUrl(false)
    setBanner(null)
  }

  const handleUpdateLander = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || !editingLander || isUpdatingLander) {
      return
    }
    setIsUpdatingLander(true)
    setBanner(null)
    try {
      await updateProjectLander(projectId, editingLander.id, {
        pixels: editingMetaPixelId.trim()
          ? [{ provider: 'meta', pixel_id: editingMetaPixelId.trim() }]
          : [],
        meta_events: buildMetaEvents(editingMetaEvents),
        auto_redirect_enabled: editingAutoRedirectEnabled,
        facebook_campaign: {
          enabled: true,
          fb_pixel_id: editingMetaPixelId.trim() || null,
          ...(editingCapiToken.trim() ? { fb_capi_token: editingCapiToken.trim() } : {}),
          clear_fb_capi_token: clearEditingCapiToken,
          ...(editingProxyUrl.trim() ? { fb_proxy_url: editingProxyUrl.trim() } : {}),
          clear_fb_proxy_url: clearEditingProxyUrl,
          fb_test_event_code: editingTestEventCode.trim() || null,
          fb_event_mappings: editingEventMappings,
        },
      })
      setEditingLander(null)
      await loadData()
      setBanner({ tone: 'success', message: 'Facebook-кампания и переход сохранены.' })
    } catch (err) {
      setBanner({ tone: 'error', message: getErrorMessage(err, 'Не удалось обновить лендинг.') })
    } finally {
      setIsUpdatingLander(false)
    }
  }

  const handleCopy = async (value: string) => {
    await navigator.clipboard.writeText(value)
    setCopiedValue(value)
    window.setTimeout(() => setCopiedValue(''), 1600)
  }

  const handleAddDomain = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isAddingDomain) {
      return
    }
    const domainName = normalizeDomainInput(newDomainName)
    if (!domainName) {
      setBanner({ tone: 'error', message: 'Укажите доменное имя.' })
      return
    }

    setIsAddingDomain(true)
    setBanner(null)
    try {
      await createProjectDomain(projectId, { domain_name: domainName })
      setNewDomainName('')
      await loadData()
      setBanner({ tone: 'success', message: 'Домен припаркован.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось припарковать домен.'),
      })
    } finally {
      setIsAddingDomain(false)
    }
  }

  const handleDeleteDomain = async (domain: ProjectDomain) => {
    if (!projectId || deletingDomainId) {
      return
    }
    if (!window.confirm(`Разлинковать домен ${domain.domain_name}?`)) {
      return
    }

    setDeletingDomainId(domain.id)
    setBanner(null)
    try {
      await deleteProjectDomain(projectId, domain.id)
      await loadData()
      setBanner({ tone: 'success', message: 'Домен удалён.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось удалить домен.'),
      })
    } finally {
      setDeletingDomainId(null)
    }
  }

  const handleDeleteLander = async (lander: ProjectLander) => {
    if (!projectId || deletingLanderId) {
      return
    }
    if (!window.confirm(`Удалить лендинг "${lander.name}"?`)) {
      return
    }

    setDeletingLanderId(lander.id)
    setBanner(null)
    try {
      await deleteProjectLander(projectId, lander.id)
      await loadData()
      setBanner({ tone: 'success', message: 'Лендинг удалён.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось удалить лендинг.'),
      })
    } finally {
      setDeletingLanderId(null)
    }
  }

  const handleSaveLander = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isSavingLander) {
      return
    }
    if (!form.slug.trim()) {
      setBanner({ tone: 'error', message: 'Заполните slug.' })
      return
    }
    if (form.trackingMode === 'existing' && !form.trackingLinkId) {
      setBanner({ tone: 'error', message: 'Выберите существующую tracking link.' })
      return
    }
    if (form.trackingMode === 'campaign' && !form.campaignBotId) {
      setBanner({ tone: 'error', message: 'Выберите бота для кампании.' })
      return
    }
    const slug = normalizeSlugInput(form.slug)
    if (!isValidLanderSlug(slug)) {
      setBanner({
        tone: 'error',
        message: 'Slug может содержать только латинские буквы, цифры, дефис и подчёркивание.',
      })
      return
    }
    if (form.type === 'custom_upload' && !form.zipFile) {
      setBanner({ tone: 'error', message: 'Выберите ZIP-архив для кастомного лендинга.' })
      return
    }

    setIsSavingLander(true)
    setBanner(null)
    try {
      const created = await createProjectLander(projectId, {
        domain_id: form.domainId || null,
        name: form.name.trim() || slug,
        type: form.type,
        slug,
        tracking_link_id: form.trackingMode === 'existing' ? form.trackingLinkId : null,
        campaign: form.trackingMode === 'campaign'
          ? {
              bot_id: form.campaignBotId,
              title: form.campaignTitle.trim() || form.name.trim() || `Landing ${slug}`,
              code: form.campaignCode.trim() || null,
              buyer_name: form.campaignBuyerName.trim() || null,
              ad_type: form.campaignAdType.trim() || null,
              payment_type: form.campaignPaymentType.trim() || null,
              fb_pixel_id: form.campaignFbPixelId.trim() || form.metaPixelId.trim() || null,
              fb_capi_token: form.campaignFbCapiToken.trim() || null,
              fb_proxy_url: form.campaignFbProxyUrl.trim() || null,
              fb_test_event_code: form.campaignFbTestEventCode.trim() || null,
              fb_event_mappings: form.campaignEventMappings,
              target_funnel_step_key: form.campaignTargetStepKey || null,
            }
          : null,
        pixels: buildPixels(form),
        meta_events: buildMetaEvents(form.metaEvents),
        utm_defaults: buildUtmDefaults(form),
        auto_redirect_enabled: form.autoRedirectEnabled,
      })
      if (form.type === 'custom_upload' && form.zipFile) {
        await uploadProjectLanderZip(projectId, created.id, form.zipFile)
      }
      setIsModalOpen(false)
      setForm(emptyLanderForm)
      await loadData()
      setBanner({
        tone: 'success',
        message: form.trackingMode === 'campaign'
          ? 'Лендинг и отдельная campaign tracking link созданы.'
          : 'Лендинг создан.',
      })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось создать лендинг.'),
      })
    } finally {
      setIsSavingLander(false)
    }
  }

  if (!projectId) {
    return (
      <div className="rounded-lg border border-white/5 bg-white/[0.02] p-5 text-sm text-zinc-500">
        Выберите проект для управления лендингами и доменами.
      </div>
    )
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-zinc-100">Лендинги и Домены</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Парковка доменов, прокладки и сквозная UTM-атрибуция в Telegram.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateModal}
          disabled={bots.length === 0}
          className="inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={16} />
          Создать лендинг
        </button>
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

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.9fr)]">
        <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-zinc-100">Парковка Доменов</h3>
              <p className="mt-1 text-sm text-zinc-500">Домены, на которых будут открываться прокладки.</p>
            </div>
            <button
              type="button"
              onClick={() => void loadData()}
              disabled={isLoading}
              title="Обновить"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:opacity-50"
            >
              <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
            </button>
          </div>

          <form className="mt-4 flex flex-col gap-3 sm:flex-row" onSubmit={handleAddDomain}>
            <label className="min-w-0 flex-1">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Доменное имя
              </span>
              <input
                value={newDomainName}
                onChange={(event) => setNewDomainName(event.target.value)}
                placeholder="go.zona-acceso.li"
                maxLength={255}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
            </label>
            <button
              type="submit"
              disabled={isAddingDomain || !newDomainName.trim()}
              className="mt-auto inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isAddingDomain ? <LoaderCircle size={16} className="animate-spin" /> : <Globe2 size={16} />}
              Припарковать
            </button>
          </form>

          <div className="mt-4 overflow-x-auto rounded-lg border border-white/5">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-3">Домен</th>
                  <th className="px-4 py-3">Статус</th>
                  <th className="w-[96px] px-4 py-3 text-right">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {domains.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-8 text-center text-sm text-zinc-500">
                      Домены пока не припаркованы.
                    </td>
                  </tr>
                ) : (
                  domains.map((domain) => (
                    <tr key={domain.id} className="bg-white/[0.01]">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 font-mono text-zinc-100">
                          <Globe2 size={16} className="text-zinc-500" />
                          {domain.domain_name}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-xs font-semibold text-emerald-200">
                          Активен
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end">
                          <button
                            type="button"
                            title="Разлинковать домен"
                            onClick={() => void handleDeleteDomain(domain)}
                            disabled={deletingDomainId === domain.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-red-500/50 hover:text-red-300 disabled:opacity-50"
                          >
                            {deletingDomainId === domain.id ? (
                              <LoaderCircle size={15} className="animate-spin" />
                            ) : (
                              <Trash2 size={15} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 p-4">
          <div className="flex items-start gap-3">
            <Clipboard size={20} className="mt-0.5 shrink-0 text-cyan-200" />
            <div>
              <h3 className="text-sm font-semibold text-cyan-100">DNS-настройка</h3>
              <p className="mt-2 text-sm leading-6 text-cyan-100/75">
                CRM сохраняет домен и лендинг, но DNS меняется у регистратора. Направьте
                CNAME поддомена на <span className="font-mono text-cyan-50">{runtimeConfig?.technical_domain ?? 'технический домен'}</span>.
                Техдомен можно выбрать сразу, без парковки отдельного домена. Динамический HTML
                не кэшируется, поэтому UTM, fbp/fbc и start-key остаются индивидуальными.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-zinc-100">Конструктор Прокладок</h3>
            <p className="mt-1 text-sm text-zinc-500">
              Кампания, Telegram-переход, UTM-атрибуция и пиксели в одном объекте.
            </p>
          </div>
          <button
            type="button"
            onClick={openCreateModal}
            disabled={bots.length === 0}
            className="inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-100 transition hover:border-emerald-500/50 hover:text-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={16} />
            Создать лендинг
          </button>
        </div>

        <div className="mt-4 overflow-x-auto rounded-lg border border-white/5">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Итоговая ссылка</th>
                <th className="px-4 py-3">Кампания и атрибуция</th>
                <th className="w-[96px] px-4 py-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {landers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-sm text-zinc-500">
                    Лендинги пока не созданы.
                  </td>
                </tr>
              ) : (
                landers.map((lander) => {
                  const link = lander.tracking_link_id
                    ? trackingLinkById.get(lander.tracking_link_id)
                    : null
                  const url = lander.public_url

                  return (
                    <tr key={lander.id} className="bg-white/[0.01]">
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-100">{lander.name}</div>
                        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
                          <span>{landerTypeLabel(lander.type)}</span>
                          <span className="font-mono">/{lander.slug}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {url ? (
                          <div className="flex min-w-0 items-center gap-2">
                            <a
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="min-w-0 truncate font-mono text-sm text-cyan-200 hover:text-cyan-100"
                            >
                              {url}
                            </a>
                            <ExternalLink size={14} className="shrink-0 text-zinc-500" />
                            <button
                              type="button"
                              title="Скопировать ссылку"
                              onClick={() => void handleCopy(url)}
                              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-cyan-500/50 hover:text-cyan-200"
                            >
                              <Copy size={14} />
                            </button>
                            {copiedValue === url ? (
                              <span className="shrink-0 text-xs text-emerald-300">Скопировано</span>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-zinc-500">URL недоступен</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="space-y-2">
                          {link ? (
                            <div>
                              <div className="text-zinc-100">{link.title}</div>
                              <div className="font-mono text-xs text-zinc-500">{link.code}</div>
                            </div>
                          ) : (
                            <span className="text-zinc-500">Не найдена</span>
                          )}
                          <div className="flex flex-wrap gap-1.5 text-xs">
                            {lander.facebook_campaign_enabled ? (
                              <span className="rounded-md border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 text-cyan-100">
                                Facebook campaign
                              </span>
                            ) : null}
                            {lander.has_fb_capi_token ? (
                              <span className="rounded-md border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-emerald-100">
                                CAPI готов
                              </span>
                            ) : null}
                            {lander.has_fb_proxy ? (
                              <span className="rounded-md border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-sky-100">
                                Proxy
                              </span>
                            ) : null}
                            {lander.pixels_json.length > 0 ? (
                              lander.pixels_json.map((pixel) => (
                                <span
                                  key={`${pixel.provider}-${pixel.pixel_id}`}
                                  className="rounded-md border border-violet-400/20 bg-violet-400/10 px-2 py-0.5 text-violet-100"
                                >
                                  {pixel.provider}: {pixel.pixel_id}
                                </span>
                              ))
                            ) : (
                              <span className="text-zinc-600">Без пикселей</span>
                            )}
                            {(lander.meta_events_json ?? []).map((event) => (
                              <span
                                key={event.name}
                                className="rounded-md border border-emerald-400/20 bg-emerald-400/10 px-2 py-0.5 text-emerald-100"
                              >
                                event: {event.name}
                              </span>
                            ))}
                            {!lander.auto_redirect_enabled ? (
                              <span className="rounded-md border border-amber-400/20 bg-amber-400/10 px-2 py-0.5 text-amber-100">
                                Без авторедиректа
                              </span>
                            ) : null}
                            {Object.keys(lander.utm_defaults_json).length > 0 ? (
                              <span className="rounded-md border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 text-cyan-100">
                                UTM defaults
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            title="Настройки Facebook-кампании"
                            onClick={() => openEditLander(lander)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-emerald-500/50 hover:text-emerald-200"
                          >
                            <Pencil size={15} />
                          </button>
                          <button
                            type="button"
                            title="Удалить лендинг"
                            onClick={() => void handleDeleteLander(lander)}
                            disabled={deletingLanderId === lander.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-red-500/50 hover:text-red-300 disabled:opacity-50"
                          >
                            {deletingLanderId === lander.id ? (
                              <LoaderCircle size={15} className="animate-spin" />
                            ) : (
                              <Trash2 size={15} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {isModalOpen ? (
        <Modal
          title="Создать лендинг"
          description="По умолчанию создается отдельная campaign tracking link. Существующую ссылку можно выбрать только для осознанного переиспользования."
          onClose={() => {
            if (!isSavingLander) {
              setIsModalOpen(false)
            }
          }}
          maxWidthClassName="max-w-4xl"
        >
          <form className="space-y-4" onSubmit={handleSaveLander}>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">Название</span>
              <input
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="FB ES Telegram prelander"
                maxLength={255}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Домен</span>
                <select
                  value={form.domainId}
                  onChange={(event) => setForm((current) => ({ ...current, domainId: event.target.value }))}
                  className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                >
                  <option value="">
                    Техдомен · {runtimeConfig?.technical_domain ?? 'не настроен'}
                  </option>
                  {domains.map((domain) => (
                    <option key={domain.id} value={domain.id}>
                      {domain.domain_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Тип прокладки</span>
                <select
                  value={form.type}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      type: event.target.value as LanderType,
                      zipFile: event.target.value === 'custom_upload' ? current.zipFile : null,
                    }))
                  }
                  className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                >
                  <option value="default_tg_redirect">Дефолтный ТГ-перегон</option>
                  <option value="custom_upload">Кастомный HTML (ZIP архив)</option>
                </select>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">
                  Slug (Путь ссылки)
                </span>
                <input
                  value={form.slug}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      slug: normalizeSlugInput(event.target.value),
                    }))
                  }
                  placeholder="0ZZVaOfQad"
                  required
                  maxLength={100}
                  className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
                <span className="mt-1 block text-xs text-zinc-500">
                  Только латиница, цифры, дефис и подчёркивание.
                </span>
              </label>
              <button
                type="button"
                onClick={() => setForm((current) => ({ ...current, slug: generateSlug() }))}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-200 transition hover:border-emerald-500/50 hover:text-emerald-200"
              >
                <RefreshCw size={15} />
                Сгенерировать
              </button>
            </div>

            <fieldset className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <legend className="px-1 text-sm font-semibold text-zinc-100">Tracking-кампания</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setForm((current) => ({ ...current, trackingMode: 'campaign', trackingLinkId: '' }))}
                  className={`min-h-11 rounded-lg border px-3 text-left text-sm transition ${
                    form.trackingMode === 'campaign'
                      ? 'border-emerald-400/50 bg-emerald-500/10 text-emerald-100'
                      : 'border-white/10 text-zinc-400 hover:border-white/20'
                  }`}
                >
                  <span className="block font-semibold">Новая кампания</span>
                  <span className="mt-0.5 block text-xs opacity-75">Создать отдельную ссылку для этого лендинга</span>
                </button>
                <button
                  type="button"
                  onClick={() => setForm((current) => ({ ...current, trackingMode: 'existing' }))}
                  className={`min-h-11 rounded-lg border px-3 text-left text-sm transition ${
                    form.trackingMode === 'existing'
                      ? 'border-cyan-400/50 bg-cyan-500/10 text-cyan-100'
                      : 'border-white/10 text-zinc-400 hover:border-white/20'
                  }`}
                >
                  <span className="block font-semibold">Использовать существующую</span>
                  <span className="mt-0.5 block text-xs opacity-75">Один источник для нескольких лендингов</span>
                </button>
              </div>

              {form.trackingMode === 'campaign' ? (
                <div className="mt-4 space-y-3">
                  <div className="grid gap-3 md:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-sm font-medium text-zinc-300">Бот кампании</span>
                      <select
                        value={form.campaignBotId}
                        onChange={(event) =>
                          setForm((current) => ({
                            ...current,
                            campaignBotId: event.target.value,
                            campaignTargetStepKey: '',
                          }))
                        }
                        required
                        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm"
                      >
                        <option value="">Выберите бота</option>
                        {bots.map((bot) => (
                          <option key={bot.id} value={bot.id}>{bot.name}</option>
                        ))}
                      </select>
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-sm font-medium text-zinc-300">Название кампании</span>
                      <input
                        value={form.campaignTitle}
                        onChange={(event) => setForm((current) => ({ ...current, campaignTitle: event.target.value }))}
                        maxLength={255}
                        placeholder="Например: Meta ES June"
                        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                      />
                    </label>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Код</span>
                      <input
                        value={form.campaignCode}
                        onChange={(event) => setForm((current) => ({ ...current, campaignCode: event.target.value }))}
                        maxLength={64}
                        placeholder="auto"
                        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Баер</span>
                      <input
                        value={form.campaignBuyerName}
                        onChange={(event) => setForm((current) => ({ ...current, campaignBuyerName: event.target.value }))}
                        maxLength={255}
                        placeholder="Имя"
                        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Тип рекламы</span>
                      <input
                        value={form.campaignAdType}
                        onChange={(event) => setForm((current) => ({ ...current, campaignAdType: event.target.value }))}
                        maxLength={100}
                        placeholder="meta"
                        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                      />
                    </label>
                  </div>
                  <div className="border-t border-white/10 pt-4">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-cyan-100">
                      <ShieldCheck size={17} className="shrink-0 text-cyan-300" />
                      Facebook Pixel и Conversion API
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Pixel / Dataset ID</span>
                        <input
                          value={form.campaignFbPixelId}
                          onChange={(event) => setForm((current) => ({ ...current, campaignFbPixelId: event.target.value }))}
                          inputMode="numeric"
                          maxLength={50}
                          placeholder="123456789012345"
                          className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                        />
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Pixel access token</span>
                        <input
                          type="password"
                          value={form.campaignFbCapiToken}
                          onChange={(event) => setForm((current) => ({ ...current, campaignFbCapiToken: event.target.value }))}
                          placeholder="Access token"
                          autoComplete="off"
                          className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                        />
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">CAPI proxy · необязательно</span>
                        <input
                          type="password"
                          value={form.campaignFbProxyUrl}
                          onChange={(event) => setForm((current) => ({ ...current, campaignFbProxyUrl: event.target.value }))}
                          placeholder="http://user:pass@proxy:8080"
                          autoComplete="off"
                          className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                        />
                      </label>
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Test event code · необязательно</span>
                        <input
                          value={form.campaignFbTestEventCode}
                          onChange={(event) => setForm((current) => ({ ...current, campaignFbTestEventCode: event.target.value }))}
                          placeholder="TEST12345"
                          maxLength={100}
                          className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                        />
                      </label>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-zinc-500">
                      Токен и proxy никогда не возвращаются из API. Test event code отправляет CAPI-события в режим проверки Meta Events Manager.
                    </p>
                  </div>
                  <div className="border-t border-white/10 pt-4">
                    <div className="mb-1 text-sm font-semibold text-zinc-100">Карта событий</div>
                    <p className="mb-3 text-xs leading-5 text-zinc-500">
                      Просмотр и переход фиксируются Pixel в лендинге. Старт бота и контакт отправляются CAPI автоматически. Остальные источники вызываются CRM-действием воронки.
                    </p>
                    <FacebookEventMappingsEditor
                      mappings={form.campaignEventMappings}
                      sourceEvents={runtimeConfig?.source_events ?? []}
                      onChange={(campaignEventMappings) => setForm((current) => ({ ...current, campaignEventMappings }))}
                    />
                  </div>
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-zinc-300">Точка входа в активную воронку</span>
                    <select
                      value={form.campaignTargetStepKey}
                      onChange={(event) => setForm((current) => ({ ...current, campaignTargetStepKey: event.target.value }))}
                      disabled={!form.campaignBotId || isTargetStepsLoading}
                      className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50 md:text-sm"
                    >
                      <option value="">Начать с обычного триггера</option>
                      {targetSteps.map((step) => (
                        <option key={step.key} value={step.key}>
                          {step.title} · {step.block_type}
                        </option>
                      ))}
                    </select>
                    <span className="mt-1 block text-xs text-zinc-500">
                      {isTargetStepsLoading
                        ? 'Загружаем шаги опубликованной воронки...'
                        : 'Шаги доступны только у активной опубликованной воронки выбранного бота.'}
                    </span>
                  </label>
                </div>
              ) : (
                <label className="mt-4 block">
                  <span className="mb-1 block text-sm font-medium text-zinc-300">Существующая tracking link</span>
                  <select
                    value={form.trackingLinkId}
                    onChange={(event) => setForm((current) => ({ ...current, trackingLinkId: event.target.value }))}
                    required
                    className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm"
                  >
                    <option value="">Выберите tracking link</option>
                    {trackingLinks.map((link) => (
                      <option key={link.id} value={link.id}>{link.title} · {link.code}</option>
                    ))}
                  </select>
                </label>
              )}
            </fieldset>

            <fieldset className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <legend className="px-1 text-sm font-semibold text-zinc-100">Переход и UTM</legend>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                UTM из рекламного URL сохраняются у лида автоматически; значения ниже заполняют только отсутствующие параметры.
              </p>
              {form.trackingMode === 'existing' ? (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Legacy Meta Pixel ID</span>
                    <input value={form.metaPixelId} onChange={(event) => setForm((current) => ({ ...current, metaPixelId: event.target.value }))} placeholder="1234567890" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Legacy события на переходе</span>
                    <input value={form.metaEvents} onChange={(event) => setForm((current) => ({ ...current, metaEvents: event.target.value }))} placeholder="CompleteRegistration, QuizCompleted" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
                  </label>
                </div>
              ) : null}
              <label className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-zinc-950/50 px-3 py-2.5 text-sm text-zinc-200">
                <span>
                  <span className="block font-medium text-zinc-100">Автопереход в Telegram</span>
                  <span className="mt-0.5 block text-xs text-zinc-500">Работает у дефолтного лендинга после короткой паузы.</span>
                </span>
                <input type="checkbox" checked={form.autoRedirectEnabled} disabled={form.type === 'custom_upload'} onChange={(event) => setForm((current) => ({ ...current, autoRedirectEnabled: event.target.checked }))} className="h-5 w-5 shrink-0 accent-emerald-400 disabled:opacity-40" />
              </label>
              <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                <label className="block"><span className="mb-1 block text-xs text-zinc-500">utm_source</span><input value={form.utmSource} onChange={(event) => setForm((current) => ({ ...current, utmSource: event.target.value }))} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 md:text-sm" /></label>
                <label className="block"><span className="mb-1 block text-xs text-zinc-500">utm_medium</span><input value={form.utmMedium} onChange={(event) => setForm((current) => ({ ...current, utmMedium: event.target.value }))} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 md:text-sm" /></label>
                <label className="block"><span className="mb-1 block text-xs text-zinc-500">utm_campaign</span><input value={form.utmCampaign} onChange={(event) => setForm((current) => ({ ...current, utmCampaign: event.target.value }))} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 md:text-sm" /></label>
                <label className="block"><span className="mb-1 block text-xs text-zinc-500">utm_term</span><input value={form.utmTerm} onChange={(event) => setForm((current) => ({ ...current, utmTerm: event.target.value }))} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 md:text-sm" /></label>
                <label className="block"><span className="mb-1 block text-xs text-zinc-500">utm_content</span><input value={form.utmContent} onChange={(event) => setForm((current) => ({ ...current, utmContent: event.target.value }))} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 focus:ring-2 md:text-sm" /></label>
              </div>
            </fieldset>

            {form.type === 'custom_upload' ? (
              <label className="block rounded-lg border border-dashed border-white/10 bg-white/[0.02] p-4">
                <span className="flex items-center gap-2 text-sm font-medium text-zinc-300">
                  <Upload size={16} />
                  ZIP-архив
                </span>
                <input
                  type="file"
                  accept=".zip,application/zip,application/x-zip-compressed"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      zipFile: event.target.files?.[0] ?? null,
                    }))
                  }
                  className="mt-3 block w-full text-sm text-zinc-400 file:mr-4 file:rounded-lg file:border-0 file:bg-emerald-500 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-zinc-950 hover:file:bg-emerald-400"
                />
                <span className="mt-2 block text-xs text-zinc-500">
                  В корне архива должны быть index.html и кнопка Telegram: <code>&lt;a data-crm-telegram-link href=&quot;#&quot;&gt;...&lt;/a&gt;</code>.
                  Для события из карты добавьте <code>data-crm-fb-source=&quot;registration&quot;</code>.
                  Старый <code>data-crm-meta-event</code> также поддерживается.
                </span>
                {form.zipFile ? (
                  <span className="mt-2 block text-sm text-emerald-200">
                    Выбран файл: {form.zipFile.name}
                  </span>
                ) : null}
              </label>
            ) : null}

            <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                disabled={isSavingLander}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isSavingLander}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSavingLander ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {editingLander ? (
        <Modal
          title="Facebook-кампания"
          description={`Pixel, CAPI и карта событий для «${editingLander.name}».`}
          maxWidthClassName="max-w-4xl"
          onClose={() => {
            if (!isUpdatingLander) {
              setEditingLander(null)
            }
          }}
        >
          <form className="space-y-4" onSubmit={(event) => void handleUpdateLander(event)}>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Pixel / Dataset ID</span>
                <input value={editingMetaPixelId} onChange={(event) => setEditingMetaPixelId(event.target.value)} inputMode="numeric" placeholder="1234567890" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Новый CAPI token</span>
                <input type="password" value={editingCapiToken} disabled={clearEditingCapiToken} onChange={(event) => setEditingCapiToken(event.target.value)} placeholder={editingLander.has_fb_capi_token ? 'Уже задан · оставить пустым' : 'Access token'} autoComplete="off" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 disabled:opacity-45 md:text-sm" />
                {editingLander.has_fb_capi_token ? (
                  <label className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                    <input type="checkbox" checked={clearEditingCapiToken} onChange={(event) => setClearEditingCapiToken(event.target.checked)} className="h-4 w-4 accent-red-400" />
                    Удалить сохранённый token
                  </label>
                ) : null}
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Новый CAPI proxy</span>
                <input type="password" value={editingProxyUrl} disabled={clearEditingProxyUrl} onChange={(event) => setEditingProxyUrl(event.target.value)} placeholder={editingLander.has_fb_proxy ? 'Уже задан · оставить пустым' : 'http://user:pass@proxy:8080'} autoComplete="off" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 disabled:opacity-45 md:text-sm" />
                {editingLander.has_fb_proxy ? (
                  <label className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                    <input type="checkbox" checked={clearEditingProxyUrl} onChange={(event) => setClearEditingProxyUrl(event.target.checked)} className="h-4 w-4 accent-red-400" />
                    Удалить сохранённый proxy
                  </label>
                ) : null}
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Test event code</span>
                <input value={editingTestEventCode} onChange={(event) => setEditingTestEventCode(event.target.value)} placeholder="TEST12345" maxLength={100} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
              </label>
            </div>
            <div>
              <div className="mb-1.5 text-sm font-medium text-zinc-200">Карта событий</div>
              <FacebookEventMappingsEditor
                mappings={editingEventMappings}
                sourceEvents={runtimeConfig?.source_events ?? []}
                onChange={setEditingEventMappings}
              />
            </div>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-zinc-200">Legacy события лендинга</span>
              <input value={editingMetaEvents} onChange={(event) => setEditingMetaEvents(event.target.value)} placeholder="QuizCompleted" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
              <span className="mt-1.5 block text-xs leading-5 text-zinc-500">Только для старых ZIP с data-crm-meta-event. Новые лендинги используют карту выше.</span>
            </label>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-zinc-950/50 px-3 py-2.5 text-sm text-zinc-200">
              <span>
                <span className="block font-medium text-zinc-100">Автопереход в Telegram</span>
                <span className="mt-0.5 block text-xs text-zinc-500">Для custom ZIP настройте переход в коде лендинга.</span>
              </span>
              <input type="checkbox" checked={editingAutoRedirectEnabled} disabled={editingLander.type === 'custom_upload'} onChange={(event) => setEditingAutoRedirectEnabled(event.target.checked)} className="h-5 w-5 shrink-0 accent-emerald-400 disabled:opacity-40" />
            </label>
            <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setEditingLander(null)} disabled={isUpdatingLander} className="inline-flex h-10 items-center justify-center rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50">Отмена</button>
              <button type="submit" disabled={isUpdatingLander} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:opacity-50">
                {isUpdatingLander ? <LoaderCircle size={16} className="animate-spin" /> : <Pencil size={16} />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  )
}

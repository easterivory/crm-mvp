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
  Radio,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
  Upload,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { fetchBotAvatar, fetchBots, type Bot } from '../../bots'
import { Modal } from '../../../shared/ui'
import { useAuthStore } from '../../../store/authStore'
import {
  createProjectDomain,
  createProjectLander,
  createTelegramChannel,
  deleteProjectDomain,
  deleteProjectLander,
  deleteTelegramChannel,
  fetchActiveTrackingLinks,
  fetchLanderTargetSteps,
  fetchLanderRuntimeConfig,
  fetchProjectDomains,
  fetchProjectLanders,
  fetchTelegramChannelAvatar,
  fetchTelegramChannels,
  updateProjectLander,
  uploadProjectLanderZip,
  verifyTelegramChannel,
} from '../api'
import type {
  LanderType,
  LanderPixel,
  LanderMetaEvent,
  FacebookEventMapping,
  FacebookEventTrigger,
  FacebookEventTriggerType,
  FacebookLeadStatusTrigger,
  FacebookSourceEvent,
  FacebookTagTrigger,
  LanderRuntimeConfig,
  LanderTargetStep,
  ProjectDomain,
  ProjectLander,
  TrackingLinkOption,
  TelegramChannel,
} from '../types'

type LandersSettingsProps = {
  projectId: string | null
  campaignOnly?: boolean
  canManageDomains?: boolean
}

type Banner = {
  tone: 'success' | 'error'
  message: string
}

type LanderForm = {
  name: string
  domainId: string
  slug: string
  description: string
  buttonText: string
  badgeText: string
  trackingMode: 'campaign' | 'existing'
  trackingLinkId: string
  campaignDestinationType: 'bot' | 'channel'
  campaignBotId: string
  campaignChannelId: string
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

type LanderEditForm = {
  name: string
  domainId: string
  slug: string
  description: string
  buttonText: string
  badgeText: string
  type: LanderType
  destinationType: 'bot' | 'channel'
  botId: string
  channelId: string
  campaignTitle: string
  campaignCode: string
  buyerName: string
  adType: string
  paymentType: string
  baseConversionRate: string
  minSampleSize: string
  targetStepKey: string
  fbCampaignEnabled: boolean
  metaPixelId: string
  metaEvents: string
  capiToken: string
  proxyUrl: string
  testEventCode: string
  eventMappings: FacebookEventMapping[]
  clearCapiToken: boolean
  clearProxyUrl: boolean
  autoRedirectEnabled: boolean
  utmSource: string
  utmMedium: string
  utmCampaign: string
  utmTerm: string
  utmContent: string
  zipFile: File | null
}

const emptyLanderForm: LanderForm = {
  name: '',
  domainId: '',
  slug: '',
  description: '',
  buttonText: 'Open in Telegram',
  badgeText: '',
  trackingMode: 'campaign',
  trackingLinkId: '',
  campaignDestinationType: 'bot',
  campaignBotId: '',
  campaignChannelId: '',
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
  utmSource: 'facebook',
  utmMedium: 'paid_social',
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
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item) => {
        if (!item || typeof item !== 'object') {
          return []
        }
        const message = 'msg' in item ? String(item.msg ?? '').trim() : ''
        const location = 'loc' in item && Array.isArray(item.loc)
          ? item.loc.filter((part: unknown) => part !== 'body').join('.')
          : ''
        return message ? [`${location ? `${location}: ` : ''}${message}`] : []
      })
      if (messages.length > 0) {
        return messages.join('; ')
      }
    }
    const responseBody = err.response?.data
    if (typeof responseBody === 'string' && responseBody.trim()) {
      const normalized = responseBody.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
      if (normalized && normalized !== 'Internal Server Error') {
        return normalized.slice(0, 500)
      }
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
    if (err.response?.status) {
      return `${fallback} HTTP ${err.response.status}. Ошибка записана в серверный лог.`
    }
    if (err.message) {
      return `${fallback} ${err.message}`
    }
  }
  return fallback
}

function landerTypeLabel(type: LanderType) {
  return type === 'custom_upload' ? 'Кастомный' : 'Дефолтный'
}

type TelegramLanderAppearanceEditorProps = {
  projectId: string
  bot?: Bot
  channel?: TelegramChannel
  description: string
  buttonText: string
  badgeText: string
  onDescriptionChange: (value: string) => void
  onButtonTextChange: (value: string) => void
  onBadgeTextChange: (value: string) => void
}

function botDisplayName(bot?: Bot) {
  return bot?.telegram_first_name?.trim() || bot?.name.trim() || 'Telegram bot'
}

function botFallbackDescription(bot?: Bot) {
  return bot?.telegram_description?.trim()
    || bot?.telegram_about?.trim()
    || 'Open this bot in Telegram to continue.'
}

function TelegramLanderAppearanceEditor({
  projectId,
  bot,
  channel,
  description,
  buttonText,
  badgeText,
  onDescriptionChange,
  onButtonTextChange,
  onBadgeTextChange,
}: TelegramLanderAppearanceEditorProps) {
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    let objectUrl: string | null = null
    setAvatarUrl(null)
    if (!bot && !channel) {
      return () => undefined
    }
    const avatarRequest = channel
      ? fetchTelegramChannelAvatar(projectId, channel.id)
      : fetchBotAvatar((bot as Bot).id, projectId)
    void avatarRequest
      .then((blob) => {
        if (!isMounted) {
          return
        }
        objectUrl = URL.createObjectURL(blob)
        setAvatarUrl(objectUrl)
      })
      .catch(() => {
        if (isMounted) {
          setAvatarUrl(null)
        }
      })
    return () => {
      isMounted = false
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [bot, channel, projectId])

  const title = channel?.title || botDisplayName(bot)
  const previewDescription = description.trim()
    || channel?.description?.trim()
    || (channel ? 'Подпишитесь на канал, чтобы получать новые публикации.' : botFallbackDescription(bot))
  const previewButtonText = buttonText.trim()
    || (channel ? 'Подписаться на канал' : 'Open in Telegram')
  const previewBadgeText = badgeText.trim()
  const username = channel ? channel.username : bot?.bot_username
  const initial = Array.from(title).find((character) => /[\p{L}\p{N}]/u.test(character))?.toUpperCase() || 'T'

  return (
    <fieldset className="rounded-lg border border-white/10 bg-white/[0.02] p-3">
      <legend className="px-1 text-sm font-semibold text-zinc-100">
        Оформление Telegram-лендинга
      </legend>
      <div className="mt-2 grid gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(220px,0.6fr)]">
        <label className="block md:row-span-2">
          <span className="mb-1.5 block text-sm font-medium text-zinc-200">Описание</span>
          <textarea
            value={description}
            onChange={(event) => onDescriptionChange(event.target.value)}
            maxLength={1000}
            rows={4}
            placeholder={botFallbackDescription(bot)}
            className="min-h-28 w-full resize-y rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base leading-6 text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
          />
        </label>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-zinc-200">Подпись под названием</span>
            <input
              value={badgeText}
              onChange={(event) => onBadgeTextChange(event.target.value)}
              maxLength={80}
              placeholder={channel ? 'Telegram-канал' : 'Без подписи'}
              className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-zinc-200">Текст кнопки</span>
            <input
              value={buttonText}
              onChange={(event) => onButtonTextChange(event.target.value)}
              maxLength={80}
              placeholder="Open in Telegram"
              className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
            />
          </label>
        </div>
      </div>

      <div className="mt-4 overflow-hidden rounded-lg border border-white/10 bg-[#dcebe4]">
        <div className="flex h-16 items-center gap-3 bg-white px-4 text-zinc-950">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#2aabee] text-white">
            <Send size={21} aria-hidden="true" />
          </span>
          <span className="text-xl font-bold">Telegram</span>
        </div>
        <div className="p-4 sm:p-7">
          <div className="mx-auto max-w-sm rounded-lg border border-black/5 bg-white px-5 py-7 text-center shadow-lg shadow-emerald-950/10">
            <div className="relative mx-auto h-24 w-24 overflow-hidden rounded-full bg-[#2aabee] text-white">
              <span className="absolute inset-0 grid place-items-center text-3xl font-bold">{initial}</span>
              {avatarUrl ? (
                <img src={avatarUrl} alt="" className="relative h-full w-full object-cover" />
              ) : null}
            </div>
            <div className="mt-4 break-words text-xl font-bold text-zinc-950">{title}</div>
            {username ? (
              <div className="mt-1 text-sm text-[#229ed9]">@{username.replace(/^@/, '')}</div>
            ) : null}
            {previewBadgeText ? (
              <div className="mt-2 inline-flex rounded-full bg-[#e8f5fc] px-2.5 py-1 text-xs font-semibold text-[#1679aa]">
                {previewBadgeText}
              </div>
            ) : null}
            <div className="mt-4 whitespace-pre-wrap break-words text-sm leading-6 text-zinc-500">
              {previewDescription}
            </div>
            <div className="mt-5 flex min-h-11 items-center justify-center rounded-lg bg-[#2aabee] px-4 text-sm font-bold text-white">
              {previewButtonText}
            </div>
          </div>
        </div>
      </div>
    </fieldset>
  )
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
    triggers: (mapping.triggers ?? (
      ['page_view', 'telegram_click', 'bot_start', 'contact'].includes(mapping.source_event)
        ? []
        : [{ type: 'funnel_action' as const }]
    )).map((trigger) => ({ ...trigger })),
  }))
}

type FacebookEventMappingsEditorProps = {
  mappings: FacebookEventMapping[]
  sourceEvents: FacebookSourceEvent[]
  statuses: FacebookLeadStatusTrigger[]
  tags: FacebookTagTrigger[]
  destinationType: 'bot' | 'channel'
  onChange: (mappings: FacebookEventMapping[]) => void
}

function FacebookEventMappingsEditor({
  mappings,
  sourceEvents,
  statuses,
  tags,
  destinationType,
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

  const triggerIdentity = (trigger: FacebookEventTrigger) =>
    `${trigger.type}:${trigger.value ?? ''}`

  const defaultTrigger = (
    type: FacebookEventTriggerType,
    existing: FacebookEventTrigger[],
  ): FacebookEventTrigger | null => {
    const used = new Set(existing.map(triggerIdentity))
    if (type === 'funnel_action') {
      return used.has('funnel_action:') ? null : { type }
    }
    const options = type === 'lead_status' ? statuses : tags
    const option = options.find((item) => !used.has(`${type}:${item.id}`))
    return option ? { type, value: option.id } : null
  }

  const patchTrigger = (
    mappingIndex: number,
    triggerIndex: number,
    nextTrigger: FacebookEventTrigger,
  ) => {
    const mapping = mappings[mappingIndex]
    const triggers = mapping.triggers ?? []
    if (triggers.some(
      (trigger, index) => index !== triggerIndex && triggerIdentity(trigger) === triggerIdentity(nextTrigger),
    )) {
      return
    }
    patchMapping(mappingIndex, {
      triggers: triggers.map((trigger, index) => index === triggerIndex ? nextTrigger : trigger),
    })
  }

  const addTrigger = (mappingIndex: number) => {
    const triggers = mappings[mappingIndex].triggers ?? []
    const next = (
      defaultTrigger('funnel_action', triggers)
      ?? defaultTrigger('lead_status', triggers)
      ?? defaultTrigger('lead_tag', triggers)
    )
    if (next) {
      patchMapping(mappingIndex, { triggers: [...triggers, next] })
    }
  }

  const removeTrigger = (mappingIndex: number, triggerIndex: number) => {
    const triggers = mappings[mappingIndex].triggers ?? []
    if (triggers.length <= 1) {
      return
    }
    patchMapping(mappingIndex, {
      triggers: triggers.filter((_, index) => index !== triggerIndex),
    })
  }

  return (
    <div className="divide-y divide-white/10 rounded-lg border border-white/10 bg-zinc-950/40">
      {mappings.map((mapping, index) => {
        const source = sourceByKey.get(mapping.source_event)
        const isChannelMembershipEvent = destinationType === 'channel'
          && ['channel_subscribe', 'channel_unsubscribe'].includes(mapping.source_event)
        const isAutomatic = source?.trigger === 'automatic' || isChannelMembershipEvent
        const triggers = mapping.triggers ?? []
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
                  {' · '}{isChannelMembershipEvent
                    ? mapping.source_event === 'channel_subscribe'
                      ? 'Фактическое вступление по инвайту кампании'
                      : 'Фактический выход подписчика из канала'
                    : source?.trigger_description ?? (isAutomatic ? 'Автоматически' : 'По правилу CRM')}
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
            {!isAutomatic && mapping.enabled ? (
              <div className="space-y-2 rounded-md border border-white/10 bg-zinc-950/55 p-3 lg:col-span-full">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                      Когда отправлять событие
                    </div>
                    <p className="mt-1 text-xs leading-5 text-zinc-500">
                      Срабатывает при выполнении любого из правил. Для регистрации и депозита можно выбрать соответствующий тег.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => addTrigger(index)}
                    disabled={
                      !defaultTrigger('funnel_action', triggers)
                      && !defaultTrigger('lead_status', triggers)
                      && !defaultTrigger('lead_tag', triggers)
                    }
                    className="inline-flex min-h-10 items-center gap-2 rounded-md border border-white/10 px-3 text-sm font-medium text-zinc-200 transition hover:border-cyan-400/40 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4 shrink-0" aria-hidden="true" />
                    Добавить правило
                  </button>
                </div>
                <div className="space-y-2">
                  {triggers.map((trigger, triggerIndex) => {
                    const valueOptions = trigger.type === 'lead_status' ? statuses : tags
                    const otherTriggers = triggers.filter((_, itemIndex) => itemIndex !== triggerIndex)
                    const usedValues = new Set(
                      otherTriggers
                        .filter((item) => item.type === trigger.type)
                        .map((item) => item.value),
                    )
                    return (
                      <div
                        key={`${triggerIdentity(trigger)}:${triggerIndex}`}
                        className="grid min-w-0 gap-2 sm:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1.2fr)_40px]"
                      >
                        <select
                          value={trigger.type}
                          onChange={(event) => {
                            const type = event.target.value as FacebookEventTriggerType
                            const next = defaultTrigger(
                              type,
                              triggers.filter((_, itemIndex) => itemIndex !== triggerIndex),
                            )
                            if (next) {
                              patchTrigger(index, triggerIndex, next)
                            }
                          }}
                          className="min-h-10 min-w-0 rounded-md border border-white/10 bg-zinc-950 px-3 text-base text-zinc-100 outline-none ring-cyan-500 focus:ring-2 md:text-sm"
                          aria-label="Тип триггера Facebook-события"
                        >
                          <option value="funnel_action" disabled={!defaultTrigger('funnel_action', otherTriggers)}>CRM-действие воронки</option>
                          <option value="lead_status" disabled={!defaultTrigger('lead_status', otherTriggers)}>Статус изменён на</option>
                          <option value="lead_tag" disabled={!defaultTrigger('lead_tag', otherTriggers)}>Добавлен тег</option>
                        </select>
                        {trigger.type === 'funnel_action' ? (
                          <div className="flex min-h-10 min-w-0 items-center rounded-md border border-white/5 bg-white/[0.025] px-3 text-sm text-zinc-400">
                            Вызывается блоком «Отправить FB-событие»
                          </div>
                        ) : (
                          <select
                            value={trigger.value ?? ''}
                            onChange={(event) => patchTrigger(index, triggerIndex, {
                              ...trigger,
                              value: event.target.value,
                            })}
                            className="min-h-10 min-w-0 rounded-md border border-white/10 bg-zinc-950 px-3 text-base text-zinc-100 outline-none ring-cyan-500 focus:ring-2 md:text-sm"
                            aria-label={trigger.type === 'lead_status' ? 'Статус лида' : 'Тег лида'}
                          >
                            {trigger.value && !valueOptions.some((item) => item.id === trigger.value) ? (
                              <option value={trigger.value}>Недоступный объект · выберите другой</option>
                            ) : null}
                            {valueOptions.map((item) => (
                              <option key={item.id} value={item.id} disabled={usedValues.has(item.id)}>
                                {item.name}
                              </option>
                            ))}
                          </select>
                        )}
                        <button
                          type="button"
                          onClick={() => removeTrigger(index, triggerIndex)}
                          disabled={triggers.length <= 1}
                          className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-white/10 text-zinc-500 transition hover:border-red-400/40 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-30"
                          title={triggers.length <= 1 ? 'У события должно остаться хотя бы одно правило' : 'Удалить правило'}
                          aria-label="Удалить правило"
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </div>
                    )
                  })}
                </div>
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

export default function LandersSettings({
  projectId,
  campaignOnly = false,
  canManageDomains = true,
}: LandersSettingsProps) {
  const isBuyer = useAuthStore((state) => state.user?.role_name === 'buyer')
  const [domains, setDomains] = useState<ProjectDomain[]>([])
  const [landers, setLanders] = useState<ProjectLander[]>([])
  const [trackingLinks, setTrackingLinks] = useState<TrackingLinkOption[]>([])
  const [runtimeConfig, setRuntimeConfig] = useState<LanderRuntimeConfig | null>(null)
  const [bots, setBots] = useState<Bot[]>([])
  const [channels, setChannels] = useState<TelegramChannel[]>([])
  const [targetSteps, setTargetSteps] = useState<LanderTargetStep[]>([])
  const [isTargetStepsLoading, setIsTargetStepsLoading] = useState(false)
  const [editingTargetSteps, setEditingTargetSteps] = useState<LanderTargetStep[]>([])
  const [isEditingTargetStepsLoading, setIsEditingTargetStepsLoading] = useState(false)
  const [newDomainName, setNewDomainName] = useState('')
  const [newChannelReference, setNewChannelReference] = useState('')
  const [newChannelBotId, setNewChannelBotId] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isAddingDomain, setIsAddingDomain] = useState(false)
  const [isAddingChannel, setIsAddingChannel] = useState(false)
  const [mutatingChannelId, setMutatingChannelId] = useState<string | null>(null)
  const [deletingDomainId, setDeletingDomainId] = useState<string | null>(null)
  const [deletingLanderId, setDeletingLanderId] = useState<string | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isSavingLander, setIsSavingLander] = useState(false)
  const [editingLander, setEditingLander] = useState<ProjectLander | null>(null)
  const [editForm, setEditForm] = useState<LanderEditForm | null>(null)
  const [isUpdatingLander, setIsUpdatingLander] = useState(false)
  const [banner, setBanner] = useState<Banner | null>(null)
  const [copiedValue, setCopiedValue] = useState('')
  const [form, setForm] = useState<LanderForm>(emptyLanderForm)

  const trackingLinkById = useMemo(
    () => new Map(trackingLinks.map((link) => [link.id, link])),
    [trackingLinks],
  )
  const visibleLanders = useMemo(
    () => campaignOnly
      ? landers.filter((lander) => lander.facebook_campaign_enabled)
      : landers,
    [campaignOnly, landers],
  )
  const selectedCreateBot = useMemo(() => {
    if (form.trackingMode === 'campaign' && form.campaignDestinationType === 'channel') {
      return undefined
    }
    const botId = form.trackingMode === 'campaign'
      ? form.campaignBotId
      : trackingLinkById.get(form.trackingLinkId)?.bot_id
    return bots.find((bot) => bot.id === botId)
  }, [bots, form.campaignBotId, form.campaignDestinationType, form.trackingLinkId, form.trackingMode, trackingLinkById])
  const selectedCreateChannel = useMemo(() => {
    const channelId = form.trackingMode === 'campaign'
      ? form.campaignChannelId
      : trackingLinkById.get(form.trackingLinkId)?.channel_id
    return channels.find((channel) => channel.id === channelId)
  }, [channels, form.campaignChannelId, form.trackingLinkId, form.trackingMode, trackingLinkById])
  const selectedEditBot = useMemo(
    () => editForm?.destinationType === 'bot'
      ? bots.find((bot) => bot.id === editForm.botId)
      : undefined,
    [bots, editForm?.botId, editForm?.destinationType],
  )
  const selectedEditChannel = useMemo(
    () => channels.find((channel) => channel.id === editForm?.channelId),
    [channels, editForm?.channelId],
  )

  const loadData = useCallback(async () => {
    if (!projectId) {
      setDomains([])
      setLanders([])
      setTrackingLinks([])
      setBots([])
      setChannels([])
      setRuntimeConfig(null)
      return
    }

    setIsLoading(true)
    setBanner(null)
    try {
      const [domainItems, landerItems, linkItems, botItems, config, channelItems] = await Promise.all([
        fetchProjectDomains(projectId),
        fetchProjectLanders(projectId),
        fetchActiveTrackingLinks(projectId),
        fetchBots(projectId),
        fetchLanderRuntimeConfig(projectId),
        fetchTelegramChannels(projectId),
      ])
      setDomains(domainItems)
      setLanders(landerItems)
      setTrackingLinks(linkItems)
      setBots(botItems)
      setChannels(channelItems)
      setRuntimeConfig(config)
      setNewChannelBotId((current) => current || botItems[0]?.id || '')
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
      campaignDestinationType: 'bot',
      campaignChannelId: channels[0]?.id ?? '',
      slug: generateSlug(),
      campaignEventMappings: cloneEventMappings(runtimeConfig?.default_event_mappings ?? []),
      trackingMode: campaignOnly ? 'campaign' : emptyLanderForm.trackingMode,
    })
  }, [bots, campaignOnly, channels, runtimeConfig, trackingLinks])

  useEffect(() => {
    if (
      !isModalOpen
      || !projectId
      || form.trackingMode !== 'campaign'
      || form.campaignDestinationType !== 'bot'
      || !form.campaignBotId
    ) {
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
  }, [form.campaignBotId, form.campaignDestinationType, form.trackingMode, isModalOpen, projectId])

  useEffect(() => {
    const botId = editForm?.botId
    if (!editingLander || !projectId || editForm?.destinationType !== 'bot' || !botId) {
      setEditingTargetSteps([])
      setIsEditingTargetStepsLoading(false)
      return
    }

    let isMounted = true
    setIsEditingTargetStepsLoading(true)
    void fetchLanderTargetSteps(projectId, botId)
      .then((items) => {
        if (!isMounted) {
          return
        }
        setEditingTargetSteps(items)
        setEditForm((current) => {
          if (!current?.targetStepKey || items.some((item) => item.key === current.targetStepKey)) {
            return current
          }
          return { ...current, targetStepKey: '' }
        })
      })
      .catch(() => {
        if (isMounted) {
          setEditingTargetSteps([])
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsEditingTargetStepsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [editForm?.botId, editForm?.destinationType, editingLander, projectId])

  const openCreateModal = () => {
    resetForm()
    setBanner(null)
    setIsModalOpen(true)
  }

  const openEditLander = (lander: ProjectLander) => {
    const metaPixel = lander.pixels_json.find((pixel) => pixel.provider === 'meta')
    const campaign = lander.facebook_campaign
    const link = lander.tracking_link_id ? trackingLinkById.get(lander.tracking_link_id) : null
    setEditingLander(lander)
    setEditForm({
      name: lander.name,
      domainId: lander.domain_id ?? '',
      slug: lander.slug,
      description: lander.description ?? '',
      buttonText: lander.button_text
        ?? ((campaign?.destination_type ?? lander.destination_type) === 'channel'
          ? 'Подписаться на канал'
          : 'Open in Telegram'),
      badgeText: lander.badge_text
        ?? ((campaign?.destination_type ?? lander.destination_type) === 'channel'
          ? 'Telegram-канал'
          : ''),
      type: lander.type,
      destinationType: campaign?.destination_type ?? lander.destination_type ?? 'bot',
      botId: campaign?.bot_id ?? link?.bot_id ?? bots[0]?.id ?? '',
      channelId: campaign?.channel_id ?? lander.channel_id ?? link?.channel_id ?? '',
      campaignTitle: campaign?.title ?? link?.title ?? lander.name,
      campaignCode: campaign?.code ?? link?.code ?? '',
      buyerName: campaign?.buyer_name ?? '',
      adType: campaign?.ad_type ?? '',
      paymentType: campaign?.payment_type ?? '',
      baseConversionRate: String(campaign?.base_conversion_rate ?? 10),
      minSampleSize: String(campaign?.min_sample_size ?? 500),
      targetStepKey: campaign?.target_funnel_step_key ?? '',
      fbCampaignEnabled: lander.facebook_campaign_enabled,
      metaPixelId: lander.fb_pixel_id ?? metaPixel?.pixel_id ?? '',
      metaEvents: (lander.meta_events_json ?? []).map((event) => event.name).join(', '),
      capiToken: '',
      proxyUrl: '',
      testEventCode: lander.fb_test_event_code ?? '',
      eventMappings: cloneEventMappings(
        lander.fb_event_mappings_json.length > 0
          ? lander.fb_event_mappings_json
          : runtimeConfig?.default_event_mappings ?? [],
      ),
      clearCapiToken: false,
      clearProxyUrl: false,
      autoRedirectEnabled: lander.auto_redirect_enabled,
      utmSource: lander.utm_defaults_json.utm_source ?? '',
      utmMedium: lander.utm_defaults_json.utm_medium ?? '',
      utmCampaign: lander.utm_defaults_json.utm_campaign ?? '',
      utmTerm: lander.utm_defaults_json.utm_term ?? '',
      utmContent: lander.utm_defaults_json.utm_content ?? '',
      zipFile: null,
    })
    setBanner(null)
  }

  const handleUpdateLander = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || !editingLander || !editForm || isUpdatingLander) {
      return
    }
    const name = editForm.name.trim()
    const title = editForm.campaignTitle.trim()
    const code = editForm.campaignCode.trim()
    const slug = editForm.slug.trim()
    const baseConversionRate = Number(editForm.baseConversionRate)
    const minSampleSize = Number(editForm.minSampleSize)
    const hasDestination = editForm.destinationType === 'channel'
      ? Boolean(editForm.channelId)
      : Boolean(editForm.botId)
    if (!name || !title || !code || !hasDestination || !isValidLanderSlug(slug)) {
      setBanner({ tone: 'error', message: 'Заполните название, назначение, код и корректный slug.' })
      return
    }
    if (!Number.isFinite(baseConversionRate) || baseConversionRate < 0 || baseConversionRate > 100) {
      setBanner({ tone: 'error', message: 'Базовая конверсия должна быть от 0 до 100%.' })
      return
    }
    if (!Number.isInteger(minSampleSize) || minSampleSize < 1) {
      setBanner({ tone: 'error', message: 'Минимальная выборка должна быть целым числом от 1.' })
      return
    }
    if (
      editForm.type === 'custom_upload' &&
      !editForm.zipFile &&
      !editingLander.custom_html_path
    ) {
      setBanner({ tone: 'error', message: 'Для кастомного лендинга загрузите ZIP-архив.' })
      return
    }
    setIsUpdatingLander(true)
    setBanner(null)
    try {
      if (editForm.zipFile) {
        await uploadProjectLanderZip(projectId, editingLander.id, editForm.zipFile)
      }
      await updateProjectLander(projectId, editingLander.id, {
        domain_id: editForm.domainId || null,
        name,
        type: editForm.type,
        slug,
        description: editForm.description.trim() || null,
        button_text: editForm.buttonText.trim() || null,
        badge_text: editForm.badgeText.trim(),
        pixels: editForm.metaPixelId.trim()
          ? [{ provider: 'meta', pixel_id: editForm.metaPixelId.trim() }]
          : [],
        meta_events: buildMetaEvents(editForm.metaEvents),
        utm_defaults: {
          ...(editForm.utmSource.trim() ? { utm_source: editForm.utmSource.trim() } : {}),
          ...(editForm.utmMedium.trim() ? { utm_medium: editForm.utmMedium.trim() } : {}),
          ...(editForm.utmCampaign.trim() ? { utm_campaign: editForm.utmCampaign.trim() } : {}),
          ...(editForm.utmTerm.trim() ? { utm_term: editForm.utmTerm.trim() } : {}),
          ...(editForm.utmContent.trim() ? { utm_content: editForm.utmContent.trim() } : {}),
        },
        auto_redirect_enabled: editForm.autoRedirectEnabled,
        facebook_campaign: {
          enabled: editForm.fbCampaignEnabled,
          destination_type: editForm.destinationType,
          bot_id: editForm.destinationType === 'bot' ? editForm.botId : null,
          channel_id: editForm.destinationType === 'channel' ? editForm.channelId : null,
          title,
          code,
          buyer_name: editForm.buyerName.trim() || null,
          ad_type: editForm.adType.trim() || null,
          payment_type: editForm.paymentType.trim() || null,
          base_conversion_rate: baseConversionRate,
          min_sample_size: minSampleSize,
          target_funnel_step_key: editForm.destinationType === 'bot'
            ? editForm.targetStepKey || null
            : null,
          fb_pixel_id: editForm.metaPixelId.trim() || null,
          ...(editForm.capiToken.trim() ? { fb_capi_token: editForm.capiToken.trim() } : {}),
          clear_fb_capi_token: editForm.clearCapiToken,
          ...(editForm.proxyUrl.trim() ? { fb_proxy_url: editForm.proxyUrl.trim() } : {}),
          clear_fb_proxy_url: editForm.clearProxyUrl,
          fb_test_event_code: editForm.testEventCode.trim() || null,
          fb_event_mappings: editForm.eventMappings,
        },
      })
      setEditingLander(null)
      setEditForm(null)
      await loadData()
      setBanner({ tone: 'success', message: 'Лендинг, домен и параметры кампании сохранены.' })
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

  const handleAddChannel = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isAddingChannel || !newChannelBotId || !newChannelReference.trim()) {
      return
    }
    setIsAddingChannel(true)
    setBanner(null)
    try {
      await createTelegramChannel(projectId, {
        tracker_bot_id: newChannelBotId,
        telegram_chat_id: newChannelReference.trim(),
      })
      setNewChannelReference('')
      await loadData()
      setBanner({ tone: 'success', message: 'Канал проверен и подключён к трекингу.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось подключить Telegram-канал.'),
      })
    } finally {
      setIsAddingChannel(false)
    }
  }

  const handleVerifyChannel = async (channel: TelegramChannel) => {
    if (!projectId || mutatingChannelId) {
      return
    }
    setMutatingChannelId(channel.id)
    setBanner(null)
    try {
      await verifyTelegramChannel(projectId, channel.id)
      await loadData()
      setBanner({ tone: 'success', message: `Права трекера для «${channel.title}» подтверждены.` })
    } catch (err) {
      setBanner({ tone: 'error', message: getErrorMessage(err, 'Не удалось проверить канал.') })
    } finally {
      setMutatingChannelId(null)
    }
  }

  const handleDeleteChannel = async (channel: TelegramChannel) => {
    if (!projectId || mutatingChannelId) {
      return
    }
    if (!window.confirm(`Отключить канал «${channel.title}» от новых кампаний?`)) {
      return
    }
    setMutatingChannelId(channel.id)
    setBanner(null)
    try {
      await deleteTelegramChannel(projectId, channel.id)
      await loadData()
      setBanner({ tone: 'success', message: 'Канал отключён.' })
    } catch (err) {
      setBanner({ tone: 'error', message: getErrorMessage(err, 'Не удалось отключить канал.') })
    } finally {
      setMutatingChannelId(null)
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
    if (!campaignOnly && form.trackingMode === 'existing' && !form.trackingLinkId) {
      setBanner({ tone: 'error', message: 'Выберите существующую tracking link.' })
      return
    }
    if (
      form.trackingMode === 'campaign'
      && form.campaignDestinationType === 'bot'
      && !form.campaignBotId
    ) {
      setBanner({ tone: 'error', message: 'Выберите бота для кампании.' })
      return
    }
    if (
      form.trackingMode === 'campaign'
      && form.campaignDestinationType === 'channel'
      && !form.campaignChannelId
    ) {
      setBanner({ tone: 'error', message: 'Выберите подключённый Telegram-канал.' })
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
    let createdLander: ProjectLander | null = null
    try {
      createdLander = await createProjectLander(projectId, {
        domain_id: form.domainId || null,
        name: form.name.trim() || slug,
        type: form.type,
        slug,
        description: form.description.trim() || null,
        button_text: form.buttonText.trim() || null,
        badge_text: form.badgeText.trim(),
        tracking_link_id: !campaignOnly && form.trackingMode === 'existing' ? form.trackingLinkId : null,
        campaign: campaignOnly || form.trackingMode === 'campaign'
          ? {
              destination_type: form.campaignDestinationType,
              bot_id: form.campaignDestinationType === 'bot' ? form.campaignBotId : null,
              channel_id: form.campaignDestinationType === 'channel'
                ? form.campaignChannelId
                : null,
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
              target_funnel_step_key: form.campaignDestinationType === 'bot'
                ? form.campaignTargetStepKey || null
                : null,
            }
          : null,
        pixels: buildPixels(form),
        meta_events: buildMetaEvents(form.metaEvents),
        utm_defaults: buildUtmDefaults(form),
        auto_redirect_enabled: form.autoRedirectEnabled,
      })
      if (form.type === 'custom_upload' && form.zipFile) {
        await uploadProjectLanderZip(projectId, createdLander.id, form.zipFile)
      }
      setIsModalOpen(false)
      setForm(emptyLanderForm)
      await loadData()
      setBanner({
        tone: 'success',
        message: campaignOnly || form.trackingMode === 'campaign'
          ? 'FB-кампания, лендинг и отдельная tracking link созданы.'
          : 'Лендинг создан.',
      })
    } catch (err) {
      if (createdLander && form.type === 'custom_upload') {
        try {
          await deleteProjectLander(projectId, createdLander.id)
        } catch {
          // The original upload error is more useful to the operator.
        }
      }
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
          <h2 className="text-xl font-semibold text-zinc-100">
            {campaignOnly ? 'Facebook-кампании' : 'Лендинги и Домены'}
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            {campaignOnly
              ? 'Лендинг, рекламный домен, tracking link, Pixel и CAPI в одной кампании.'
              : 'Парковка доменов, прокладки и сквозная UTM-атрибуция в Telegram.'}
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateModal}
          disabled={bots.length === 0}
          className="inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={16} />
          {campaignOnly ? 'Создать FB-кампанию' : 'Создать лендинг'}
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

          {canManageDomains ? <form className="mt-4 flex flex-col gap-3 sm:flex-row" onSubmit={handleAddDomain}>
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
          </form> : (
            <p className="mt-4 rounded-lg border border-white/5 bg-zinc-950/40 px-3 py-2 text-xs leading-5 text-zinc-500">
              Домены подключает администратор. Здесь можно выбрать любой уже настроенный домен проекта.
            </p>
          )}

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
                        <div className="space-y-1">
                          <span
                            title={domain.routing_error ?? domain.cname_error ?? undefined}
                            className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${
                              domain.routing_verified
                                ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                                : 'border-red-500/25 bg-red-500/10 text-red-200'
                            }`}
                          >
                            {domain.routing_verified ? (
                              <CheckCircle2 size={13} className="shrink-0" />
                            ) : (
                              <AlertTriangle size={13} className="shrink-0" />
                            )}
                            {domain.routing_verified ? 'Домен доступен' : 'Ошибка маршрута'}
                          </span>
                          {domain.routing_error ? (
                            <div className="max-w-[360px] text-xs leading-5 text-red-200/80">
                              {domain.routing_error}
                            </div>
                          ) : null}
                          <div className="max-w-[360px] break-all font-mono text-xs leading-5 text-zinc-500">
                            DNS: {domain.cname_target
                              ?? (domain.routing_verified ? 'маршрут через CDN работает' : domain.cname_error)
                              ?? 'нет данных'}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end">
                          {canManageDomains ? <button
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
                          </button> : null}
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
                В Bunny DNS используйте один из двух вариантов: A-запись на IP origin-сервера с
                CDN Acceleration либо CNAME на hostname уже созданной Pull Zone
                <span className="font-mono text-cyan-50"> *.b-cdn.net</span> с выключенным CDN Acceleration
                у самой DNS-записи. Во втором варианте добавьте рекламный домен в Hostnames Pull Zone
                и включите SSL. Origin должен вести напрямую на сервер и сохранять исходный Host.
                Не направляйте ускоренный CNAME на
                <span className="font-mono text-cyan-50"> {runtimeConfig?.technical_domain ?? 'технический домен'}</span>
                или на другую Bunny-зону: это создаёт HTTP 508/цикл редиректов.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="flex items-center gap-2 text-base font-semibold text-zinc-100">
              <Radio size={17} className="shrink-0 text-cyan-300" />
              Каналы для залива
            </h3>
            <p className="mt-1 text-sm leading-5 text-zinc-500">
              Бот-трекер создаёт отдельную Telegram invite link для каждой кампании и фиксирует заявки, подписки и выходы.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={isLoading}
            title="Обновить каналы"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-cyan-500/40 hover:text-cyan-200 disabled:opacity-50"
          >
            <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>

        {!isBuyer ? (
          <form className="mt-4 grid gap-3 md:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1fr)_auto] md:items-end" onSubmit={handleAddChannel}>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">Бот-трекер</span>
              <select
                value={newChannelBotId}
                onChange={(event) => setNewChannelBotId(event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-cyan-500 transition focus:ring-2 md:text-sm"
              >
                <option value="">Выберите бота</option>
                {bots.map((bot) => (
                  <option key={bot.id} value={bot.id}>
                    {bot.name}{bot.bot_username ? ` · @${bot.bot_username.replace(/^@/, '')}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">Канал</span>
              <input
                value={newChannelReference}
                onChange={(event) => setNewChannelReference(event.target.value)}
                placeholder="@channel или -1001234567890"
                maxLength={255}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
              />
            </label>
            <button
              type="submit"
              disabled={isAddingChannel || !newChannelBotId || !newChannelReference.trim()}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-4 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isAddingChannel ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
              Подключить
            </button>
          </form>
        ) : (
          <p className="mt-4 rounded-lg border border-white/5 bg-zinc-950/40 px-3 py-2 text-xs leading-5 text-zinc-500">
            Каналы и права бота-трекера настраивает администратор. Вы можете выбрать любой готовый канал проекта в своей кампании.
          </p>
        )}

        <div className="mt-4 overflow-x-auto rounded-lg border border-white/5">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3">Канал</th>
                <th className="px-4 py-3">Бот-трекер</th>
                <th className="px-4 py-3">Готовность</th>
                <th className="w-[104px] px-4 py-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {channels.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-500">
                    Каналы пока не подключены.
                  </td>
                </tr>
              ) : channels.map((channel) => {
                const trackerBot = bots.find((bot) => bot.id === channel.tracker_bot_id)
                const ready = channel.bot_is_admin && channel.can_invite_users
                return (
                  <tr key={channel.id} className="bg-white/[0.01]">
                    <td className="px-4 py-3">
                      <div className="font-medium text-zinc-100">{channel.title}</div>
                      <div className="mt-1 font-mono text-xs text-zinc-500">
                        {channel.username ? `@${channel.username.replace(/^@/, '')}` : channel.telegram_chat_id}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-zinc-300">
                      {trackerBot?.name ?? channel.tracker_bot_id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-semibold ${
                        ready
                          ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200'
                          : 'border-red-500/25 bg-red-500/10 text-red-200'
                      }`}>
                        {ready ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
                        {ready ? 'Готов к трекингу' : 'Нет прав приглашения'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {!isBuyer ? (
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            title="Перепроверить права"
                            onClick={() => void handleVerifyChannel(channel)}
                            disabled={mutatingChannelId === channel.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-cyan-500/50 hover:text-cyan-200 disabled:opacity-50"
                          >
                            <RefreshCw size={14} className={mutatingChannelId === channel.id ? 'animate-spin' : ''} />
                          </button>
                          <button
                            type="button"
                            title="Отключить канал"
                            onClick={() => void handleDeleteChannel(channel)}
                            disabled={mutatingChannelId === channel.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-red-500/50 hover:text-red-300 disabled:opacity-50"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs leading-5 text-zinc-500">
          В Telegram добавьте выбранного бота администратором канала и включите право приглашать пользователей. После этого нажмите проверку.
        </p>
      </section>

      <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-zinc-100">
              {campaignOnly ? 'Кампании и лендинги' : 'Конструктор Прокладок'}
            </h3>
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
            {campaignOnly ? 'Создать FB-кампанию' : 'Создать лендинг'}
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
              {visibleLanders.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-sm text-zinc-500">
                    {campaignOnly ? 'FB-кампании пока не созданы.' : 'Лендинги пока не созданы.'}
                  </td>
                </tr>
              ) : (
                visibleLanders.map((lander) => {
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
                            {lander.destination_type === 'channel' ? (
                              <span className="rounded-md border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-sky-100">
                                Канал · {lander.channel_title || 'Telegram'}
                              </span>
                            ) : null}
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
                            title="Редактировать лендинг и кампанию"
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
          title={campaignOnly ? 'Создать Facebook-кампанию' : 'Создать лендинг'}
          description={campaignOnly
            ? 'CRM атомарно создаст отдельную tracking link и встроит её Telegram-переход в выбранный лендинг.'
            : 'По умолчанию создается отдельная campaign tracking link. Существующую ссылку можно выбрать только для осознанного переиспользования.'}
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
              {!campaignOnly ? <div className="mt-2 grid gap-2 sm:grid-cols-2">
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
                  onClick={() => setForm((current) => {
                    const trackingLinkId = current.trackingLinkId || trackingLinks[0]?.id || ''
                    const isChannel = trackingLinkById.get(trackingLinkId)?.destination_type === 'channel'
                    return {
                      ...current,
                      trackingMode: 'existing',
                      trackingLinkId,
                      buttonText: isChannel && current.buttonText === 'Open in Telegram'
                        ? 'Подписаться на канал'
                        : current.buttonText,
                      badgeText: isChannel && !current.badgeText
                        ? 'Telegram-канал'
                        : current.badgeText,
                    }
                  })}
                  className={`min-h-11 rounded-lg border px-3 text-left text-sm transition ${
                    form.trackingMode === 'existing'
                      ? 'border-cyan-400/50 bg-cyan-500/10 text-cyan-100'
                      : 'border-white/10 text-zinc-400 hover:border-white/20'
                  }`}
                >
                  <span className="block font-semibold">Использовать существующую</span>
                  <span className="mt-0.5 block text-xs opacity-75">Один источник для нескольких лендингов</span>
                </button>
              </div> : (
                <p className="mt-2 text-xs leading-5 text-zinc-500">
                  Для кампании всегда создаётся собственная tracking link: клики, старты, лиды и расходы не смешиваются с другими источниками.
                </p>
              )}

              {campaignOnly || form.trackingMode === 'campaign' ? (
                <div className="mt-4 space-y-3">
                  <div>
                    <span className="mb-1.5 block text-sm font-medium text-zinc-300">Куда вести трафик</span>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {([
                        ['bot', 'В бота', 'Старт, лид и прохождение воронки'],
                        ['channel', 'В канал', 'Подписки и отписки по персональной invite link'],
                      ] as const).map(([value, label, helper]) => (
                        <button
                          key={value}
                          type="button"
                          onClick={() => setForm((current) => ({
                            ...current,
                            campaignDestinationType: value,
                            campaignTargetStepKey: value === 'bot' ? current.campaignTargetStepKey : '',
                            buttonText: value === 'channel'
                              ? (!current.buttonText || current.buttonText === 'Open in Telegram' ? 'Подписаться на канал' : current.buttonText)
                              : (current.buttonText === 'Подписаться на канал' ? 'Open in Telegram' : current.buttonText),
                            badgeText: value === 'channel'
                              ? (current.badgeText || 'Telegram-канал')
                              : (current.badgeText === 'Telegram-канал' ? '' : current.badgeText),
                          }))}
                          className={`min-h-12 rounded-lg border px-3 py-2 text-left transition ${
                            form.campaignDestinationType === value
                              ? 'border-cyan-400/50 bg-cyan-500/10 text-cyan-100'
                              : 'border-white/10 text-zinc-400 hover:border-white/20'
                          }`}
                        >
                          <span className="block text-sm font-semibold">{label}</span>
                          <span className="mt-0.5 block text-xs opacity-75">{helper}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    {form.campaignDestinationType === 'bot' ? (
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
                    ) : (
                      <label className="block">
                        <span className="mb-1 block text-sm font-medium text-zinc-300">Telegram-канал</span>
                        <select
                          value={form.campaignChannelId}
                          onChange={(event) => setForm((current) => ({ ...current, campaignChannelId: event.target.value }))}
                          required
                          className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-cyan-500 transition focus:ring-2 md:text-sm"
                        >
                          <option value="">Выберите подключённый канал</option>
                          {channels.map((channel) => (
                            <option key={channel.id} value={channel.id}>
                              {channel.title}{channel.username ? ` · @${channel.username.replace(/^@/, '')}` : ''}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
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
                  {form.campaignDestinationType === 'channel' ? (
                    <div className="rounded-lg border border-cyan-400/20 bg-cyan-500/[0.06] px-3 py-3 text-sm leading-6 text-cyan-100/80">
                      CRM создаст ссылку-заявку. Автозапуск воронки и автоприём
                      настраивает суперадмин в разделе «Настройки → Система».
                    </div>
                  ) : null}
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
                    {!isBuyer ? <label className="block">
                      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">Баер</span>
                      <input
                        value={form.campaignBuyerName}
                        onChange={(event) => setForm((current) => ({ ...current, campaignBuyerName: event.target.value }))}
                        maxLength={255}
                        placeholder="Имя"
                        className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                      />
                    </label> : null}
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
                        <span className="mt-1.5 block text-xs leading-5 text-amber-300/80">
                          Только для вкладки Test events. Перед запуском рекламы очистите поле, иначе события не попадут в боевую статистику Ads Manager.
                        </span>
                      </label>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-zinc-500">
                      {isBuyer
                        ? 'Пустые Pixel ID и token будут взяты из настроек баер-бота, если они там заданы. Введённые здесь значения применятся только к этой кампании. '
                        : ''}
                      Кампанию можно сохранить без реквизитов Meta; события начнут отправляться после их настройки. Токен и proxy никогда не возвращаются из API.
                    </p>
                  </div>
                  <div className="border-t border-white/10 pt-4">
                    <div className="mb-1 text-sm font-semibold text-zinc-100">Карта событий</div>
                    <p className="mb-3 text-xs leading-5 text-zinc-500">
                      Автоматические события имеют фиксированную точку срабатывания. Для серверных событий задайте одно или несколько правил CRM: действие воронки, переход в статус или добавление тега.
                    </p>
                    <FacebookEventMappingsEditor
                      mappings={form.campaignEventMappings}
                      sourceEvents={runtimeConfig?.source_events ?? []}
                      statuses={runtimeConfig?.lead_statuses ?? []}
                      tags={runtimeConfig?.tags ?? []}
                      destinationType={form.campaignDestinationType}
                      onChange={(campaignEventMappings) => setForm((current) => ({ ...current, campaignEventMappings }))}
                    />
                  </div>
                  {form.campaignDestinationType === 'bot' ? <label className="block">
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
                  </label> : (
                    <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/[0.06] px-3 py-2 text-xs leading-5 text-cyan-100/75">
                      Для канала CRM создаст уникальную invite link. Клики, заявки, вступления, выходы и активные подписчики будут считаться отдельно от стартов и лидов бота.
                    </div>
                  )}
                </div>
              ) : (
                <label className="mt-4 block">
                  <span className="mb-1 block text-sm font-medium text-zinc-300">Существующая tracking link</span>
                  <select
                    value={form.trackingLinkId}
                    onChange={(event) => {
                      const trackingLinkId = event.target.value
                      const isChannel = trackingLinkById.get(trackingLinkId)?.destination_type === 'channel'
                      setForm((current) => ({
                        ...current,
                        trackingLinkId,
                        buttonText: isChannel
                          ? (current.buttonText === 'Open in Telegram' ? 'Подписаться на канал' : current.buttonText)
                          : (current.buttonText === 'Подписаться на канал' ? 'Open in Telegram' : current.buttonText),
                        badgeText: isChannel
                          ? (current.badgeText || 'Telegram-канал')
                          : (current.badgeText === 'Telegram-канал' ? '' : current.badgeText),
                      }))
                    }}
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

            {form.type === 'default_tg_redirect' ? (
              <TelegramLanderAppearanceEditor
                projectId={projectId}
                bot={selectedCreateBot}
                channel={selectedCreateChannel}
                description={form.description}
                buttonText={form.buttonText}
                badgeText={form.badgeText}
                onDescriptionChange={(description) => setForm((current) => ({ ...current, description }))}
                onButtonTextChange={(buttonText) => setForm((current) => ({ ...current, buttonText }))}
                onBadgeTextChange={(badgeText) => setForm((current) => ({ ...current, badgeText }))}
              />
            ) : null}

            <fieldset className="rounded-xl border border-white/10 bg-white/[0.02] p-3">
              <legend className="px-1 text-sm font-semibold text-zinc-100">Переход и UTM</legend>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                UTM из рекламного URL сохраняются у лида автоматически; значения ниже заполняют только отсутствующие параметры.
              </p>
              {!campaignOnly && form.trackingMode === 'existing' ? (
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

      {editingLander && editForm ? (
        <Modal
          title="Редактировать лендинг"
          description={`Домен, Telegram-переход и Facebook-кампания «${editingLander.name}».`}
          maxWidthClassName="max-w-4xl"
          onClose={() => {
            if (!isUpdatingLander) {
              setEditingLander(null)
              setEditForm(null)
            }
          }}
        >
          <form className="space-y-4" onSubmit={(event) => void handleUpdateLander(event)}>
            <fieldset className="space-y-3">
              <legend className="text-sm font-semibold text-zinc-100">Лендинг</legend>
              <div className="grid gap-3 md:grid-cols-2">
                <label className="block md:col-span-2">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Название</span>
                  <input value={editForm.name} onChange={(event) => setEditForm((current) => current ? { ...current, name: event.target.value } : current)} maxLength={255} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Домен</span>
                  <select value={editForm.domainId} onChange={(event) => setEditForm((current) => current ? { ...current, domainId: event.target.value } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm">
                    <option value="">Техдомен · {runtimeConfig?.technical_domain ?? 'не настроен'}</option>
                    {domains.map((domain) => <option key={domain.id} value={domain.id}>{domain.domain_name}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Тип лендинга</span>
                  <select value={editForm.type} onChange={(event) => setEditForm((current) => current ? { ...current, type: event.target.value as LanderType } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm">
                    <option value="default_tg_redirect">Telegram redirect</option>
                    <option value="custom_upload">Кастомный ZIP</option>
                  </select>
                </label>
                <label className="block md:col-span-2">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Slug</span>
                  <div className="flex gap-2">
                    <input value={editForm.slug} onChange={(event) => setEditForm((current) => current ? { ...current, slug: normalizeSlugInput(event.target.value) } : current)} maxLength={100} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                    <button type="button" title="Сгенерировать slug" onClick={() => setEditForm((current) => current ? { ...current, slug: generateSlug() } : current)} className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 text-zinc-300 transition hover:border-emerald-500/50 hover:text-emerald-200">
                      <RefreshCw size={16} />
                    </button>
                  </div>
                </label>
              </div>
              {editForm.type === 'custom_upload' ? (
                <label className="block rounded-lg border border-dashed border-white/10 px-3 py-3">
                  <span className="flex items-center gap-2 text-sm font-medium text-zinc-200"><Upload size={16} /> ZIP-архив</span>
                  <input type="file" accept=".zip,application/zip,application/x-zip-compressed" onChange={(event) => setEditForm((current) => current ? { ...current, zipFile: event.target.files?.[0] ?? null } : current)} className="mt-2 block w-full text-sm text-zinc-400 file:mr-3 file:rounded-lg file:border-0 file:bg-emerald-500 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-zinc-950" />
                  <span className="mt-1.5 block text-xs text-zinc-500">
                    {editForm.zipFile?.name ?? (editingLander.custom_html_path ? 'Текущий ZIP сохранён' : 'ZIP не загружен')}
                  </span>
                </label>
              ) : null}
            </fieldset>

            <fieldset className="space-y-3 border-t border-white/10 pt-4">
              <div className="flex items-center justify-between gap-3">
                <legend className="text-sm font-semibold text-zinc-100">Tracking campaign</legend>
                <label className="flex items-center gap-2 text-sm text-zinc-300">
                  <input type="checkbox" checked={editForm.fbCampaignEnabled} onChange={(event) => setEditForm((current) => current ? { ...current, fbCampaignEnabled: event.target.checked } : current)} className="h-5 w-5 accent-emerald-400" />
                  Facebook активен
                </label>
              </div>
              <div className="grid grid-cols-2 gap-2 rounded-lg border border-white/10 bg-zinc-950/50 p-1">
                {([
                  ['bot', 'В бота'],
                  ['channel', 'В канал'],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setEditForm((current) => {
                      if (!current) {
                        return current
                      }
                      const previousDefault = current.destinationType === 'channel'
                        ? 'Подписаться на канал'
                        : 'Open in Telegram'
                      const nextDefault = value === 'channel'
                        ? 'Подписаться на канал'
                        : 'Open in Telegram'
                      return {
                        ...current,
                        destinationType: value,
                        targetStepKey: value === 'channel' ? '' : current.targetStepKey,
                        buttonText: !current.buttonText.trim() || current.buttonText === previousDefault
                          ? nextDefault
                          : current.buttonText,
                        badgeText: value === 'channel'
                          ? (current.badgeText || 'Telegram-канал')
                          : (current.badgeText === 'Telegram-канал' ? '' : current.badgeText),
                      }
                    })}
                    className={`min-h-10 rounded-md px-3 text-sm font-semibold transition ${
                      editForm.destinationType === value
                        ? 'bg-cyan-500/15 text-cyan-100 ring-1 ring-cyan-400/40'
                        : 'text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-100'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {editForm.destinationType === 'bot' ? (
                  <>
                    <label className="block">
                      <span className="mb-1.5 block text-sm font-medium text-zinc-200">Бот</span>
                      <select value={editForm.botId} onChange={(event) => setEditForm((current) => current ? { ...current, botId: event.target.value, targetStepKey: '' } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm">
                        <option value="">Выберите бота</option>
                        {bots.map((bot) => <option key={bot.id} value={bot.id}>{bot.name}{bot.bot_username ? ` · @${bot.bot_username.replace(/^@/, '')}` : ''}</option>)}
                      </select>
                    </label>
                    <label className="block">
                      <span className="mb-1.5 block text-sm font-medium text-zinc-200">Стартовый шаг</span>
                      <select value={editForm.targetStepKey} disabled={!editForm.botId || isEditingTargetStepsLoading} onChange={(event) => setEditForm((current) => current ? { ...current, targetStepKey: event.target.value } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 disabled:opacity-50 md:text-sm">
                        <option value="">Старт активной воронки</option>
                        {editingTargetSteps.map((step) => <option key={step.key} value={step.key}>{step.title} · {step.key}</option>)}
                      </select>
                    </label>
                  </>
                ) : (
                  <>
                    <label className="block md:col-span-2">
                      <span className="mb-1.5 block text-sm font-medium text-zinc-200">Telegram-канал</span>
                      <select value={editForm.channelId} onChange={(event) => setEditForm((current) => current ? { ...current, channelId: event.target.value } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm">
                        <option value="">Выберите подключенный канал</option>
                        {channels.map((channel) => (
                          <option key={channel.id} value={channel.id}>
                            {channel.title}{channel.username ? ` · @${channel.username.replace(/^@/, '')}` : ''}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="md:col-span-2">
                      <div className="rounded-lg border border-cyan-400/20 bg-cyan-500/[0.06] px-3 py-3 text-sm leading-6 text-cyan-100/80">
                        Автозапуск воронки и автоприём заявок управляются суперадмином
                        в разделе «Настройки → Система».
                      </div>
                    </div>
                  </>
                )}
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Название кампании</span>
                  <input value={editForm.campaignTitle} onChange={(event) => setEditForm((current) => current ? { ...current, campaignTitle: event.target.value } : current)} maxLength={255} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Код ссылки</span>
                  <input value={editForm.campaignCode} onChange={(event) => setEditForm((current) => current ? { ...current, campaignCode: event.target.value } : current)} maxLength={64} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
                {!isBuyer ? <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Баер</span>
                  <input value={editForm.buyerName} onChange={(event) => setEditForm((current) => current ? { ...current, buyerName: event.target.value } : current)} maxLength={255} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label> : null}
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Тип рекламы</span>
                  <input value={editForm.adType} onChange={(event) => setEditForm((current) => current ? { ...current, adType: event.target.value } : current)} maxLength={100} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Модель оплаты</span>
                  <input value={editForm.paymentType} onChange={(event) => setEditForm((current) => current ? { ...current, paymentType: event.target.value } : current)} maxLength={100} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Базовая конверсия, %</span>
                  <input type="number" min="0" max="100" step="0.1" value={editForm.baseConversionRate} onChange={(event) => setEditForm((current) => current ? { ...current, baseConversionRate: event.target.value } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-zinc-200">Минимальная выборка</span>
                  <input type="number" min="1" step="1" value={editForm.minSampleSize} onChange={(event) => setEditForm((current) => current ? { ...current, minSampleSize: event.target.value } : current)} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                </label>
              </div>
            </fieldset>

            {editForm.type === 'default_tg_redirect' ? (
              <TelegramLanderAppearanceEditor
                projectId={projectId}
                bot={selectedEditBot}
                channel={selectedEditChannel}
                description={editForm.description}
                buttonText={editForm.buttonText}
                badgeText={editForm.badgeText}
                onDescriptionChange={(description) => setEditForm((current) => current ? { ...current, description } : current)}
                onButtonTextChange={(buttonText) => setEditForm((current) => current ? { ...current, buttonText } : current)}
                onBadgeTextChange={(badgeText) => setEditForm((current) => current ? { ...current, badgeText } : current)}
              />
            ) : null}

            <fieldset className="space-y-3 border-t border-white/10 pt-4">
              <legend className="text-sm font-semibold text-zinc-100">Facebook Pixel и CAPI</legend>
              <div className="grid gap-3 md:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Pixel / Dataset ID</span>
                <input value={editForm.metaPixelId} onChange={(event) => setEditForm((current) => current ? { ...current, metaPixelId: event.target.value } : current)} inputMode="numeric" placeholder="1234567890" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Новый CAPI token</span>
                <input type="password" value={editForm.capiToken} disabled={editForm.clearCapiToken} onChange={(event) => setEditForm((current) => current ? { ...current, capiToken: event.target.value } : current)} placeholder={editingLander.has_fb_capi_token ? 'Уже задан · оставить пустым' : 'Access token'} autoComplete="off" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 disabled:opacity-45 md:text-sm" />
                {editingLander.has_fb_capi_token ? (
                  <label className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                    <input type="checkbox" checked={editForm.clearCapiToken} onChange={(event) => setEditForm((current) => current ? { ...current, clearCapiToken: event.target.checked } : current)} className="h-4 w-4 accent-red-400" />
                    Удалить сохранённый token
                  </label>
                ) : null}
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Новый CAPI proxy</span>
                <input type="password" value={editForm.proxyUrl} disabled={editForm.clearProxyUrl} onChange={(event) => setEditForm((current) => current ? { ...current, proxyUrl: event.target.value } : current)} placeholder={editingLander.has_fb_proxy ? 'Уже задан · оставить пустым' : 'http://user:pass@proxy:8080'} autoComplete="off" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 disabled:opacity-45 md:text-sm" />
                {editingLander.has_fb_proxy ? (
                  <label className="mt-2 flex items-center gap-2 text-xs text-zinc-400">
                    <input type="checkbox" checked={editForm.clearProxyUrl} onChange={(event) => setEditForm((current) => current ? { ...current, clearProxyUrl: event.target.checked } : current)} className="h-4 w-4 accent-red-400" />
                    Удалить сохранённый proxy
                  </label>
                ) : null}
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-zinc-200">Test event code</span>
                <input value={editForm.testEventCode} onChange={(event) => setEditForm((current) => current ? { ...current, testEventCode: event.target.value } : current)} placeholder="TEST12345" maxLength={100} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
                <span className="mt-1.5 block text-xs leading-5 text-amber-300/80">Только для Test events. Для боевой атрибуции Ads Manager поле должно быть пустым.</span>
              </label>
              </div>
            </fieldset>
            <div>
              <div className="mb-1.5 text-sm font-medium text-zinc-200">Карта событий</div>
              <FacebookEventMappingsEditor
                mappings={editForm.eventMappings}
                sourceEvents={runtimeConfig?.source_events ?? []}
                statuses={runtimeConfig?.lead_statuses ?? []}
                tags={runtimeConfig?.tags ?? []}
                destinationType={editForm.destinationType}
                onChange={(eventMappings) => setEditForm((current) => current ? { ...current, eventMappings } : current)}
              />
            </div>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-zinc-200">Legacy события лендинга</span>
              <input value={editForm.metaEvents} onChange={(event) => setEditForm((current) => current ? { ...current, metaEvents: event.target.value } : current)} placeholder="QuizCompleted" className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm" />
              <span className="mt-1.5 block text-xs leading-5 text-zinc-500">Только для старых ZIP с data-crm-meta-event. Новые лендинги используют карту выше.</span>
            </label>
            <fieldset className="space-y-3 border-t border-white/10 pt-4">
              <legend className="text-sm font-semibold text-zinc-100">UTM по умолчанию</legend>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {([
                  ['utmSource', 'utm_source'],
                  ['utmMedium', 'utm_medium'],
                  ['utmCampaign', 'utm_campaign'],
                  ['utmTerm', 'utm_term'],
                  ['utmContent', 'utm_content'],
                ] as const).map(([field, label]) => (
                  <label key={field} className="block">
                    <span className="mb-1.5 block text-sm font-medium text-zinc-200">{label}</span>
                    <input value={editForm[field]} onChange={(event) => setEditForm((current) => current ? { ...current, [field]: event.target.value } : current)} maxLength={255} className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 md:text-sm" />
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-white/10 bg-zinc-950/50 px-3 py-2.5 text-sm text-zinc-200">
              <span>
                <span className="block font-medium text-zinc-100">Автопереход в Telegram</span>
                <span className="mt-0.5 block text-xs text-zinc-500">Для custom ZIP настройте переход в коде лендинга.</span>
              </span>
              <input type="checkbox" checked={editForm.autoRedirectEnabled} disabled={editForm.type === 'custom_upload'} onChange={(event) => setEditForm((current) => current ? { ...current, autoRedirectEnabled: event.target.checked } : current)} className="h-5 w-5 shrink-0 accent-emerald-400 disabled:opacity-40" />
            </label>
            <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => { setEditingLander(null); setEditForm(null) }} disabled={isUpdatingLander} className="inline-flex h-10 items-center justify-center rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50">Отмена</button>
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

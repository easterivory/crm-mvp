import {
  CalendarDays,
  Check,
  CheckCircle2,
  Clock3,
  Copy,
  Globe2,
  MessageSquareText,
  Pencil,
  Phone,
  Tag,
  Trash2,
  TrendingUp,
  Undo2,
  UserRound,
  WalletCards,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'

import DuplicateWarning from './DuplicateWarning'
import type { Lead } from '../types'

type LeadCardProps = {
  lead: Lead
  projectId: string
  isMutating: boolean
  isTrashView?: boolean
  onTrash?: (lead: Lead) => void
  onRestore?: (lead: Lead) => void
  onOpenChat?: (lead: Lead) => void
  onSubmitToPartner?: (lead: Lead) => void
  onEdit?: (lead: Lead) => void
  visibleFields?: readonly string[]
}

export const DEFAULT_LEAD_CARD_FIELDS = [
  'phone',
  'call_time',
  'created_at',
  'manager',
  'country',
  'expected_start_amount',
  'tracking',
  'submission_partner',
  'submitted_at',
  'score',
  'chat_id',
  'telegram_id',
  'tags',
  'attribution',
  'custom_fields',
] as const

export const LEAD_CARD_FIELD_OPTIONS = [
  ['phone', 'Телефон'],
  ['username', 'Username'],
  ['age', 'Возраст'],
  ['has_card', 'Банковская карта'],
  ['call_time', 'Время созвона'],
  ['created_at', 'Дата создания'],
  ['manager', 'Менеджер'],
  ['country', 'Страна'],
  ['expected_start_amount', 'Сумма для старта'],
  ['tracking', 'Трекинг'],
  ['submission_partner', 'Партнёр подачи'],
  ['submitted_at', 'Дата подачи'],
  ['score', 'Качество лида'],
  ['chat_id', 'Chat ID'],
  ['telegram_id', 'Telegram ID'],
  ['tags', 'Теги'],
  ['attribution', 'Атрибуция'],
  ['custom_fields', 'Все данные из воронки'],
] as const

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'Не указано'
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function empty(value?: string | null) {
  return value && value.trim() ? value : 'Не указано'
}

function withAlpha(hex: string | null | undefined, alpha: number) {
  const value = hex?.trim()
  if (!value || !/^#[0-9A-Fa-f]{6}$/.test(value)) {
    return `rgba(255,255,255,${alpha})`
  }
  const red = Number.parseInt(value.slice(1, 3), 16)
  const green = Number.parseInt(value.slice(3, 5), 16)
  const blue = Number.parseInt(value.slice(5, 7), 16)
  return `rgba(${red},${green},${blue},${alpha})`
}

function botLabel(lead: Lead) {
  if (!lead.bot_name && !lead.bot_username) {
    return 'Бот не указан'
  }

  return [lead.bot_name, lead.bot_username ? `@${lead.bot_username}` : null]
    .filter(Boolean)
    .join(' · ')
}

function attributionEntries(customFields: Record<string, unknown> | null | undefined) {
  const raw = customFields?.fb_data
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return []
  }

  return Object.entries(raw as Record<string, unknown>)
    .filter(([key, value]) => (
      key.startsWith('utm_') || ['fbclid', 'gclid', 'ttclid'].includes(key)
    ) && (typeof value === 'string' || typeof value === 'number'))
    .map(([key, value]) => [key, String(value)] as const)
}

export function leadCustomFieldEntries(customFields: Record<string, unknown> | null | undefined) {
  if (!customFields) {
    return []
  }
  return Object.entries(customFields)
    .filter(([key, value]) => (
      key !== 'fb_data'
      && key !== 'expected_start_amount'
      && key !== 'budget'
      && key !== 'first_name'
      && key !== 'last_name'
      && !key.startsWith('__')
      && value !== null
      && value !== undefined
      && ['string', 'number', 'boolean'].includes(typeof value)
      && String(value).trim() !== ''
    ))
    .map(([key, value]) => ({
      key,
      label: key.replace(/_/g, ' ').replace(/^\p{L}/u, (letter) => letter.toUpperCase()),
      value: typeof value === 'boolean' ? (value ? 'Да' : 'Нет') : String(value),
    }))
}

function expectedStartAmount(customFields: Record<string, unknown> | null | undefined) {
  const value = customFields?.expected_start_amount ?? customFields?.budget
  return value === null || value === undefined || String(value).trim() === ''
    ? 'Не указано'
    : String(value)
}

export default function LeadCard({
  lead,
  projectId,
  isMutating,
  isTrashView = false,
  onTrash,
  onRestore,
  onOpenChat,
  onSubmitToPartner,
  onEdit,
  visibleFields = DEFAULT_LEAD_CARD_FIELDS,
}: LeadCardProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const title =
    lead.name ||
    lead.contact_name ||
    (lead.username ? `@${lead.username}` : null) ||
    `Telegram ${lead.external_chat_id ?? lead.id.slice(0, 8)}`
  const attribution = attributionEntries(lead.custom_fields)
  const customFields = leadCustomFieldEntries(lead.custom_fields)
  const visibleFieldSet = new Set(visibleFields)
  const isVisible = (field: string) => visibleFieldSet.has(field)
  const visibleCustomFields = customFields.filter(
    (field) => isVisible('custom_fields') || isVisible(`custom:${field.key}`),
  )

  const handleCopy = async (key: string, value: string | null | undefined) => {
    if (!value) {
      return
    }
    await navigator.clipboard.writeText(value)
    setCopiedField(key)
    window.setTimeout(() => {
      setCopiedField((current) => (current === key ? null : current))
    }, 1400)
  }

  return (
    <article className="rounded-xl border border-white/5 bg-surface p-4 shadow-card">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-accent-300/20 bg-accent-400/10 text-accent-200 shadow-glow-accent">
              <UserRound size={20} />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-white">{title}</h2>
              <p className="truncate text-sm text-gray-500">{botLabel(lead)}</p>
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="w-fit rounded-full bg-primary-500/12 px-3 py-1 text-xs font-medium text-primary-100">
            {lead.status_name ?? lead.status_code ?? 'Статус не указан'}
          </span>
          {onEdit ? (
            <button
              type="button"
              onClick={() => onEdit(lead)}
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
              title="Редактировать лида"
              aria-label="Редактировать лида"
            >
              <Pencil size={14} />
            </button>
          ) : null}
        </div>
      </div>

      <DuplicateWarning leadId={lead.id} projectId={projectId} className="mt-4" />

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {isVisible('phone') ? <Info icon={<Phone size={15} />} label="Телефон" value={empty(lead.phone)} /> : null}
        {isVisible('username') ? <Info icon={<UserRound size={15} />} label="Username" value={empty(lead.username ? `@${lead.username.replace(/^@/, '')}` : null)} /> : null}
        {isVisible('age') ? <Info icon={<UserRound size={15} />} label="Возраст" value={lead.age === null ? 'Не указано' : String(lead.age)} /> : null}
        {isVisible('has_card') ? <Info icon={<WalletCards size={15} />} label="Банковская карта" value={lead.has_card === null ? 'Не указано' : lead.has_card ? 'Есть' : 'Нет'} /> : null}
        {isVisible('call_time') ? <Info
          icon={<Clock3 size={15} />}
          label="Время созвона"
          value={empty(lead.preferred_call_time ?? lead.call_time_text)}
        /> : null}
        {isVisible('created_at') ? <Info icon={<CalendarDays size={15} />} label="Создан" value={formatDate(lead.created_at)} /> : null}
        {isVisible('manager') ? <Info icon={<UserRound size={15} />} label="Менеджер" value={empty(lead.manager_name)} /> : null}
        {isVisible('country') ? <Info icon={<Globe2 size={15} />} label="Страна" value={empty(lead.country)} /> : null}
        {isVisible('expected_start_amount') ? <Info
          icon={<WalletCards size={15} />}
          label="Сумма для старта"
          value={expectedStartAmount(lead.custom_fields)}
        /> : null}
        {isVisible('tracking') ? <Info
          icon={<Tag size={15} />}
          label="Трекинг"
          value={empty(lead.tracking_code ?? lead.tracking_ref_code)}
        /> : null}
        {isVisible('submission_partner') && lead.submission_partner_name ? <Info icon={<TrendingUp size={15} />} label="Партнёр подачи" value={lead.submission_partner_name} /> : null}
        {isVisible('submitted_at') && lead.submitted_at ? <Info icon={<CheckCircle2 size={15} />} label="Подан" value={formatDate(lead.submitted_at)} /> : null}
        {isVisible('score') && lead.score_percent !== null && lead.score_percent !== undefined && (
          <Info
            icon={<TrendingUp size={15} />}
            label="Качество лида"
            value={`${lead.score_percent}%`}
          />
        )}
        {isVisible('chat_id') ? <CopyInfo
          label="Chat ID"
          value={lead.chat_id}
          isCopied={copiedField === 'chat_id'}
          onCopy={() => void handleCopy('chat_id', lead.chat_id)}
        /> : null}
        {isVisible('telegram_id') ? <CopyInfo
          label="Telegram ID"
          value={lead.external_user_id ?? lead.external_chat_id ?? null}
          isCopied={copiedField === 'telegram_id'}
          onCopy={() => void handleCopy('telegram_id', lead.external_user_id ?? lead.external_chat_id)}
        /> : null}
      </div>

      {isVisible('tags') ? <div className="mt-4 flex flex-wrap gap-2">
        {lead.tags.length > 0 ? (
          lead.tags.map((tag) => (
            <span
              key={tag.id}
              className="rounded-full border px-2 py-1 text-xs font-medium text-gray-50"
              style={{
                backgroundColor: withAlpha(tag.color, 0.14),
                borderColor: withAlpha(tag.color, 0.55),
              }}
            >
              {tag.name}
            </span>
          ))
        ) : (
          <span className="text-sm text-gray-500">Тегов пока нет</span>
        )}
      </div> : null}

      {isVisible('attribution') && attribution.length > 0 ? (
        <div className="mt-4 rounded-xl border border-cyan-300/15 bg-cyan-400/[0.05] p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-cyan-100/80">Атрибуция</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {attribution.map(([key, value]) => (
              <span key={key} className="rounded-md border border-cyan-300/15 bg-background/40 px-2 py-1 text-xs text-gray-200">
                <span className="text-cyan-100">{key}</span>={value}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {visibleCustomFields.length > 0 ? (
        <div className="mt-4 rounded-xl border border-white/8 bg-white/[0.025] p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Данные из воронки
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {visibleCustomFields.map((field) => (
              <div key={field.key} className="flex items-start justify-between gap-3 text-sm">
                <span className="text-gray-500">{field.label}</span>
                <span className="max-w-[60%] break-words text-right text-gray-100">
                  {field.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {isTrashView ? (
        onRestore ? (
          <div className="mt-5">
            <button
              type="button"
              onClick={() => onRestore(lead)}
              disabled={isMutating}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-emerald-300/35 bg-emerald-500/15 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition hover:border-emerald-200/70 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-10 sm:py-0"
            >
              <Undo2 size={17} />
              Восстановить лида
            </button>
          </div>
        ) : null
      ) : (
        <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
          {onOpenChat ? (
            <button
              type="button"
              onClick={() => onOpenChat(lead)}
              disabled={!lead.chat_id}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-sky-300/35 bg-sky-400/10 px-4 py-2.5 text-sm font-semibold text-sky-100 transition hover:border-sky-200/70 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-10 sm:py-0"
            >
              <MessageSquareText size={16} />
              Перейти в чат
            </button>
          ) : null}
          {onSubmitToPartner && (
            <button
              type="button"
              onClick={() => onSubmitToPartner(lead)}
              disabled={isMutating}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition hover:border-emerald-300/60 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-10 sm:py-0"
            >
              <TrendingUp size={16} />
              Подать в CRM партнёра
            </button>
          )}
          {onTrash ? (
            <button
              type="button"
              onClick={() => onTrash(lead)}
              disabled={isMutating}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-2.5 text-sm font-semibold text-red-100 transition hover:border-red-300/60 disabled:cursor-not-allowed disabled:opacity-50 sm:min-h-10 sm:py-0"
            >
              <Trash2 size={16} />
              В корзину
            </button>
          ) : null}
        </div>
      )}
    </article>
  )
}

function CopyInfo({
  label,
  value,
  isCopied,
  onCopy,
}: {
  label: string
  value: string | null
  isCopied: boolean
  onCopy: () => void
}) {
  return (
    <div className="min-w-0 rounded-xl border border-white/5 bg-white/[0.03] p-3">
      <div className="mb-1 flex items-center justify-between gap-2 text-xs text-gray-500">
        <span>{label}</span>
        <button
          type="button"
          onClick={onCopy}
          disabled={!value}
          title={`Скопировать ${label}`}
          className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-white/10 text-gray-300 transition hover:border-accent-300/40 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isCopied ? <Check size={12} /> : <Copy size={12} />}
        </button>
      </div>
      <p className="truncate text-sm font-medium text-white">{value || 'Не указано'}</p>
    </div>
  )
}

function Info({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div className="min-w-0 rounded-xl border border-white/5 bg-white/[0.03] p-3">
      <div className="mb-1 flex items-center gap-2 text-xs text-gray-500">
        {icon}
        {label}
      </div>
      <p className="truncate text-sm font-medium text-white">{value}</p>
    </div>
  )
}

import {
  CalendarDays,
  Clock3,
  Globe2,
  Phone,
  Send,
  Tag,
  Trash2,
  UserRound,
} from 'lucide-react'
import type { ReactNode } from 'react'

import type { Lead } from '../types'

type LeadCardProps = {
  lead: Lead
  isMutating: boolean
  onSubmit: (lead: Lead) => void
  onReject: (lead: Lead) => void
}

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

function botLabel(lead: Lead) {
  if (!lead.bot_name && !lead.bot_username) {
    return 'Бот не указан'
  }

  return [lead.bot_name, lead.bot_username ? `@${lead.bot_username}` : null]
    .filter(Boolean)
    .join(' · ')
}

export default function LeadCard({
  lead,
  isMutating,
  onSubmit,
  onReject,
}: LeadCardProps) {
  const title =
    lead.contact_name ||
    (lead.username ? `@${lead.username}` : null) ||
    `Telegram ${lead.external_chat_id ?? lead.id.slice(0, 8)}`

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

        <span className="w-fit rounded-full bg-primary-500/12 px-3 py-1 text-xs font-medium text-primary-100">
          {lead.status_name ?? lead.status_code ?? 'Статус не указан'}
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Info icon={<Phone size={15} />} label="Телефон" value={empty(lead.phone)} />
        <Info icon={<Clock3 size={15} />} label="Время созвона" value="Не указано" />
        <Info icon={<CalendarDays size={15} />} label="Создан" value={formatDate(lead.created_at)} />
        <Info icon={<UserRound size={15} />} label="Менеджер" value={empty(lead.manager_name)} />
        <Info icon={<Globe2 size={15} />} label="Страна" value="Не указано" />
        <Info
          icon={<Tag size={15} />}
          label="Трекинг"
          value={empty(lead.tracking_code ?? lead.tracking_ref_code)}
        />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {lead.tags.length > 0 ? (
          lead.tags.map((tag) => (
            <span
              key={tag.id}
              className="rounded-full bg-accent-500/10 px-2 py-1 text-xs font-medium text-accent-100"
            >
              {tag.name}
            </span>
          ))
        ) : (
          <span className="text-sm text-gray-500">Тегов пока нет</span>
        )}
      </div>

      <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          onClick={() => onSubmit(lead)}
          disabled={isMutating || lead.status_code === 'qualified'}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send size={16} />
          Отправить
        </button>
        <button
          type="button"
          onClick={() => onReject(lead)}
          disabled={isMutating || lead.status_code === 'lost'}
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-4 text-sm font-semibold text-red-100 transition hover:border-red-300/60 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Trash2 size={16} />
          Удалить
        </button>
      </div>
    </article>
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

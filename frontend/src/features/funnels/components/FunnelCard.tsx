import { Archive, Bot, Copy, Edit3, RadioTower } from 'lucide-react'

import type { Bot as BotRecord } from '../../bots'
import type { Funnel } from '../types'

type FunnelCardProps = {
  funnel: Funnel
  bot: BotRecord | undefined
  onOpen: (funnel: Funnel) => void
  onCopy: (funnel: Funnel) => void
  onArchive: (funnel: Funnel) => void
}

export default function FunnelCard({
  funnel,
  bot,
  onOpen,
  onCopy,
  onArchive,
}: FunnelCardProps) {
  const hasPublished = Boolean(funnel.published_version_id)

  return (
    <article className="rounded-lg border border-white/8 bg-white/[0.035] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-white">{funnel.name}</h3>
          <p className="mt-1 line-clamp-2 text-sm leading-5 text-gray-500">
            {funnel.description || 'Описание не указано'}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-1 text-xs ${
            hasPublished
              ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
              : 'border-amber-300/25 bg-amber-300/10 text-amber-100'
          }`}
        >
          {hasPublished ? 'published' : 'draft'}
        </span>
      </div>

      <div className="mt-4 flex items-center gap-2 text-sm text-gray-400">
        <Bot size={15} />
        <span className="truncate">
          {bot ? `${bot.name}${bot.bot_username ? ` · @${bot.bot_username}` : ''}` : 'Бот не найден'}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onOpen(funnel)}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-accent-300/25 bg-accent-300/10 px-3 text-sm font-medium text-accent-50 transition hover:border-accent-300/50"
        >
          <Edit3 size={15} />
          Открыть
        </button>
        <button
          type="button"
          onClick={() => onCopy(funnel)}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-gray-200 transition hover:border-white/20"
        >
          <Copy size={15} />
          Копировать
        </button>
        <button
          type="button"
          onClick={() => onArchive(funnel)}
          disabled={funnel.status === 'archived'}
          className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/15 bg-transparent px-3 text-sm text-red-200 transition hover:border-red-300/35 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Archive size={15} />
          Архив
        </button>
      </div>

      {hasPublished ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-emerald-200/80">
          <RadioTower size={13} />
          Есть опубликованная версия
        </div>
      ) : null}
    </article>
  )
}

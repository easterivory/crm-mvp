import { Archive, Bot, Copy, Edit3, LoaderCircle, RotateCcw } from 'lucide-react'

import type { Bot as BotRecord } from '../../bots'
import type { Funnel } from '../types'

type FunnelCardProps = {
  funnel: Funnel
  bot: BotRecord | undefined
  canEdit: boolean
  canRestartSelf: boolean
  isRestartingSelf: boolean
  onOpen: (funnel: Funnel) => void
  onCopy: (funnel: Funnel) => void
  onArchive: (funnel: Funnel) => void
  onSetCurrentVersion: (funnel: Funnel, versionId: string) => void
  onRestartSelf: (funnel: Funnel) => void
}

export default function FunnelCard({
  funnel,
  bot,
  canEdit,
  canRestartSelf,
  isRestartingSelf,
  onOpen,
  onCopy,
  onArchive,
  onSetCurrentVersion,
  onRestartSelf,
}: FunnelCardProps) {
  const publishedVersions = funnel.published_versions ?? []
  const hasPublished = publishedVersions.length > 0
  const activeVersion = publishedVersions.find((version) => version.is_active_for_bot)
  const currentVersion =
    publishedVersions.find((version) => version.is_current_for_funnel) ??
    publishedVersions[0] ??
    null

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
          {hasPublished ? `Версий: ${publishedVersions.length}` : 'Черновик'}
        </span>
        {funnel.is_active_for_bot ? (
          <span className="shrink-0 rounded-full border border-cyan-300/25 bg-cyan-300/10 px-2 py-1 text-xs text-cyan-100">
            Активна
          </span>
        ) : null}
      </div>

      <div className="mt-4 flex items-center gap-2 text-sm text-gray-400">
        <Bot size={15} />
        <span className="truncate">
          {bot ? `${bot.name}${bot.bot_username ? ` · @${bot.bot_username}` : ''}` : 'Бот не найден'}
        </span>
      </div>

      {hasPublished ? (
        <div className="mt-4 rounded-lg border border-white/8 bg-background/45 px-3 py-2">
          <label className="block text-[11px] font-medium uppercase tracking-wide text-gray-500">
            Актуальная версия
          </label>
          {canEdit ? (
            <select
              value={currentVersion?.id ?? ''}
              onChange={(event) => {
                const nextVersionId = event.target.value
                event.currentTarget.value = currentVersion?.id ?? ''
                if (nextVersionId && nextVersionId !== currentVersion?.id) {
                  onSetCurrentVersion(funnel, nextVersionId)
                }
              }}
              className="mt-1.5 h-9 w-full rounded-lg border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
              aria-label={`Актуальная версия воронки ${funnel.name}`}
            >
              {publishedVersions.map((version) => (
                <option key={version.id} value={version.id}>
                  v{version.version_number}
                  {version.is_active_for_bot ? ' · активна на боте' : ''}
                </option>
              ))}
            </select>
          ) : (
            <p className="mt-1.5 text-sm text-gray-300">
              {currentVersion ? `v${currentVersion.version_number}` : 'Не выбрана'}
            </p>
          )}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {canRestartSelf ? (
          <button
            type="button"
            onClick={() => onRestartSelf(funnel)}
            disabled={!currentVersion || isRestartingSelf}
            title={
              currentVersion
                ? `Сбросить у себя до начала актуальной версии v${currentVersion.version_number}`
                : 'Сначала опубликуйте версию воронки'
            }
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-300/10 px-3 text-sm font-medium text-cyan-50 transition hover:border-cyan-300/50 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {isRestartingSelf ? (
              <LoaderCircle size={15} className="animate-spin" />
            ) : (
              <RotateCcw size={15} />
            )}
            Сбросить себе
          </button>
        ) : null}
        {canEdit ? (
          <button
            type="button"
            onClick={() => onOpen(funnel)}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-accent-300/25 bg-accent-300/10 px-3 text-sm font-medium text-accent-50 transition hover:border-accent-300/50"
          >
            <Edit3 size={15} />
            Открыть
          </button>
        ) : null}
        {canEdit ? (
          <button
            type="button"
            onClick={() => onCopy(funnel)}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 text-sm text-gray-200 transition hover:border-white/20"
          >
            <Copy size={15} />
            Копировать
          </button>
        ) : null}
        {canEdit ? (
          <button
            type="button"
            onClick={() => onArchive(funnel)}
            disabled={funnel.status === 'archived'}
            className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-300/15 bg-transparent px-3 text-sm text-red-200 transition hover:border-red-300/35 disabled:cursor-not-allowed disabled:opacity-45"
          >
            <Archive size={15} />
            Архив
          </button>
        ) : null}
      </div>

      {hasPublished ? (
        <div className="mt-3 text-xs text-emerald-200/80">
          {activeVersion
            ? `На боте активна версия v${activeVersion.version_number}`
            : currentVersion
              ? `Актуальная версия: v${currentVersion.version_number}`
              : `Последняя опубликованная: v${publishedVersions[0].version_number}`}
        </div>
      ) : null}
    </article>
  )
}

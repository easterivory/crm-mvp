import { CheckCircle2, Clock3 } from 'lucide-react'
import { useMemo } from 'react'

import type { FunnelVersion } from '../types'
import type { FunnelUser } from '../api'

type VersionHistoryPanelProps = {
  versions: FunnelVersion[]
  users: FunnelUser[]
  activeVersionId: string
  onOpenVersion: (versionId: string) => void
}

function formatVersionDate(version: FunnelVersion) {
  const value = version.published_at ?? version.updated_at ?? version.created_at
  return new Intl.DateTimeFormat(undefined, {
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value))
}

function statusLabel(version: FunnelVersion) {
  if (version.is_active_for_bot) {
    return 'Активна'
  }
  if (version.status === 'published') {
    return 'Опубликована'
  }
  if (version.status === 'archived') {
    return 'Архив'
  }
  return 'Черновик'
}

function authorLabel(version: FunnelVersion, users: Map<string, FunnelUser>) {
  const authorId = version.created_by_id ?? version.created_by_user_id
  if (!authorId) {
    return 'Системное изменение'
  }
  const user = users.get(authorId)
  if (!user) {
    return `Пользователь ${authorId.slice(0, 8)}`
  }
  return user.name ? `${user.name} (${user.email})` : user.email
}

export default function VersionHistoryPanel({
  versions,
  users,
  activeVersionId,
  onOpenVersion,
}: VersionHistoryPanelProps) {
  const usersById = useMemo(
    () => new Map(users.map((user) => [user.id, user])),
    [users],
  )
  const sortedVersions = useMemo(
    () =>
      [...versions].sort((left, right) => {
        const leftTime = new Date(left.published_at ?? left.updated_at ?? left.created_at).getTime()
        const rightTime = new Date(right.published_at ?? right.updated_at ?? right.created_at).getTime()
        return rightTime - leftTime
      }),
    [versions],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-6">
      <div className="mb-4 flex shrink-0 items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-white">История версий</h2>
          <p className="mt-1 text-sm text-gray-500">
            Опубликованные версии неизменяемы. Активную версию выбирают на странице «Воронки».
          </p>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-gray-400">
          {sortedVersions.length} версий
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/5 bg-white/[0.02]">
        <div className="min-w-[760px]">
          <div className="grid grid-cols-[120px_150px_minmax(180px,1fr)_160px_minmax(220px,1.2fr)_180px] gap-3 border-b border-white/5 px-4 py-3 text-xs font-medium uppercase tracking-wide text-gray-500">
            <span>Версия</span>
            <span>Статус</span>
            <span>Автор</span>
            <span>Дата</span>
            <span>Описание</span>
            <span className="text-right">Статус на боте</span>
          </div>

          {sortedVersions.map((version) => {
            const isActiveForBot = version.is_active_for_bot
            const isOpened = version.id === activeVersionId
            return (
              <div
                key={version.id}
                className="grid grid-cols-[120px_150px_minmax(180px,1fr)_160px_minmax(220px,1.2fr)_180px] gap-3 border-b border-white/5 px-4 py-3 text-sm last:border-b-0"
              >
                <button
                  type="button"
                  onClick={() => onOpenVersion(version.id)}
                  className={`inline-flex h-9 items-center justify-center rounded-lg border px-3 font-semibold transition ${
                    isOpened
                      ? 'border-accent-300/35 bg-accent-300/10 text-accent-50'
                      : 'border-white/10 bg-white/[0.03] text-gray-200 hover:border-accent-300/30'
                  }`}
                >
                  v{version.version_number}
                </button>

                <span
                  className={`inline-flex h-9 items-center gap-2 rounded-lg border px-3 ${
                    isActiveForBot
                      ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
                      : version.status === 'draft'
                        ? 'border-amber-300/20 bg-amber-300/10 text-amber-100'
                        : 'border-white/10 bg-white/[0.03] text-gray-300'
                  }`}
                >
                  {isActiveForBot ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}
                  {statusLabel(version)}
                </span>

                <span className="flex min-h-9 items-center truncate text-gray-200">
                  {authorLabel(version, usersById)}
                </span>

                <span className="flex min-h-9 items-center text-gray-400">
                  {formatVersionDate(version)}
                </span>

                <span className="flex min-h-9 items-center text-gray-300">
                  <span className="line-clamp-2">
                    {version.change_log?.trim() || 'Описание изменений не указано'}
                  </span>
                </span>

                <span className="flex min-h-9 items-center justify-end">
                  {isActiveForBot ? (
                    <span className="text-xs text-emerald-200">Текущая активная</span>
                  ) : version.status === 'published' ? (
                    <span className="text-right text-xs text-gray-500">
                      Доступна для выбора
                    </span>
                  ) : (
                    <span className="text-right text-xs text-gray-600">Историческая</span>
                  )}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

import { LoaderCircle, Plus, Workflow } from 'lucide-react'
import { FormEvent, useEffect, useMemo, useState } from 'react'

import type { Bot as BotRecord } from '../../bots'
import { EmptyState } from '../../../shared/ui'
import FunnelCard from './FunnelCard'
import type { Funnel } from '../types'

type FunnelListProps = {
  funnels: Funnel[]
  bots: BotRecord[]
  selectedProjectId: string | null
  selectedBotIds: string[]
  isLoading: boolean
  isCreating: boolean
  onCreate: (payload: { name: string; description: string; botId: string }) => void
  onOpen: (funnel: Funnel) => void
  onCopy: (funnel: Funnel) => void
  onArchive: (funnel: Funnel) => void
  onMakeActive: (funnel: Funnel) => void
}

export default function FunnelList({
  funnels,
  bots,
  selectedProjectId,
  selectedBotIds,
  isLoading,
  isCreating,
  onCreate,
  onOpen,
  onCopy,
  onArchive,
  onMakeActive,
}: FunnelListProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [creatingBotId, setCreatingBotId] = useState('')

  const visibleBots = useMemo(() => {
    if (selectedBotIds.length === 0) {
      return bots
    }
    const selected = new Set(selectedBotIds)
    return bots.filter((bot) => selected.has(bot.id))
  }, [bots, selectedBotIds])

  const funnelsByBot = useMemo(() => {
    const grouped = new Map<string, Funnel[]>()
    for (const funnel of funnels) {
      grouped.set(funnel.bot_id, [...(grouped.get(funnel.bot_id) ?? []), funnel])
    }
    return grouped
  }, [funnels])
  const canCreate = Boolean(
    name.trim() && creatingBotId && visibleBots.some((bot) => bot.id === creatingBotId),
  )

  useEffect(() => {
    if (creatingBotId && !visibleBots.some((bot) => bot.id === creatingBotId)) {
      setCreatingBotId('')
    }
  }, [creatingBotId, visibleBots])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedName = name.trim()
    const normalizedBotId = creatingBotId
    if (!normalizedName || !normalizedBotId) {
      return
    }
    onCreate({
      name: normalizedName,
      description: description.trim(),
      botId: normalizedBotId,
    })
    setName('')
    setDescription('')
  }

  const startCreatingForBot = (targetBotId: string) => {
    setCreatingBotId(targetBotId)
    setName('')
    setDescription('')
  }

  if (!selectedProjectId) {
    return (
      <EmptyState
        icon={<Workflow size={28} />}
        title="Выберите проект"
        description="Воронки загружаются в рамках выбранного проекта."
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-white/8 bg-surface/80 p-4 shadow-card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-white">Воронки</h1>
            <p className="text-sm text-gray-500">
              {selectedBotIds.length === 0
                ? 'Все боты выбранного проекта'
                : `${selectedBotIds.length} выбранных бота`}
            </p>
          </div>
          {isLoading ? <LoaderCircle size={18} className="animate-spin text-gray-500" /> : null}
        </div>

        {visibleBots.length === 0 && !isLoading ? (
          <EmptyState
            icon={<Workflow size={28} />}
            title="Ботов пока нет"
            description="Создайте Telegram-бота, чтобы добавить для него воронку."
          />
        ) : (
          <div className="min-h-0 flex-1 overflow-x-auto pb-2">
            <div className="flex h-full min-w-max gap-4">
              {visibleBots.map((bot) => {
                const botFunnels = funnelsByBot.get(bot.id) ?? []
                const active = botFunnels.find((funnel) => funnel.is_active_for_bot)
                const isCreatingForBot = creatingBotId === bot.id
                return (
                  <section
                    key={bot.id}
                    className="flex h-full w-[380px] shrink-0 flex-col overflow-hidden rounded-xl border border-white/8 bg-background/45"
                  >
                    <header className="shrink-0 border-b border-white/8 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-base font-semibold text-white">{bot.name}</p>
                          <p className="mt-1 truncate text-xs text-gray-500">
                            {bot.bot_username ? `@${bot.bot_username}` : 'username не синхронизирован'}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => startCreatingForBot(bot.id)}
                          className="inline-flex h-9 shrink-0 items-center gap-2 rounded-xl border border-accent-300/25 bg-accent-300/10 px-3 text-sm font-medium text-accent-50 transition hover:border-accent-300/50"
                        >
                          <Plus size={15} />
                          Создать
                        </button>
                      </div>
                      <p className="mt-3 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-xs text-gray-400">
                        {active ? `Активная: ${active.name}` : 'Активная воронка не назначена'}
                      </p>
                    </header>

                    <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
                      {isCreatingForBot ? (
                        <form
                          onSubmit={handleSubmit}
                          className="space-y-3 rounded-xl border border-accent-300/20 bg-accent-300/5 p-3"
                        >
                          <input
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            placeholder="Название воронки"
                            className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                          />
                          <textarea
                            value={description}
                            onChange={(event) => setDescription(event.target.value)}
                            rows={2}
                            placeholder="Описание"
                            className="w-full resize-none rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                          />
                          <div className="flex gap-2">
                            <button
                              type="submit"
                              disabled={!canCreate || isCreating}
                              className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-3 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {isCreating ? <LoaderCircle size={15} className="animate-spin" /> : <Plus size={15} />}
                              Создать
                            </button>
                            <button
                              type="button"
                              onClick={() => setCreatingBotId('')}
                              className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-300 transition hover:border-white/20"
                            >
                              Отмена
                            </button>
                          </div>
                        </form>
                      ) : null}

                      {botFunnels.length === 0 ? (
                        <div className="rounded-xl border border-dashed border-white/10 p-5 text-center">
                          <p className="text-sm text-gray-400">У этого бота пока нет воронок</p>
                          <button
                            type="button"
                            onClick={() => startCreatingForBot(bot.id)}
                            className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl border border-accent-300/25 px-3 text-sm text-accent-100 transition hover:border-accent-300/50"
                          >
                            <Plus size={15} />
                            Создать воронку
                          </button>
                        </div>
                      ) : (
                        botFunnels.map((funnel) => (
                          <FunnelCard
                            key={funnel.id}
                            funnel={funnel}
                            bot={bot}
                            onOpen={onOpen}
                            onCopy={onCopy}
                            onArchive={onArchive}
                            onMakeActive={onMakeActive}
                          />
                        ))
                      )}
                    </div>
                  </section>
                )
              })}
            </div>
          </div>
        )}
    </div>
  )
}

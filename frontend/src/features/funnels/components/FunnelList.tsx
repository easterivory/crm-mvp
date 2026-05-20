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
}: FunnelListProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [botId, setBotId] = useState('')

  const visibleBots = useMemo(() => {
    if (selectedBotIds.length === 0) {
      return bots
    }
    const selected = new Set(selectedBotIds)
    return bots.filter((bot) => selected.has(bot.id))
  }, [bots, selectedBotIds])

  const botById = useMemo(() => new Map(bots.map((bot) => [bot.id, bot])), [bots])
  const canUseCurrentBot = Boolean(botId && visibleBots.some((bot) => bot.id === botId))
  const needsExplicitBotChoice = selectedBotIds.length !== 1
  const canCreate = Boolean(name.trim() && visibleBots.length > 0 && canUseCurrentBot)

  useEffect(() => {
    if (selectedBotIds.length === 1 && visibleBots[0]) {
      setBotId(visibleBots[0].id)
      return
    }
    if (botId && !visibleBots.some((bot) => bot.id === botId)) {
      setBotId('')
    }
  }, [botId, selectedBotIds.length, visibleBots])

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedName = name.trim()
    const normalizedBotId = botId
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
    <div className="grid h-full min-h-0 gap-4 overflow-y-auto lg:grid-cols-[minmax(280px,340px)_minmax(0,1fr)] lg:overflow-hidden">
      <form
        onSubmit={handleSubmit}
        className="h-fit rounded-lg border border-white/8 bg-surface/90 p-4 shadow-card"
      >
        <h2 className="text-base font-semibold text-white">Новая воронка</h2>
        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
              Название
            </span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Например, первичная квалификация"
              className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
              Бот
            </span>
            <select
              value={botId}
              onChange={(event) => setBotId(event.target.value)}
              className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
            >
              <option value="">Выберите бота</option>
              {visibleBots.map((bot) => (
                <option key={bot.id} value={bot.id}>
                  {bot.name}
                </option>
              ))}
            </select>
          </label>
          {needsExplicitBotChoice && !canUseCurrentBot ? (
            <p className="text-xs text-amber-200">
              Выберите конкретного бота для новой воронки.
            </p>
          ) : null}
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
              Описание
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              placeholder="Коротко о назначении сценария"
              className="w-full resize-none rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
            />
          </label>
          <button
            type="submit"
            disabled={!canCreate || isCreating}
            className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isCreating ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
            Создать черновик
          </button>
        </div>
      </form>

      <div className="min-h-0 overflow-y-auto rounded-lg border border-white/8 bg-surface/80 p-4 shadow-card">
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

        {funnels.length === 0 && !isLoading ? (
          <EmptyState
            icon={<Workflow size={28} />}
            title="Воронок пока нет"
            description="Создайте черновик для выбранного бота и откройте визуальный редактор."
          />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {funnels.map((funnel) => (
              <FunnelCard
                key={funnel.id}
                funnel={funnel}
                bot={botById.get(funnel.bot_id)}
                onOpen={onOpen}
                onCopy={onCopy}
                onArchive={onArchive}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

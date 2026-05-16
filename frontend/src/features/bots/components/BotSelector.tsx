import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ChevronDown, LoaderCircle } from 'lucide-react'

import { useProjectBotSelection } from '../../../shared/lib'
import { fetchBots } from '../api'
import type { Bot } from '../types'

export default function BotSelector() {
  const {
    selectedProjectId,
    selectedBotIds,
    setSelectedBotIds,
    resetBotSelection,
  } = useProjectBotSelection()
  const [bots, setBots] = useState<Bot[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [loadedProjectId, setLoadedProjectId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  const selectedBots = useMemo(
    () => bots.filter((bot) => selectedBotIds.includes(bot.id)),
    [bots, selectedBotIds],
  )

  const label = useMemo(() => {
    if (!selectedProjectId) {
      return 'Select project'
    }
    if (isLoading) {
      return 'Loading bots'
    }
    if (error) {
      return 'Bots unavailable'
    }
    if (bots.length === 0) {
      return 'No bots'
    }
    if (selectedBotIds.length === 0) {
      return 'All bots'
    }
    if (selectedBots.length === 1) {
      return selectedBots[0].name
    }
    return `${selectedBots.length} bots`
  }, [bots.length, error, isLoading, selectedBotIds.length, selectedBots, selectedProjectId])

  const loadBots = useCallback(async () => {
    if (!selectedProjectId) {
      setBots([])
      setLoadedProjectId(null)
      resetBotSelection()
      return
    }

    setIsLoading(true)
    setLoadedProjectId(null)
    setError(null)

    try {
      const items = await fetchBots(selectedProjectId)
      setBots(items)
      setLoadedProjectId(selectedProjectId)
    } catch {
      setError('Bots unavailable')
      setBots([])
      setLoadedProjectId(null)
    } finally {
      setIsLoading(false)
    }
  }, [resetBotSelection, selectedProjectId])

  useEffect(() => {
    loadBots().catch(() => undefined)
  }, [loadBots])

  useEffect(() => {
    if (isLoading || loadedProjectId !== selectedProjectId) {
      return
    }

    const botIds = new Set(bots.map((bot) => bot.id))
    const validSelection = selectedBotIds.filter((botId) => botIds.has(botId))

    if (validSelection.length !== selectedBotIds.length) {
      setSelectedBotIds(validSelection)
    }
  }, [bots, isLoading, loadedProjectId, selectedBotIds, selectedProjectId, setSelectedBotIds])

  const toggleBot = (botId: string) => {
    if (selectedBotIds.includes(botId)) {
      setSelectedBotIds(selectedBotIds.filter((selectedBotId) => selectedBotId !== botId))
      return
    }

    setSelectedBotIds([...selectedBotIds, botId])
  }

  const isDisabled = !selectedProjectId || isLoading || Boolean(error) || bots.length === 0

  return (
    <div className="relative min-w-0">
      <span className="block text-[10px] font-semibold uppercase tracking-[0.2em] text-gray-500">
        Bots
      </span>
      <button
        type="button"
        disabled={!selectedProjectId || Boolean(error)}
        onClick={() => setIsOpen((value) => !value)}
        className="mt-1 flex h-10 w-full min-w-[190px] items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-left text-sm font-medium text-gray-100 outline-none transition hover:border-accent-300/40 focus:border-accent-300/60 focus:shadow-glow-accent disabled:cursor-not-allowed disabled:text-gray-500"
        title={label}
      >
        <span className="truncate">{label}</span>
        {isLoading ? (
          <LoaderCircle size={16} className="shrink-0 animate-spin text-gray-500" />
        ) : (
          <ChevronDown size={16} className="shrink-0 text-gray-500" />
        )}
      </button>

      {isOpen ? (
        <div className="absolute right-0 z-50 mt-2 w-72 overflow-hidden rounded-xl border border-white/10 bg-[#0B0F19]/95 p-2 shadow-card backdrop-blur-xl">
          <button
            type="button"
            disabled={isDisabled}
            onClick={() => {
              resetBotSelection()
              setIsOpen(false)
            }}
            className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-gray-200 transition hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:text-gray-600"
          >
            <span>All bots in project</span>
            {selectedBotIds.length === 0 ? <Check size={16} className="text-accent-300" /> : null}
          </button>

          <div className="mt-1 max-h-64 overflow-y-auto">
            {bots.map((bot) => {
              const isSelected = selectedBotIds.includes(bot.id)

              return (
                <button
                  key={bot.id}
                  type="button"
                  onClick={() => toggleBot(bot.id)}
                  className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm text-gray-200 transition hover:bg-white/[0.06]"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-gray-100">
                      {bot.name}
                    </span>
                    {bot.bot_username ? (
                      <span className="block truncate text-xs text-gray-500">
                        @{bot.bot_username}
                      </span>
                    ) : null}
                  </span>
                  {isSelected ? <Check size={16} className="shrink-0 text-accent-300" /> : null}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

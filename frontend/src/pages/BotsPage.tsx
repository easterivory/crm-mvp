import {
  Bot as BotIcon,
  Check,
  Copy,
  Link as LinkIcon,
  LoaderCircle,
  Pencil,
  PlugZap,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import api from '../api/client'

type PaginatedResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type BotRecord = {
  id: string
  project_id: string
  name: string
  has_telegram_token: boolean
  bot_username: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
}

type BotStep = {
  id: string
  bot_version_id: string
  step_type: string
  config: Record<string, unknown>
  next_step_id: string | null
  fallback_step_id: string | null
  created_at: string
  updated_at: string
}

type TrackingLink = {
  id: string
  project_id: string
  bot_id: string
  name: string
  ref_code: string
  cost_model: 'fix_pdp' | 'cpm' | 'cpa'
  price_per_unit: string
  spend: string
  target_step_id: string | null
  tracking_url: string
  created_at: string
}

function getErrorMessage(err: unknown, fallback = 'Request failed.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Cannot reach API.'
    }
  }

  return fallback
}

function getStepLabel(step: BotStep) {
  const text =
    typeof step.config.text === 'string'
      ? step.config.text
      : typeof step.config.variable_name === 'string'
        ? step.config.variable_name
        : ''
  const shortText = text.length > 32 ? `${text.slice(0, 32)}...` : text
  return shortText ? `${step.step_type} · ${shortText}` : step.step_type
}

export default function BotsPage() {
  const [bots, setBots] = useState<BotRecord[]>([])
  const [trackingLinks, setTrackingLinks] = useState<TrackingLink[]>([])
  const [steps, setSteps] = useState<BotStep[]>([])
  const [selectedBotId, setSelectedBotId] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isAddingBot, setIsAddingBot] = useState(false)
  const [isCreatingLink, setIsCreatingLink] = useState(false)
  const [webhookBotId, setWebhookBotId] = useState<string | null>(null)
  const [deletingBotId, setDeletingBotId] = useState<string | null>(null)
  const [deletingLinkId, setDeletingLinkId] = useState<string | null>(null)
  const [editingBotId, setEditingBotId] = useState<string | null>(null)
  const [editingBotName, setEditingBotName] = useState('')
  const [editingBotUsername, setEditingBotUsername] = useState('')
  const [editingBotToken, setEditingBotToken] = useState('')
  const [savingBotId, setSavingBotId] = useState<string | null>(null)

  const [botName, setBotName] = useState('')
  const [botToken, setBotToken] = useState('')
  const [botUsername, setBotUsername] = useState('')
  const [linkName, setLinkName] = useState('')
  const [targetStepId, setTargetStepId] = useState('')

  const selectedBot = useMemo(
    () => bots.find((bot) => bot.id === selectedBotId) ?? null,
    [bots, selectedBotId],
  )

  const botNameById = useMemo(() => {
    return new Map(bots.map((bot) => [bot.id, bot.name]))
  }, [bots])

  const loadBots = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<BotRecord>>('/bots', {
      params: { limit: 100, offset: 0 },
    })
    setBots(data.items)
    setSelectedBotId((current) => {
      if (current && data.items.some((bot) => bot.id === current)) {
        return current
      }
      return data.items[0]?.id ?? ''
    })
  }, [])

  const loadTrackingLinks = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<TrackingLink>>(
      '/tracking-links',
      { params: { limit: 100, offset: 0 } },
    )
    setTrackingLinks(data.items)
  }, [])

  const loadSteps = useCallback(async (botId: string) => {
    if (!botId) {
      setSteps([])
      return
    }

    const { data } = await api.get<BotStep[]>('/bot_steps', {
      params: { bot_id: botId },
    })
    setSteps(data)
  }, [])

  const loadAll = useCallback(async () => {
    setIsLoading(true)
    setError('')

    try {
      await Promise.all([loadBots(), loadTrackingLinks()])
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load bots.'))
    } finally {
      setIsLoading(false)
    }
  }, [loadBots, loadTrackingLinks])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  useEffect(() => {
    setTargetStepId('')
    void loadSteps(selectedBotId).catch((err) => {
      setError(getErrorMessage(err, 'Could not load bot steps.'))
    })
  }, [loadSteps, selectedBotId])

  const handleAddBot = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isAddingBot) {
      return
    }

    setIsAddingBot(true)
    setError('')
    setNotice('')

    try {
      const { data } = await api.post<BotRecord>('/bots', {
        name: botName.trim() || undefined,
        telegram_token: botToken.trim(),
        bot_username: botUsername.trim() || undefined,
      })
      setBotName('')
      setBotToken('')
      setBotUsername('')
      await loadBots()
      setSelectedBotId(data.id)
      setNotice('Bot added and webhook registered.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add bot.'))
    } finally {
      setIsAddingBot(false)
    }
  }

  const handleSetWebhook = async (botId: string) => {
    setWebhookBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.post(`/bots/${botId}/webhook`)
      await loadBots()
      setNotice('Webhook registered.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not set webhook.'))
    } finally {
      setWebhookBotId(null)
    }
  }

  const startEditBot = (bot: BotRecord) => {
    setEditingBotId(bot.id)
    setEditingBotName(bot.name)
    setEditingBotUsername(bot.bot_username ? `@${bot.bot_username}` : '')
    setEditingBotToken('')
  }

  const cancelEditBot = () => {
    setEditingBotId(null)
    setEditingBotName('')
    setEditingBotUsername('')
    setEditingBotToken('')
  }

  const handleSaveBot = async (botId: string) => {
    if (savingBotId) {
      return
    }

    const payload: {
      name: string
      bot_username: string | null
      telegram_token?: string
    } = {
      name: editingBotName.trim(),
      bot_username: editingBotUsername.trim() || null,
    }
    if (editingBotToken.trim()) {
      payload.telegram_token = editingBotToken.trim()
    }

    setSavingBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.patch<BotRecord>(`/bots/${botId}`, payload)
      cancelEditBot()
      await loadBots()
      setNotice(
        payload.telegram_token
          ? 'Bot updated and webhook registered.'
          : 'Bot updated.',
      )
    } catch (err) {
      setError(getErrorMessage(err, 'Could not update bot.'))
    } finally {
      setSavingBotId(null)
    }
  }

  const handleDeleteBot = async (botId: string) => {
    if (!window.confirm('Delete this bot?')) {
      return
    }

    setDeletingBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/bots/${botId}`)
      await Promise.all([loadBots(), loadTrackingLinks()])
      setNotice('Bot deleted.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete bot.'))
    } finally {
      setDeletingBotId(null)
    }
  }

  const handleCreateLink = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedBotId || isCreatingLink) {
      return
    }

    setIsCreatingLink(true)
    setError('')
    setNotice('')

    try {
      await api.post<TrackingLink>('/tracking-links', {
        bot_id: selectedBotId,
        name: linkName.trim(),
        target_step_id: targetStepId || null,
      })
      setLinkName('')
      setTargetStepId('')
      await loadTrackingLinks()
      setNotice('Tracking link generated.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not create tracking link.'))
    } finally {
      setIsCreatingLink(false)
    }
  }

  const handleCopy = async (url: string) => {
    await navigator.clipboard.writeText(url)
    setNotice('Copied.')
  }

  const handleDeleteLink = async (linkId: string) => {
    setDeletingLinkId(linkId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/tracking-links/${linkId}`)
      await loadTrackingLinks()
      setNotice('Tracking link deleted.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete tracking link.'))
    } finally {
      setDeletingLinkId(null)
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl">
      <header className="flex shrink-0 items-center justify-between border-b border-zinc-800 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-300">
            <BotIcon size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Bots & Traffic</h1>
            <p className="text-xs text-zinc-500">Telegram sources</p>
          </div>
        </div>
        <button
          type="button"
          title="Refresh"
          onClick={() => void loadAll()}
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 text-zinc-300 transition hover:border-cyan-500/60 hover:text-cyan-200"
        >
          <RefreshCw size={16} />
        </button>
      </header>

      {error ? (
        <div className="border-b border-red-900/70 bg-red-950/40 px-5 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="border-b border-cyan-900/70 bg-cyan-950/40 px-5 py-3 text-sm text-cyan-100">
          {notice}
        </div>
      ) : null}

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center text-sm text-zinc-500">
          <LoaderCircle size={18} className="mr-2 animate-spin" />
          Loading bots
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 divide-y divide-zinc-800 overflow-y-auto lg:grid-cols-[minmax(320px,380px)_minmax(0,1fr)] lg:divide-x lg:divide-y-0 lg:overflow-hidden">
          <div className="min-h-0 p-5 lg:overflow-y-auto">
            <div className="mb-5 flex items-center gap-2">
              <BotIcon size={18} className="text-cyan-300" />
              <h2 className="text-base font-semibold text-zinc-100">Bots</h2>
            </div>

            <form className="mb-5 grid gap-3" onSubmit={handleAddBot}>
              <input
                value={botName}
                onChange={(event) => setBotName(event.target.value)}
                placeholder="Bot name"
                maxLength={255}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <input
                value={botToken}
                onChange={(event) => setBotToken(event.target.value)}
                placeholder="Telegram token"
                type="password"
                required
                maxLength={255}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <div className="flex gap-3">
                <input
                  value={botUsername}
                  onChange={(event) => setBotUsername(event.target.value)}
                  placeholder="@username"
                  maxLength={255}
                  className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
                <button
                  type="submit"
                  title="Add bot"
                  disabled={isAddingBot}
                  className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-400 text-zinc-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isAddingBot ? (
                    <LoaderCircle size={17} className="animate-spin" />
                  ) : (
                    <Plus size={17} />
                  )}
                </button>
              </div>
            </form>

            <div className="space-y-2">
              {bots.length === 0 ? (
                <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-5 text-sm text-zinc-500">
                  No bots yet.
                </div>
              ) : null}

              {bots.map((bot) => {
                const isEditing = editingBotId === bot.id

                return (
                  <div
                    key={bot.id}
                    className={`rounded-lg border px-4 py-3 transition ${
                      selectedBotId === bot.id
                        ? 'border-cyan-500/60 bg-cyan-500/10'
                        : 'border-zinc-800 bg-zinc-900/40'
                    }`}
                  >
                    {isEditing ? (
                      <div className="mb-3 grid gap-2">
                        <input
                          value={editingBotName}
                          onChange={(event) => setEditingBotName(event.target.value)}
                          maxLength={255}
                          autoFocus
                          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition focus:ring-2"
                        />
                        <input
                          value={editingBotUsername}
                          onChange={(event) => setEditingBotUsername(event.target.value)}
                          maxLength={255}
                          placeholder="@username"
                          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2"
                        />
                        <input
                          value={editingBotToken}
                          onChange={(event) => setEditingBotToken(event.target.value)}
                          maxLength={255}
                          type="password"
                          placeholder="New token (optional)"
                          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2"
                        />
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setSelectedBotId(bot.id)}
                        className="mb-3 block w-full min-w-0 text-left"
                      >
                        <p className="truncate text-sm font-semibold text-zinc-100">
                          {bot.name}
                        </p>
                        <p className="truncate text-xs text-zinc-500">
                          {bot.bot_username ? `@${bot.bot_username}` : 'username missing'}
                        </p>
                      </button>
                    )}
                    <div className="flex items-center gap-2">
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            title="Save bot"
                            onClick={() => void handleSaveBot(bot.id)}
                            disabled={savingBotId === bot.id || !editingBotName.trim()}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700 text-cyan-200 transition hover:border-cyan-500/60 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {savingBotId === bot.id ? (
                              <LoaderCircle size={16} className="animate-spin" />
                            ) : (
                              <Check size={16} />
                            )}
                          </button>
                          <button
                            type="button"
                            title="Cancel"
                            onClick={cancelEditBot}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700 text-zinc-400 transition hover:border-zinc-500 hover:text-zinc-200"
                          >
                            <X size={16} />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            title="Set webhook"
                            onClick={() => void handleSetWebhook(bot.id)}
                            disabled={webhookBotId === bot.id}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700 text-zinc-300 transition hover:border-cyan-500/60 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {webhookBotId === bot.id ? (
                              <LoaderCircle size={16} className="animate-spin" />
                            ) : (
                              <PlugZap size={16} />
                            )}
                          </button>
                          <button
                            type="button"
                            title="Edit bot"
                            onClick={() => startEditBot(bot)}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700 text-zinc-400 transition hover:border-cyan-500/60 hover:text-cyan-200"
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            type="button"
                            title="Delete bot"
                            onClick={() => void handleDeleteBot(bot.id)}
                            disabled={deletingBotId === bot.id}
                            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-700 text-zinc-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {deletingBotId === bot.id ? (
                              <LoaderCircle size={16} className="animate-spin" />
                            ) : (
                              <Trash2 size={16} />
                            )}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="min-h-0 p-5 lg:overflow-y-auto">
            <div className="mb-5 flex items-center gap-2">
              <LinkIcon size={18} className="text-cyan-300" />
              <h2 className="text-base font-semibold text-zinc-100">
                Tracking links
              </h2>
            </div>

            <form
              className="mb-5 grid gap-3 xl:grid-cols-[minmax(180px,0.9fr)_minmax(220px,1fr)_minmax(220px,1fr)_auto]"
              onSubmit={handleCreateLink}
            >
              <select
                value={selectedBotId}
                onChange={(event) => setSelectedBotId(event.target.value)}
                required
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition focus:ring-2"
              >
                <option value="" disabled>
                  Select bot
                </option>
                {bots.map((bot) => (
                  <option key={bot.id} value={bot.id}>
                    {bot.name}
                  </option>
                ))}
              </select>
              <input
                value={linkName}
                onChange={(event) => setLinkName(event.target.value)}
                placeholder="Таргет Инста"
                required
                maxLength={255}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <select
                value={targetStepId}
                onChange={(event) => setTargetStepId(event.target.value)}
                className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-500 transition focus:ring-2"
              >
                <option value="">Default start step</option>
                {steps.map((step) => (
                  <option key={step.id} value={step.id}>
                    {getStepLabel(step)}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                title="Generate link"
                disabled={!selectedBot || isCreatingLink}
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-400 text-zinc-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreatingLink ? (
                  <LoaderCircle size={17} className="animate-spin" />
                ) : (
                  <Plus size={17} />
                )}
              </button>
            </form>

            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-[860px] w-full table-fixed text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="w-[22%] px-4 py-3">Name</th>
                    <th className="w-[20%] px-4 py-3">Bot</th>
                    <th className="w-[18%] px-4 py-3">Ref</th>
                    <th className="px-4 py-3">Link</th>
                    <th className="w-[104px] px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {trackingLinks.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="bg-zinc-950 px-4 py-8 text-center text-zinc-500">
                        No tracking links yet.
                      </td>
                    </tr>
                  ) : null}

                  {trackingLinks.map((link) => (
                    <tr key={link.id} className="bg-zinc-950">
                      <td className="truncate px-4 py-3 font-medium text-zinc-100">
                        {link.name}
                      </td>
                      <td className="truncate px-4 py-3 text-zinc-400">
                        {botNameById.get(link.bot_id) ?? link.bot_id.slice(0, 8)}
                      </td>
                      <td className="truncate px-4 py-3 font-mono text-xs text-cyan-200">
                        {link.ref_code}
                      </td>
                      <td className="truncate px-4 py-3 text-zinc-400" title={link.tracking_url}>
                        {link.tracking_url}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            title="Copy link"
                            onClick={() => void handleCopy(link.tracking_url)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-300 transition hover:border-cyan-500/60 hover:text-cyan-200"
                          >
                            <Copy size={15} />
                          </button>
                          <button
                            type="button"
                            title="Delete link"
                            onClick={() => void handleDeleteLink(link.id)}
                            disabled={deletingLinkId === link.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {deletingLinkId === link.id ? (
                              <LoaderCircle size={15} className="animate-spin" />
                            ) : (
                              <Trash2 size={15} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

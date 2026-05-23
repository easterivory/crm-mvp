import {
  Bot as BotIcon,
  Check,
  LoaderCircle,
  Pencil,
  PlugZap,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
import type { PaginatedResponse } from '../shared/types'
import { useAuthStore } from '../store/authStore'

type BotRecord = {
  id: string
  project_id: string
  name: string
  has_telegram_token: boolean
  telegram_bot_id: number | null
  telegram_first_name: string | null
  bot_username: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
}

function getErrorMessage(err: unknown, fallback = 'Запрос не выполнен.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.response?.status === 403) {
      return 'Недостаточно прав для этого действия.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }

  return fallback
}

export default function BotsPage() {
  const navigate = useNavigate()
  const currentUser = useAuthStore((state) => state.user)
  const { selectedProjectId } = useProjectBotSelection()
  const activeProjectId = selectedProjectId ?? currentUser?.project_id ?? null

  const [bots, setBots] = useState<BotRecord[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isAddingBot, setIsAddingBot] = useState(false)
  const [webhookBotId, setWebhookBotId] = useState<string | null>(null)
  const [deletingBotId, setDeletingBotId] = useState<string | null>(null)
  const [editingBotId, setEditingBotId] = useState<string | null>(null)
  const [editingBotName, setEditingBotName] = useState('')
  const [editingBotToken, setEditingBotToken] = useState('')
  const [savingBotId, setSavingBotId] = useState<string | null>(null)
  const [syncingBotId, setSyncingBotId] = useState<string | null>(null)

  const [botName, setBotName] = useState('')
  const [botToken, setBotToken] = useState('')

  const loadBots = useCallback(async () => {
    if (!activeProjectId) {
      setBots([])
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    setError('')

    try {
      const { data } = await api.get<PaginatedResponse<BotRecord>>('/bots', {
        params: { limit: 100, offset: 0, project_id: activeProjectId },
      })
      setBots(data.items)
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось загрузить ботов.'))
    } finally {
      setIsLoading(false)
    }
  }, [activeProjectId])

  useEffect(() => {
    void loadBots()
  }, [loadBots])

  const handleAddBot = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!activeProjectId) {
      setError('Выберите проект перед добавлением бота.')
      return
    }
    if (isAddingBot) {
      return
    }

    setIsAddingBot(true)
    setError('')
    setNotice('')

    try {
      await api.post<BotRecord>('/bots', {
        name: botName.trim() || undefined,
        telegram_token: botToken.trim(),
      }, {
        params: { project_id: activeProjectId },
      })
      setBotName('')
      setBotToken('')
      await loadBots()
      setNotice('Бот добавлен: имя подтянуто из Telegram, webhook зарегистрирован.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось добавить бота.'))
    } finally {
      setIsAddingBot(false)
    }
  }

  const handleSetWebhook = async (botId: string) => {
    setWebhookBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.post(`/bots/${botId}/webhook`, null, {
        params: activeProjectId ? { project_id: activeProjectId } : undefined,
      })
      await loadBots()
      setNotice('Webhook зарегистрирован, identity обновлена из Telegram.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось зарегистрировать webhook.'))
    } finally {
      setWebhookBotId(null)
    }
  }

  const handleSyncBot = async (botId: string) => {
    setSyncingBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.post(`/bots/${botId}/sync-telegram-identity`, null, {
        params: activeProjectId ? { project_id: activeProjectId } : undefined,
      })
      await loadBots()
      setNotice('Данные бота синхронизированы с Telegram.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось синхронизировать бота.'))
    } finally {
      setSyncingBotId(null)
    }
  }

  const startEditBot = (bot: BotRecord) => {
    setEditingBotId(bot.id)
    setEditingBotName(bot.name)
    setEditingBotToken('')
  }

  const cancelEditBot = () => {
    setEditingBotId(null)
    setEditingBotName('')
    setEditingBotToken('')
  }

  const handleSaveBot = async (botId: string) => {
    if (savingBotId) {
      return
    }

    setSavingBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.patch<BotRecord>(`/bots/${botId}`, {
        name: editingBotName.trim(),
        ...(editingBotToken.trim() ? { telegram_token: editingBotToken.trim() } : {}),
      }, {
        params: activeProjectId ? { project_id: activeProjectId } : undefined,
      })
      cancelEditBot()
      await loadBots()
      setNotice('Бот обновлён. Если token менялся, identity и webhook пересинхронизированы.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось обновить бота.'))
    } finally {
      setSavingBotId(null)
    }
  }

  const handleDeleteBot = async (botId: string) => {
    if (!window.confirm('Архивировать этого бота?')) {
      return
    }

    setDeletingBotId(botId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/bots/${botId}`, {
        params: activeProjectId ? { project_id: activeProjectId } : undefined,
      })
      await loadBots()
      setNotice('Бот архивирован.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось архивировать бота.'))
    } finally {
      setDeletingBotId(null)
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0B0F19]/80 text-gray-200 shadow-card">
      <header className="shrink-0 border-b border-white/5 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-cyan-500/15 text-cyan-300">
              <BotIcon size={18} />
            </div>
            <div className="min-w-0">
              <h1 className="text-xl font-semibold text-white">Боты</h1>
              <p className="text-sm text-gray-500">Управление Telegram-ботами проекта</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => navigate('/tracking')}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-accent-300/30 bg-accent-500/10 px-4 text-sm font-semibold text-accent-100 transition hover:border-accent-300/60"
            >
              Перейти в Трекинг
            </button>
            <button
              type="button"
              title="Обновить"
              onClick={() => void loadBots()}
              className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 hover:text-white"
            >
              {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            </button>
          </div>
        </div>
      </header>

      {error ? (
        <div className="border-b border-red-400/20 bg-red-500/10 px-5 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="border-b border-accent-400/20 bg-accent-500/10 px-5 py-3 text-sm text-accent-100">
          {notice}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
        <form className="mb-5 grid gap-3 rounded-xl border border-white/5 bg-surface p-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_auto]" onSubmit={handleAddBot}>
          <input
            value={botName}
            onChange={(event) => setBotName(event.target.value)}
            placeholder="Название бота"
            maxLength={255}
            className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
          />
          <input
            value={botToken}
            onChange={(event) => setBotToken(event.target.value)}
            placeholder="Telegram token"
            type="password"
            required
            maxLength={255}
            className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
          />
          <button
            type="submit"
            disabled={isAddingBot}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isAddingBot ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
            Добавить
          </button>
        </form>

        <div className="grid gap-4 xl:grid-cols-2">
          {isLoading ? (
            <div className="rounded-xl border border-white/5 bg-surface px-4 py-12 text-center text-sm text-gray-500 xl:col-span-2">
              <LoaderCircle size={18} className="mr-2 inline animate-spin" />
              Загрузка ботов
            </div>
          ) : null}

          {!isLoading && bots.length === 0 ? (
            <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-4 py-12 text-center text-sm text-gray-500 xl:col-span-2">
              Ботов пока нет.
            </div>
          ) : null}

          {bots.map((bot) => {
            const isEditing = editingBotId === bot.id

            return (
              <article key={bot.id} className="rounded-xl border border-white/5 bg-surface p-4 shadow-card">
                {isEditing ? (
                  <div className="grid gap-3">
                    <input
                      value={editingBotName}
                      onChange={(event) => setEditingBotName(event.target.value)}
                      maxLength={255}
                      autoFocus
                      className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
                    />
                    <div className="rounded-xl border border-white/10 bg-background/50 px-3 py-2 text-sm text-gray-400">
                      Username обновляется только через Telegram getMe.
                    </div>
                    <input
                      value={editingBotToken}
                      onChange={(event) => setEditingBotToken(event.target.value)}
                      maxLength={255}
                      type="password"
                      placeholder="Новый token, необязательно"
                      className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                    />
                  </div>
                ) : (
                  <div className="min-w-0">
                    <h2 className="truncate text-lg font-semibold text-white">{bot.name}</h2>
                    <p className="truncate text-sm text-gray-500">
                      {bot.bot_username ? `@${bot.bot_username}` : 'username не указан'}
                    </p>
                    {bot.telegram_first_name || bot.telegram_bot_id ? (
                      <p className="mt-1 truncate text-xs text-gray-500">
                        Telegram: {[bot.telegram_first_name, bot.telegram_bot_id ? `ID ${bot.telegram_bot_id}` : null].filter(Boolean).join(' · ')}
                      </p>
                    ) : null}
                    <p className="mt-2 text-xs text-gray-500">
                      Token: {bot.has_telegram_token ? 'добавлен' : 'не добавлен'}
                    </p>
                  </div>
                )}

                <div className="mt-4 flex flex-wrap gap-2">
                  {isEditing ? (
                    <>
                      <button
                        type="button"
                        title="Сохранить"
                        onClick={() => void handleSaveBot(bot.id)}
                        disabled={savingBotId === bot.id || !editingBotName.trim()}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-cyan-100 transition hover:border-cyan-300/60 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {savingBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <Check size={15} />}
                        Сохранить
                      </button>
                      <button
                        type="button"
                        title="Отмена"
                        onClick={cancelEditBot}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-white/20"
                      >
                        <X size={15} />
                        Отмена
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        title="Зарегистрировать webhook"
                        onClick={() => void handleSetWebhook(bot.id)}
                        disabled={webhookBotId === bot.id}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {webhookBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <PlugZap size={15} />}
                        Webhook
                      </button>
                      <button
                        type="button"
                        title="Синхронизировать с Telegram"
                        onClick={() => void handleSyncBot(bot.id)}
                        disabled={syncingBotId === bot.id}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {syncingBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                        Синхронизировать
                      </button>
                      <button
                        type="button"
                        title="Редактировать"
                        onClick={() => startEditBot(bot)}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50"
                      >
                        <Pencil size={15} />
                        Изменить
                      </button>
                      <button
                        type="button"
                        title="Архивировать"
                        onClick={() => void handleDeleteBot(bot.id)}
                        disabled={deletingBotId === bot.id}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-red-400/25 bg-red-500/10 px-3 text-sm text-red-100 transition hover:border-red-300/60 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {deletingBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <Trash2 size={15} />}
                        Архивировать
                      </button>
                    </>
                  )}
                </div>
              </article>
            )
          })}
        </div>

        <div className="mt-5 rounded-xl border border-accent-300/20 bg-accent-500/10 p-4 text-sm text-accent-100">
          Tracking links создаются только в разделе «Трекинг» через кнопку «Создать ссылку».
        </div>
      </div>
    </section>
  )
}

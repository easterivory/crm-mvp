import {
  Bot as BotIcon,
  Check,
  Download,
  ImagePlus,
  Import as ImportIcon,
  LoaderCircle,
  Pencil,
  PlugZap,
  Plus,
  RefreshCw,
  Trash2,
  UserRound,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

import api from '../api/client'
import {
  downloadBotAuditLogs,
  updateBot,
  uploadBotAvatar,
  type Bot as BotRecord,
} from '../features/bots'
import LeadImportModal from '../features/bots/components/LeadImportModal'
import TelegramAccountConnectionPanel from '../features/bots/components/TelegramAccountConnectionPanel'
import { useProjectBotSelection } from '../shared/lib'
import type { PaginatedResponse } from '../shared/types'
import { useAuthStore } from '../store/authStore'

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

function normalizeOptionalText(value: string) {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

function normalizeTelegramToken(value: string) {
  return value
    .normalize('NFKC')
    .replace(/[\s\u200B-\u200D\u2060\uFEFF]/g, '')
    .replace(/^bot(?=\d+:)/i, '')
}

function BotDescriptionRow({ label, value }: { label: string; value: string | null }) {
  if (!value) {
    return null
  }

  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] px-3 py-2">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-600">{label}</div>
      <p className="line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-gray-300">{value}</p>
    </div>
  )
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
  const [editingCrmDescription, setEditingCrmDescription] = useState('')
  const [editingTelegramAbout, setEditingTelegramAbout] = useState('')
  const [editingTelegramDescription, setEditingTelegramDescription] = useState('')
  const [savingBotId, setSavingBotId] = useState<string | null>(null)
  const [syncingBotId, setSyncingBotId] = useState<string | null>(null)
  const [avatarUploadingBotId, setAvatarUploadingBotId] = useState<string | null>(null)
  const [auditExportingBotId, setAuditExportingBotId] = useState<string | null>(null)
  const [leadImportBot, setLeadImportBot] = useState<BotRecord | null>(null)

  const [botName, setBotName] = useState('')
  const [botToken, setBotToken] = useState('')
  const [transportType, setTransportType] = useState<'bot_api' | 'user_mtproto'>('bot_api')
  const canImportLeads = currentUser?.role_name === 'admin' || currentUser?.role_name === 'super_admin'

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
    const name = botName.trim()
    const token = normalizeTelegramToken(botToken)
    if (transportType === 'user_mtproto' && !name) {
      setError('Укажите внутреннее название рабочего аккаунта.')
      return
    }
    if (transportType === 'bot_api' && !name && !token) {
      setError('Укажите название черновика или Telegram token.')
      return
    }

    setIsAddingBot(true)
    setError('')
    setNotice('')

    try {
      const { data: createdBot } = await api.post<BotRecord>('/bots', {
        name: name || undefined,
        transport_type: transportType,
        ...(transportType === 'bot_api' && token ? { telegram_token: token } : {}),
      }, {
        params: { project_id: activeProjectId },
      })
      setBotName('')
      setBotToken('')
      await loadBots()
      if (createdBot.telegram_setup_warning) {
        setError(createdBot.telegram_setup_warning)
        return
      }
      setNotice(
        transportType === 'user_mtproto'
          ? 'Рабочий аккаунт создан. Завершите вход в его карточке.'
          : token
          ? 'Бот добавлен: имя подтянуто из Telegram, webhook зарегистрирован.'
          : 'Черновик бота создан. Добавьте новый token после завершения импорта.',
      )
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
    setEditingCrmDescription(bot.crm_description ?? '')
    setEditingTelegramAbout(bot.telegram_about ?? '')
    setEditingTelegramDescription(bot.telegram_description ?? '')
  }

  const cancelEditBot = () => {
    setEditingBotId(null)
    setEditingBotName('')
    setEditingBotToken('')
    setEditingCrmDescription('')
    setEditingTelegramAbout('')
    setEditingTelegramDescription('')
  }

  const handleSaveBot = async (botId: string) => {
    if (savingBotId) {
      return
    }

    setSavingBotId(botId)
    setError('')
    setNotice('')

    try {
      const editedBot = bots.find((bot) => bot.id === botId)
      const token = normalizeTelegramToken(editingBotToken)
      const updatedBot = await updateBot(botId, {
        name: editingBotName.trim(),
        crm_description: normalizeOptionalText(editingCrmDescription),
        ...(editedBot?.transport_type !== 'user_mtproto'
          ? {
              telegram_about: normalizeOptionalText(editingTelegramAbout),
              telegram_description: normalizeOptionalText(editingTelegramDescription),
              ...(token ? { telegram_token: token } : {}),
            }
          : {}),
      }, activeProjectId)
      cancelEditBot()
      await loadBots()
      if (updatedBot.telegram_setup_warning) {
        setError(updatedBot.telegram_setup_warning)
        return
      }
      setNotice(
        editedBot?.transport_type === 'user_mtproto'
          ? 'Настройки рабочего аккаунта обновлены.'
          : 'Бот обновлён, профиль Telegram синхронизирован.',
      )
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось обновить бота.'))
    } finally {
      setSavingBotId(null)
    }
  }

  const handleUploadAvatar = async (botId: string, file: File | null | undefined) => {
    if (!file || avatarUploadingBotId) {
      return
    }

    setAvatarUploadingBotId(botId)
    setError('')
    setNotice('')

    try {
      await uploadBotAvatar(botId, file, activeProjectId)
      setNotice('Аватарка бота обновлена в Telegram.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось загрузить аватарку.'))
    } finally {
      setAvatarUploadingBotId(null)
    }
  }

  const handleDownloadAuditLogs = async (botId: string) => {
    if (auditExportingBotId) {
      return
    }

    setAuditExportingBotId(botId)
    setError('')
    setNotice('')

    try {
      await downloadBotAuditLogs(botId, activeProjectId)
      setNotice('CSV с логами настроек скачан.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось скачать логи настроек.'))
    } finally {
      setAuditExportingBotId(null)
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
              <h1 className="text-xl font-semibold text-white">Telegram</h1>
              <p className="text-sm text-gray-500">Боты и рабочие аккаунты проекта</p>
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
        <form className="mb-5 grid gap-3 rounded-xl border border-white/5 bg-surface p-4 md:grid-cols-2 xl:grid-cols-[auto_1fr_1fr_auto]" onSubmit={handleAddBot}>
          <div className="flex min-h-10 rounded-lg border border-white/10 bg-background/70 p-1 md:col-span-2 xl:col-span-1">
            <button
              type="button"
              onClick={() => setTransportType('bot_api')}
              className={`flex flex-1 items-center justify-center gap-2 rounded-md px-3 text-sm font-semibold transition ${transportType === 'bot_api' ? 'bg-cyan-500/15 text-cyan-100' : 'text-gray-500 hover:text-gray-200'}`}
            >
              <BotIcon size={15} />
              Бот
            </button>
            <button
              type="button"
              onClick={() => setTransportType('user_mtproto')}
              className={`flex flex-1 items-center justify-center gap-2 rounded-md px-3 text-sm font-semibold transition ${transportType === 'user_mtproto' ? 'bg-cyan-500/15 text-cyan-100' : 'text-gray-500 hover:text-gray-200'}`}
            >
              <UserRound size={15} />
              Аккаунт
            </button>
          </div>
          <input
            value={botName}
            onChange={(event) => setBotName(event.target.value)}
            placeholder={transportType === 'user_mtproto' ? 'Внутреннее название аккаунта' : 'Название бота'}
            maxLength={255}
            className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
          />
          {transportType === 'bot_api' ? (
            <input
              value={botToken}
              onChange={(event) => setBotToken(event.target.value)}
              placeholder="Telegram token (можно добавить позже)"
              type="password"
              autoComplete="new-password"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              data-1p-ignore="true"
              data-lpignore="true"
              maxLength={255}
              className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
            />
          ) : (
            <div className="flex min-h-10 items-center rounded-xl border border-white/5 bg-white/[0.02] px-3 text-sm text-gray-500">
              API ID и API hash указываются после создания.
            </div>
          )}
          <button
            type="submit"
            disabled={isAddingBot || (transportType === 'user_mtproto' ? !botName.trim() : !botName.trim() && !botToken.trim())}
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
            const isUserAccount = bot.transport_type === 'user_mtproto'

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
                    {!isUserAccount ? (
                      <input
                        value={editingBotToken}
                        onChange={(event) => setEditingBotToken(event.target.value)}
                        maxLength={255}
                        type="password"
                        autoComplete="new-password"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                        data-1p-ignore="true"
                        data-lpignore="true"
                        placeholder="Новый token, необязательно"
                        className="rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-base text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm"
                      />
                    ) : null}
                    <label className="grid gap-1">
                      <span className="text-xs font-medium text-gray-500">CRM-описание</span>
                      <textarea
                        value={editingCrmDescription}
                        onChange={(event) => setEditingCrmDescription(event.target.value)}
                        maxLength={4096}
                        rows={3}
                        className="min-h-[84px] resize-y rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                        placeholder="Внутреннее описание для операторов"
                      />
                    </label>
                    {!isUserAccount ? <label className="grid gap-1">
                      <span className="text-xs font-medium text-gray-500">Короткое описание Telegram</span>
                      <textarea
                        value={editingTelegramAbout}
                        onChange={(event) => setEditingTelegramAbout(event.target.value)}
                        maxLength={120}
                        rows={2}
                        className="min-h-[68px] resize-y rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                        placeholder="Текст в блоке «О боте»"
                      />
                    </label> : null}
                    {!isUserAccount ? <label className="grid gap-1">
                      <span className="text-xs font-medium text-gray-500">Приветственное описание Telegram</span>
                      <textarea
                        value={editingTelegramDescription}
                        onChange={(event) => setEditingTelegramDescription(event.target.value)}
                        maxLength={512}
                        rows={3}
                        className="min-h-[84px] resize-y rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                        placeholder="Описание до старта бота"
                      />
                    </label> : null}
                  </div>
                ) : (
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                      {isUserAccount ? <UserRound size={17} className="shrink-0 text-cyan-300" /> : <BotIcon size={17} className="shrink-0 text-cyan-300" />}
                      <h2 className="min-w-0 truncate text-lg font-semibold text-white">{bot.name}</h2>
                      <span className="shrink-0 rounded-full border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[10px] font-semibold text-gray-400">
                        {isUserAccount ? 'АККАУНТ' : 'БОТ'}
                      </span>
                    </div>
                    <p className="truncate text-sm text-gray-500">
                      {bot.bot_username ? `@${bot.bot_username}` : 'username не указан'}
                    </p>
                    {bot.telegram_first_name || bot.telegram_bot_id ? (
                      <p className="mt-1 truncate text-xs text-gray-500">
                        Telegram: {[bot.telegram_first_name, bot.telegram_bot_id ? `ID ${bot.telegram_bot_id}` : null].filter(Boolean).join(' · ')}
                      </p>
                    ) : null}
                    {!isUserAccount ? (
                      <p className="mt-2 text-xs text-gray-500">
                        Token: {bot.has_telegram_token ? 'добавлен' : 'не добавлен'}
                      </p>
                    ) : null}
                    <div className="mt-4 grid gap-2 text-sm">
                      <BotDescriptionRow label="CRM" value={bot.crm_description} />
                      {!isUserAccount ? <BotDescriptionRow label="About" value={bot.telegram_about} /> : null}
                      {!isUserAccount ? <BotDescriptionRow label="Description" value={bot.telegram_description} /> : null}
                    </div>
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
                      {!isUserAccount ? <button
                        type="button"
                        title="Зарегистрировать webhook"
                        onClick={() => void handleSetWebhook(bot.id)}
                        disabled={webhookBotId === bot.id || !bot.has_telegram_token}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {webhookBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <PlugZap size={15} />}
                        Webhook
                      </button> : null}
                      {!isUserAccount ? <button
                        type="button"
                        title="Синхронизировать с Telegram"
                        onClick={() => void handleSyncBot(bot.id)}
                        disabled={syncingBotId === bot.id || !bot.has_telegram_token}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {syncingBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <RefreshCw size={15} />}
                        Синхронизировать
                      </button> : null}
                      <button
                        type="button"
                        title="Редактировать"
                        onClick={() => startEditBot(bot)}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50"
                      >
                        <Pencil size={15} />
                        Изменить
                      </button>
                      {!isUserAccount ? <label
                        title="Загрузить JPEG-аватар"
                        className={`inline-flex h-9 cursor-pointer items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 ${
                          avatarUploadingBotId === bot.id ? 'pointer-events-none opacity-50' : ''
                        }`}
                      >
                        {avatarUploadingBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <ImagePlus size={15} />}
                        Аватар
                        <input
                          type="file"
                          accept="image/jpeg"
                          className="hidden"
                          onChange={(event) => {
                            void handleUploadAvatar(bot.id, event.currentTarget.files?.[0])
                            event.currentTarget.value = ''
                          }}
                        />
                      </label> : null}
                      <button
                        type="button"
                        title="Скачать логи изменений настроек бота"
                        onClick={() => void handleDownloadAuditLogs(bot.id)}
                        disabled={auditExportingBotId === bot.id}
                        className="inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-accent-300/50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {auditExportingBotId === bot.id ? <LoaderCircle size={15} className="animate-spin" /> : <Download size={15} />}
                        CSV
                      </button>
                      {canImportLeads && activeProjectId ? (
                        <button
                          type="button"
                          title="Перенести лидов из Chatterfy"
                          onClick={() => setLeadImportBot(bot)}
                          className="inline-flex h-9 items-center gap-2 rounded-xl border border-cyan-400/25 bg-cyan-500/10 px-3 text-sm text-cyan-100 transition hover:border-cyan-300/60"
                        >
                          <ImportIcon size={15} />
                          Перенос лидов
                        </button>
                      ) : null}
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
                {isUserAccount && activeProjectId ? (
                  <TelegramAccountConnectionPanel
                    bot={bot}
                    projectId={activeProjectId}
                    onChanged={loadBots}
                  />
                ) : null}
              </article>
            )
          })}
        </div>

        <div className="mt-5 rounded-xl border border-accent-300/20 bg-accent-500/10 p-4 text-sm text-accent-100">
          Реферальные tracking links доступны Telegram-ботам. Для рабочих аккаунтов считается общая статистика по аккаунту.
        </div>
      </div>
      {leadImportBot && activeProjectId ? (
        <LeadImportModal
          bot={leadImportBot}
          projectId={activeProjectId}
          onClose={() => setLeadImportBot(null)}
        />
      ) : null}
    </section>
  )
}

import axios from 'axios'
import { CheckCircle2, KeyRound, Link2Off, LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useState } from 'react'

import {
  confirmTelegramAccountCode,
  confirmTelegramAccountPassword,
  disconnectTelegramAccount,
  fetchTelegramAccountConnection,
  requestTelegramAccountCode,
  syncTelegramAccount,
} from '../api'
import type { Bot, TelegramAccountConnection } from '../types'

type Props = {
  bot: Bot
  projectId: string
  onChanged: () => void | Promise<void>
}

function errorText(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return 'Не удалось выполнить операцию с Telegram-аккаунтом.'
}

const inputClass =
  'min-h-10 w-full rounded-lg border border-white/10 bg-background/70 px-3 text-base text-gray-100 outline-none ring-cyan-400/40 transition placeholder:text-gray-600 focus:ring-2 md:text-sm'

export default function TelegramAccountConnectionPanel({ bot, projectId, onChanged }: Props) {
  const [connection, setConnection] = useState<TelegramAccountConnection | null>(null)
  const [apiId, setApiId] = useState('')
  const [apiHash, setApiHash] = useState('')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError('')
    try {
      const next = await fetchTelegramAccountConnection(bot.id, projectId)
      setConnection(next)
      if (next.api_id) setApiId(String(next.api_id))
    } catch (requestError) {
      setError(errorText(requestError))
    }
  }, [bot.id, projectId])

  useEffect(() => {
    void load()
  }, [load])

  const run = async (action: () => Promise<TelegramAccountConnection>) => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const next = await action()
      setConnection(next)
      await onChanged()
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setBusy(false)
    }
  }

  const requestCode = (event: FormEvent) => {
    event.preventDefault()
    const numericApiId = Number(apiId)
    if (!Number.isInteger(numericApiId) || numericApiId <= 0 || !apiHash.trim() || !phone.trim()) {
      setError('Заполните API ID, API hash и номер телефона.')
      return
    }
    void run(() =>
      requestTelegramAccountCode(
        bot.id,
        { api_id: numericApiId, api_hash: apiHash.trim(), phone_number: phone.trim() },
        projectId,
      ),
    )
  }

  const disconnect = async () => {
    if (busy || !window.confirm('Отключить рабочий Telegram-аккаунт от CRM?')) return
    setBusy(true)
    setError('')
    try {
      await disconnectTelegramAccount(bot.id, projectId)
      setConnection(null)
      setApiHash('')
      setPhone('')
      setCode('')
      setPassword('')
      await load()
      await onChanged()
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setBusy(false)
    }
  }

  const authStatus = connection?.auth_status ?? 'disconnected'
  const isAuthorized = authStatus === 'authorized'
  const identity = [connection?.telegram_first_name, connection?.telegram_last_name]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="mt-4 border-t border-white/5 pt-4">
      <div className="mb-3 flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <ShieldCheck size={16} className="shrink-0 text-cyan-300" />
          <span className="truncate text-sm font-semibold text-gray-100">Рабочий Telegram-аккаунт</span>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-1 text-[11px] font-semibold ${
            connection?.connection_status === 'connected'
              ? 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200'
              : connection?.connection_status === 'error'
                ? 'border-red-400/30 bg-red-500/10 text-red-200'
                : 'border-white/10 bg-white/[0.03] text-gray-400'
          }`}
        >
          {connection?.connection_status === 'connected'
            ? 'В сети'
            : connection?.connection_status === 'connecting'
              ? 'Подключение'
              : connection?.connection_status === 'error'
                ? 'Ошибка'
                : 'Не подключён'}
        </span>
      </div>

      {error ? <div className="mb-3 rounded-lg border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</div> : null}
      {connection?.last_error && !error ? (
        <div className="mb-3 rounded-lg border border-amber-400/20 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
          {connection.last_error}
        </div>
      ) : null}

      {isAuthorized ? (
        <div className="grid gap-3">
          <div className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-3 text-sm">
            <div className="flex items-center gap-2 font-semibold text-white">
              <CheckCircle2 size={16} className="shrink-0 text-emerald-300" />
              <span className="min-w-0 truncate">{identity || 'Telegram-аккаунт'}</span>
            </div>
            <div className="mt-1 truncate text-xs text-gray-500">
              {connection?.telegram_username ? `@${connection.telegram_username}` : 'без username'}
              {connection?.phone_number_masked ? ` · ${connection.phone_number_masked}` : ''}
              {connection?.telegram_user_id ? ` · ID ${connection.telegram_user_id}` : ''}
            </div>
            <p className="mt-2 text-xs leading-5 text-gray-500">
              Новые входящие и сообщения, отправленные из приложения Telegram, синхронизируются автоматически.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void run(() => syncTelegramAccount(bot.id, projectId))}
              disabled={busy}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.04] px-3 text-sm text-gray-200 transition hover:border-cyan-300/50 disabled:opacity-50"
            >
              {busy ? <LoaderCircle size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              Обновить профиль
            </button>
            <button
              type="button"
              onClick={() => void disconnect()}
              disabled={busy}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-red-400/20 bg-red-500/10 px-3 text-sm text-red-100 transition hover:border-red-300/50 disabled:opacity-50"
            >
              <Link2Off size={15} />
              Отключить
            </button>
          </div>
        </div>
      ) : authStatus === 'awaiting_code' ? (
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault()
            if (code.trim()) void run(() => confirmTelegramAccountCode(bot.id, code.trim(), projectId))
          }}
        >
          <input
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\s+/g, ''))}
            placeholder="Код Telegram"
            inputMode="numeric"
            autoComplete="one-time-code"
            className={inputClass}
          />
          <button type="submit" disabled={busy || !code.trim()} className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-semibold text-[#071018] disabled:opacity-50">
            {busy ? <LoaderCircle size={15} className="animate-spin" /> : <KeyRound size={15} />}
            Подтвердить
          </button>
        </form>
      ) : authStatus === 'awaiting_password' ? (
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault()
            if (password) void run(() => confirmTelegramAccountPassword(bot.id, password, projectId))
          }}
        >
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Пароль 2FA"
            type="password"
            autoComplete="current-password"
            className={inputClass}
          />
          <button type="submit" disabled={busy || !password} className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-semibold text-[#071018] disabled:opacity-50">
            {busy ? <LoaderCircle size={15} className="animate-spin" /> : <KeyRound size={15} />}
            Войти
          </button>
        </form>
      ) : (
        <form className="grid gap-2 sm:grid-cols-2" onSubmit={requestCode}>
          <input value={apiId} onChange={(event) => setApiId(event.target.value.replace(/\D+/g, ''))} placeholder="API ID" inputMode="numeric" className={inputClass} />
          <input value={apiHash} onChange={(event) => setApiHash(event.target.value)} placeholder="API hash" type="password" autoComplete="new-password" className={inputClass} />
          <input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="Телефон с кодом страны" type="tel" autoComplete="tel" className={inputClass} />
          <button type="submit" disabled={busy} className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-semibold text-[#071018] disabled:opacity-50">
            {busy ? <LoaderCircle size={15} className="animate-spin" /> : <KeyRound size={15} />}
            Получить код
          </button>
        </form>
      )}
    </div>
  )
}

import { LoaderCircle, LockKeyhole, Mail, Send } from 'lucide-react'
import { FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

import api from '../api/client'
import { useAuthStore } from '../store/authStore'

type TelegramSession = {
  session_token: string
  deep_link: string
  bot_username: string
  expires_in: number
}

type TelegramSessionStatus = {
  status: 'pending' | 'completed' | 'expired' | 'not_registered'
  access_token: string | null
}

export default function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((state) => state.login)
  const completeLogin = useAuthStore((state) => state.completeLogin)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  const telegramPollRef = useRef<number | null>(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isTelegramLoading, setIsTelegramLoading] = useState(false)
  const [telegramBotUsername, setTelegramBotUsername] = useState('')
  const [isTelegramConfigured, setIsTelegramConfigured] = useState(false)
  const [isTelegramConfigLoading, setIsTelegramConfigLoading] = useState(true)

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/chats', { replace: true })
    }
  }, [isAuthenticated, navigate])

  useEffect(() => {
    let cancelled = false
    void api
      .get<{ username: string | null; is_configured: boolean }>(
        '/auth/telegram-config',
      )
      .then(({ data }) => {
        if (cancelled) {
          return
        }
        setTelegramBotUsername((data.username ?? '').replace(/^@/, ''))
        setIsTelegramConfigured(data.is_configured)
      })
      .catch(() => {
        if (!cancelled) setIsTelegramConfigured(false)
      })
      .finally(() => {
        if (!cancelled) {
          setIsTelegramConfigLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => () => {
    if (telegramPollRef.current !== null) window.clearInterval(telegramPollRef.current)
  }, [])

  const handleTelegramLogin = async () => {
    if (isTelegramLoading) return
    setError('')
    setIsTelegramLoading(true)
    const telegramWindow = window.open('about:blank', 'crm-telegram-login')
    try {
      const { data } = await api.post<TelegramSession>('/auth/telegram-login/sessions')
      if (telegramWindow) {
        telegramWindow.opener = null
        telegramWindow.location.href = data.deep_link
      } else {
        throw new Error('Telegram popup was blocked')
      }

      const checkStatus = async () => {
        const response = await api.post<TelegramSessionStatus>(
          '/auth/telegram-login/sessions/status',
          { session_token: data.session_token },
        )
        if (response.data.status === 'pending') return
        if (telegramPollRef.current !== null) {
          window.clearInterval(telegramPollRef.current)
          telegramPollRef.current = null
        }
        if (response.data.status === 'completed' && response.data.access_token) {
          telegramWindow.close()
          await completeLogin(response.data.access_token)
          navigate('/chats', { replace: true })
          return
        }
        setIsTelegramLoading(false)
        setError(
          response.data.status === 'not_registered'
            ? 'Этот Telegram не привязан к аккаунту CRM.'
            : 'Ссылка входа истекла. Запустите вход ещё раз.',
        )
      }

      const poll = () => {
        void checkStatus().catch((err) => {
          if (telegramPollRef.current !== null) window.clearInterval(telegramPollRef.current)
          telegramPollRef.current = null
          setIsTelegramLoading(false)
          setError(extractAuthError(err))
        })
      }
      telegramPollRef.current = window.setInterval(poll, 1500)
      poll()
    } catch (err) {
      telegramWindow?.close()
      setIsTelegramLoading(false)
      setError(extractAuthError(err))
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login(email, password)
      navigate('/chats', { replace: true })
    } catch (err) {
      setError(extractAuthError(err))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-950 p-4 text-zinc-100">
      <div className="w-full max-w-md rounded-lg border border-zinc-800 bg-zinc-950 p-8 shadow-2xl">
        <h1 className="mb-2 text-center text-2xl font-semibold text-zinc-100">CRM MVP</h1>
        <p className="mb-6 text-center text-sm text-zinc-500">Войдите, чтобы продолжить</p>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-zinc-300">Email</span>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={16} />
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-2 pl-10 pr-3 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-500 focus:ring-2"
                placeholder="name@company.com"
                autoComplete="email"
                required
              />
            </div>
          </label>

          <label className="block">
            <span className="mb-1 block text-sm font-medium text-zinc-300">Пароль</span>
            <div className="relative">
              <LockKeyhole className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={16} />
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 py-2 pl-10 pr-3 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-500 focus:ring-2"
                placeholder="Введите пароль"
                autoComplete="current-password"
                required
              />
            </div>
          </label>

          {error ? <p className="text-sm text-red-300">{error}</p> : null}

          <button
            type="submit"
            disabled={isLoading}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 py-2.5 text-sm font-medium text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-75"
          >
            {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : null}
            {isLoading ? 'Входим...' : 'Войти'}
          </button>
        </form>

        <div className="my-6 flex items-center gap-3 text-xs uppercase tracking-[0.18em] text-zinc-600">
          <span className="h-px flex-1 bg-zinc-800" />
          <span>или</span>
          <span className="h-px flex-1 bg-zinc-800" />
        </div>

        <div className="flex min-h-12 items-center justify-center">
          {isTelegramConfigLoading ? (
            <LoaderCircle size={18} className="animate-spin text-zinc-500" />
          ) : isTelegramConfigured && telegramBotUsername ? (
            <button
              type="button"
              onClick={() => void handleTelegramLogin()}
              disabled={isTelegramLoading}
              className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-sky-400/30 bg-sky-500/10 px-4 text-sm font-semibold text-sky-100 transition hover:bg-sky-500/15 disabled:cursor-wait disabled:opacity-60"
            >
              {isTelegramLoading ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
              {isTelegramLoading ? 'Подтвердите вход в Telegram' : 'Войти через Telegram'}
            </button>
          ) : (
            <button
              type="button"
              disabled
              title="Админ-бот Telegram не настроен"
              className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-sky-400/20 bg-sky-500/10 px-4 text-sm font-semibold text-sky-100 opacity-60"
            >
              <Send size={16} />
              Войти через Telegram
            </button>
          )}
        </div>
        {isTelegramLoading ? (
          <div className="mt-3 flex items-center justify-center gap-2 text-sm text-zinc-500">
            <LoaderCircle size={15} className="animate-spin" />
            Проверяем Telegram
          </div>
        ) : null}
      </div>
    </div>
  )
}

function extractAuthError(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен. Проверьте backend или контейнер.'
    }
  }

  if (err instanceof Error && err.message === 'Telegram popup was blocked') {
    return 'Браузер заблокировал окно Telegram. Разрешите всплывающие окна для CRM и повторите вход.'
  }

  return 'Не удалось войти. Попробуйте снова.'
}

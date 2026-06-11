import { LoaderCircle, LockKeyhole, Mail, Send } from 'lucide-react'
import { FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

import { useAuthStore, type TelegramAuthPayload } from '../store/authStore'

type TelegramLoginUser = TelegramAuthPayload & {
  id?: number | string
  first_name?: string
  last_name?: string
  username?: string
  photo_url?: string
  auth_date?: number | string
  hash?: string
}

declare global {
  interface Window {
    onTelegramAuth?: (user: TelegramLoginUser) => void
  }
}

const telegramBotUsername = (
  import.meta.env.VITE_TELEGRAM_LOGIN_BOT_USERNAME ||
  import.meta.env.VITE_BUYER_BOT_USERNAME ||
  ''
).replace(/^@/, '')

export default function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((state) => state.login)
  const loginWithTelegram = useAuthStore((state) => state.loginWithTelegram)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  const telegramWidgetRef = useRef<HTMLDivElement | null>(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isTelegramLoading, setIsTelegramLoading] = useState(false)

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/chats', { replace: true })
    }
  }, [isAuthenticated, navigate])

  useEffect(() => {
    window.onTelegramAuth = (user: TelegramLoginUser) => {
      setError('')
      setIsTelegramLoading(true)
      void loginWithTelegram(user)
        .then(() => navigate('/chats', { replace: true }))
        .catch((err) => {
          setError(extractAuthError(err))
        })
        .finally(() => setIsTelegramLoading(false))
    }

    return () => {
      delete window.onTelegramAuth
    }
  }, [loginWithTelegram, navigate])

  useEffect(() => {
    if (!telegramBotUsername || !telegramWidgetRef.current) {
      return
    }

    const widgetContainer = telegramWidgetRef.current
    widgetContainer.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.async = true
    script.setAttribute('data-telegram-login', telegramBotUsername)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-radius', '12')
    script.setAttribute('data-request-access', 'write')
    script.setAttribute('data-onauth', 'onTelegramAuth(user)')
    widgetContainer.appendChild(script)

    return () => {
      widgetContainer.innerHTML = ''
    }
  }, [])

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
          {telegramBotUsername ? (
            <div className={isTelegramLoading ? 'pointer-events-none opacity-60' : ''} ref={telegramWidgetRef} />
          ) : (
            <button
              type="button"
              disabled
              title="Telegram Login bot username is not configured"
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

  return 'Не удалось войти. Попробуйте снова.'
}

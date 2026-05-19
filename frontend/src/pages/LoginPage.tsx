import { LoaderCircle, LockKeyhole, Mail } from 'lucide-react'
import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

import { useAuthStore } from '../store/authStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const login = useAuthStore((state) => state.login)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/chats', { replace: true })
    }
  }, [isAuthenticated, navigate])

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      await login(email, password)
      navigate('/chats', { replace: true })
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail
        if (typeof detail === 'string' && detail.length > 0) {
          setError(detail)
        } else if (err.code === 'ERR_NETWORK') {
          setError('API недоступен. Проверьте backend или контейнер.')
        } else {
          setError('Не удалось войти. Попробуйте снова.')
        }
      } else {
        setError('Не удалось войти. Попробуйте снова.')
      }
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
      </div>
    </div>
  )
}

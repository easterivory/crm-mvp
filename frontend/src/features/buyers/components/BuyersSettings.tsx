import axios from 'axios'
import {
  Check,
  Clipboard,
  LoaderCircle,
  Plus,
  RefreshCcw,
  Send,
  UserRoundPlus,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { Modal } from '../../../shared/ui'
import { createBuyer, fetchBuyerPerformance } from '../api'
import type { BuyerInvite, BuyerPerformance } from '../types'

type BuyersSettingsProps = {
  projectId: string | null
}

function getErrorMessage(err: unknown, fallback: string) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

export default function BuyersSettings({ projectId }: BuyersSettingsProps) {
  const [buyers, setBuyers] = useState<BuyerPerformance[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [createdInvite, setCreatedInvite] = useState<BuyerInvite | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')

  const sortedBuyers = useMemo(
    () => [...buyers].sort((a, b) => a.name.localeCompare(b.name, 'ru')),
    [buyers],
  )

  const loadBuyers = useCallback(async () => {
    if (!projectId) {
      setBuyers([])
      return
    }

    setIsLoading(true)
    setError('')
    try {
      setBuyers(await fetchBuyerPerformance(projectId))
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось загрузить баеров.'))
    } finally {
      setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadBuyers()
  }, [loadBuyers])

  const resetCreateForm = () => {
    setName('')
    setEmail('')
    setPassword('')
    setCreatedInvite(null)
    setCopied(false)
    setError('')
  }

  const handleOpenCreate = () => {
    resetCreateForm()
    setIsCreateOpen(true)
  }

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isCreating) {
      return
    }

    setIsCreating(true)
    setError('')
    setCopied(false)
    try {
      const invite = await createBuyer(
        {
          name: name.trim(),
          email: email.trim(),
          password,
        },
        projectId,
      )
      setCreatedInvite(invite)
      setPassword('')
      await loadBuyers()
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось создать баера.'))
    } finally {
      setIsCreating(false)
    }
  }

  const handleCopy = async () => {
    if (!createdInvite) {
      return
    }

    try {
      await navigator.clipboard.writeText(createdInvite.invite_link)
      setCopied(true)
    } catch {
      setError('Не удалось скопировать ссылку в буфер обмена.')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-zinc-100">Баеры</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Инвайты для Telegram-кабинета закупщиков и статус привязки аккаунта.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void loadBuyers()}
            disabled={isLoading || !projectId}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 text-sm font-semibold text-zinc-200 transition hover:border-cyan-300/50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCcw size={16} className={isLoading ? 'animate-spin' : undefined} />
            Обновить
          </button>
          <button
            type="button"
            onClick={handleOpenCreate}
            disabled={!projectId}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={16} />
            Добавить баера
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-900/70 bg-red-950/40 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      {!projectId ? (
        <div className="rounded-lg border border-white/10 bg-white/[0.02] p-5 text-sm text-zinc-500">
          Выберите проект, чтобы управлять баерами.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-white/10 bg-white/[0.02]">
          <table className="min-w-[720px] w-full text-left text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3">Имя баера</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Telegram</th>
                <th className="px-4 py-3 text-right">Ссылки</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {isLoading ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-500">
                    <LoaderCircle size={18} className="mr-2 inline animate-spin" />
                    Загрузка баеров
                  </td>
                </tr>
              ) : sortedBuyers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-500">
                    Баеры еще не созданы.
                  </td>
                </tr>
              ) : (
                sortedBuyers.map((buyer) => (
                  <tr key={buyer.buyer_id} className="bg-transparent">
                    <td className="px-4 py-3 font-semibold text-zinc-100">{buyer.name}</td>
                    <td className="px-4 py-3 text-zinc-400">{buyer.email}</td>
                    <td className="px-4 py-3">
                      {buyer.buyer_telegram_id ? (
                        <span className="inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-200">
                          <Check size={13} />
                          Telegram привязан (ID: {buyer.buyer_telegram_id})
                        </span>
                      ) : (
                        <span className="inline-flex rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs font-semibold text-zinc-400">
                          Ожидает активации
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-zinc-300">
                      {buyer.links_count}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {isCreateOpen ? (
        <Modal
          title="Добавить баера"
          description="Создайте пользователя и передайте ему одноразовую ссылку для привязки Telegram."
          onClose={() => setIsCreateOpen(false)}
          maxWidthClassName="max-w-xl"
        >
          <div className="space-y-5">
            {createdInvite ? (
              <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-emerald-100">
                  <Send size={16} />
                  Инвайт готов
                </div>
                <p className="mt-2 text-sm text-emerald-100/75">
                  Отправьте ссылку баеру. После активации токен будет очищен на сервере.
                </p>
                <div className="mt-3 break-all rounded-lg border border-white/10 bg-[#070B14] p-3 font-mono text-xs text-cyan-100">
                  {createdInvite.invite_link}
                </div>
                <button
                  type="button"
                  onClick={() => void handleCopy()}
                  className="mt-3 inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-emerald-300/30 bg-emerald-300/10 px-3 text-sm font-semibold text-emerald-100 transition hover:border-emerald-200/60"
                >
                  {copied ? <Check size={16} /> : <Clipboard size={16} />}
                  {copied ? 'Скопировано' : 'Скопировать ссылку'}
                </button>
              </div>
            ) : null}

            <form className="space-y-3" onSubmit={handleCreate}>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Имя</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  required
                  maxLength={255}
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-400 transition placeholder:text-zinc-600 focus:ring-2"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Email</span>
                <input
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-400 transition placeholder:text-zinc-600 focus:ring-2"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Пароль</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength={8}
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-cyan-400 transition placeholder:text-zinc-600 focus:ring-2"
                />
              </label>
              <button
                type="submit"
                disabled={!projectId || isCreating}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreating ? <LoaderCircle size={16} className="animate-spin" /> : <UserRoundPlus size={16} />}
                Создать баера
              </button>
            </form>
          </div>
        </Modal>
      ) : null}
    </div>
  )
}

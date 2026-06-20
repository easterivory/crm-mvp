import axios from 'axios'
import {
  AlertTriangle,
  CheckCircle2,
  Clipboard,
  Copy,
  ExternalLink,
  Globe2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

import { Modal } from '../../../shared/ui'
import {
  createProjectDomain,
  createProjectLander,
  deleteProjectDomain,
  deleteProjectLander,
  fetchActiveTrackingLinks,
  fetchProjectDomains,
  fetchProjectLanders,
  uploadProjectLanderZip,
} from '../api'
import type {
  LanderType,
  ProjectDomain,
  ProjectLander,
  TrackingLinkOption,
} from '../types'

type LandersSettingsProps = {
  projectId: string | null
}

type Banner = {
  tone: 'success' | 'error'
  message: string
}

type LanderForm = {
  name: string
  domainId: string
  slug: string
  trackingLinkId: string
  type: LanderType
  zipFile: File | null
}

const emptyLanderForm: LanderForm = {
  name: '',
  domainId: '',
  slug: '',
  trackingLinkId: '',
  type: 'default_tg_redirect',
  zipFile: null,
}

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      if (detail === 'Invalid lander slug' || detail.includes('slug may contain only')) {
        return 'Slug может содержать только латинские буквы, цифры, дефис и подчёркивание.'
      }
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return fallback
}

function landerTypeLabel(type: LanderType) {
  return type === 'custom_upload' ? 'Кастомный' : 'Дефолтный'
}

function generateSlug() {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'
  const bytes = new Uint8Array(10)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => alphabet[byte % alphabet.length]).join('')
}

function normalizeSlugInput(value: string) {
  return value.trim().replace(/[^A-Za-z0-9_-]/g, '').slice(0, 100)
}

function isValidLanderSlug(value: string) {
  return /^[A-Za-z0-9_-]{1,100}$/.test(value.trim())
}

function normalizeDomainInput(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, '')
    .split('/')[0]
    .split(':')[0]
    .replace(/\.$/, '')
}

function buildLanderUrl(domainName: string, slug: string) {
  return `https://${domainName}/l/${slug}`
}

export default function LandersSettings({ projectId }: LandersSettingsProps) {
  const [domains, setDomains] = useState<ProjectDomain[]>([])
  const [landers, setLanders] = useState<ProjectLander[]>([])
  const [trackingLinks, setTrackingLinks] = useState<TrackingLinkOption[]>([])
  const [newDomainName, setNewDomainName] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isAddingDomain, setIsAddingDomain] = useState(false)
  const [deletingDomainId, setDeletingDomainId] = useState<string | null>(null)
  const [deletingLanderId, setDeletingLanderId] = useState<string | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isSavingLander, setIsSavingLander] = useState(false)
  const [banner, setBanner] = useState<Banner | null>(null)
  const [copiedValue, setCopiedValue] = useState('')
  const [form, setForm] = useState<LanderForm>(emptyLanderForm)

  const domainById = useMemo(
    () => new Map(domains.map((domain) => [domain.id, domain])),
    [domains],
  )
  const trackingLinkById = useMemo(
    () => new Map(trackingLinks.map((link) => [link.id, link])),
    [trackingLinks],
  )

  const loadData = useCallback(async () => {
    if (!projectId) {
      setDomains([])
      setLanders([])
      setTrackingLinks([])
      return
    }

    setIsLoading(true)
    setBanner(null)
    try {
      const [domainItems, landerItems, linkItems] = await Promise.all([
        fetchProjectDomains(projectId),
        fetchProjectLanders(projectId),
        fetchActiveTrackingLinks(projectId),
      ])
      setDomains(domainItems)
      setLanders(landerItems)
      setTrackingLinks(linkItems)
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось загрузить лендинги и домены.'),
      })
    } finally {
      setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const resetForm = useCallback(() => {
    setForm({
      ...emptyLanderForm,
      domainId: domains[0]?.id ?? '',
      trackingLinkId: trackingLinks[0]?.id ?? '',
      slug: generateSlug(),
    })
  }, [domains, trackingLinks])

  const openCreateModal = () => {
    resetForm()
    setBanner(null)
    setIsModalOpen(true)
  }

  const handleCopy = async (value: string) => {
    await navigator.clipboard.writeText(value)
    setCopiedValue(value)
    window.setTimeout(() => setCopiedValue(''), 1600)
  }

  const handleAddDomain = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isAddingDomain) {
      return
    }
    const domainName = normalizeDomainInput(newDomainName)
    if (!domainName) {
      setBanner({ tone: 'error', message: 'Укажите доменное имя.' })
      return
    }

    setIsAddingDomain(true)
    setBanner(null)
    try {
      await createProjectDomain(projectId, { domain_name: domainName })
      setNewDomainName('')
      await loadData()
      setBanner({ tone: 'success', message: 'Домен припаркован.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось припарковать домен.'),
      })
    } finally {
      setIsAddingDomain(false)
    }
  }

  const handleDeleteDomain = async (domain: ProjectDomain) => {
    if (!projectId || deletingDomainId) {
      return
    }
    if (!window.confirm(`Разлинковать домен ${domain.domain_name}?`)) {
      return
    }

    setDeletingDomainId(domain.id)
    setBanner(null)
    try {
      await deleteProjectDomain(projectId, domain.id)
      await loadData()
      setBanner({ tone: 'success', message: 'Домен удалён.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось удалить домен.'),
      })
    } finally {
      setDeletingDomainId(null)
    }
  }

  const handleDeleteLander = async (lander: ProjectLander) => {
    if (!projectId || deletingLanderId) {
      return
    }
    if (!window.confirm(`Удалить лендинг "${lander.name}"?`)) {
      return
    }

    setDeletingLanderId(lander.id)
    setBanner(null)
    try {
      await deleteProjectLander(projectId, lander.id)
      await loadData()
      setBanner({ tone: 'success', message: 'Лендинг удалён.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось удалить лендинг.'),
      })
    } finally {
      setDeletingLanderId(null)
    }
  }

  const handleSaveLander = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!projectId || isSavingLander) {
      return
    }
    if (!form.domainId || !form.trackingLinkId || !form.slug.trim()) {
      setBanner({ tone: 'error', message: 'Заполните домен, slug и реф-ссылку.' })
      return
    }
    const slug = normalizeSlugInput(form.slug)
    if (!isValidLanderSlug(slug)) {
      setBanner({
        tone: 'error',
        message: 'Slug может содержать только латинские буквы, цифры, дефис и подчёркивание.',
      })
      return
    }
    if (form.type === 'custom_upload' && !form.zipFile) {
      setBanner({ tone: 'error', message: 'Выберите ZIP-архив для кастомного лендинга.' })
      return
    }

    setIsSavingLander(true)
    setBanner(null)
    try {
      const created = await createProjectLander(projectId, {
        domain_id: form.domainId,
        name: form.name.trim() || slug,
        type: form.type,
        slug,
        tracking_link_id: form.trackingLinkId,
      })
      if (form.type === 'custom_upload' && form.zipFile) {
        await uploadProjectLanderZip(projectId, created.id, form.zipFile)
      }
      setIsModalOpen(false)
      setForm(emptyLanderForm)
      await loadData()
      setBanner({ tone: 'success', message: 'Лендинг создан.' })
    } catch (err) {
      setBanner({
        tone: 'error',
        message: getErrorMessage(err, 'Не удалось создать лендинг.'),
      })
    } finally {
      setIsSavingLander(false)
    }
  }

  if (!projectId) {
    return (
      <div className="rounded-lg border border-white/5 bg-white/[0.02] p-5 text-sm text-zinc-500">
        Выберите проект для управления лендингами и доменами.
      </div>
    )
  }

  return (
    <div className="max-w-6xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-zinc-100">Лендинги и Домены</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Парковка доменов, прокладки и сквозная UTM-атрибуция в Telegram.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreateModal}
          disabled={domains.length === 0 || trackingLinks.length === 0}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={16} />
          Создать лендинг
        </button>
      </div>

      {banner ? (
        <div
          className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${
            banner.tone === 'success'
              ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
              : 'border-red-500/30 bg-red-500/10 text-red-100'
          }`}
        >
          {banner.tone === 'success' ? (
            <CheckCircle2 size={18} className="mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
          )}
          <span>{banner.message}</span>
        </div>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(280px,0.9fr)]">
        <div className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-base font-semibold text-zinc-100">Парковка Доменов</h3>
              <p className="mt-1 text-sm text-zinc-500">Домены, на которых будут открываться прокладки.</p>
            </div>
            <button
              type="button"
              onClick={() => void loadData()}
              disabled={isLoading}
              title="Обновить"
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-emerald-500/40 hover:text-emerald-300 disabled:opacity-50"
            >
              <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
            </button>
          </div>

          <form className="mt-4 flex flex-col gap-3 sm:flex-row" onSubmit={handleAddDomain}>
            <label className="min-w-0 flex-1">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Доменное имя
              </span>
              <input
                value={newDomainName}
                onChange={(event) => setNewDomainName(event.target.value)}
                placeholder="go.zona-acceso.li"
                maxLength={255}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
            </label>
            <button
              type="submit"
              disabled={isAddingDomain || !newDomainName.trim()}
              className="mt-auto inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 text-sm font-semibold text-emerald-100 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isAddingDomain ? <LoaderCircle size={16} className="animate-spin" /> : <Globe2 size={16} />}
              Припарковать
            </button>
          </form>

          <div className="mt-4 overflow-x-auto rounded-lg border border-white/5">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-zinc-500">
                <tr>
                  <th className="px-4 py-3">Домен</th>
                  <th className="px-4 py-3">Статус</th>
                  <th className="w-[96px] px-4 py-3 text-right">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {domains.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-8 text-center text-sm text-zinc-500">
                      Домены пока не припаркованы.
                    </td>
                  </tr>
                ) : (
                  domains.map((domain) => (
                    <tr key={domain.id} className="bg-white/[0.01]">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 font-mono text-zinc-100">
                          <Globe2 size={16} className="text-zinc-500" />
                          {domain.domain_name}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-xs font-semibold text-emerald-200">
                          Активен
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end">
                          <button
                            type="button"
                            title="Разлинковать домен"
                            onClick={() => void handleDeleteDomain(domain)}
                            disabled={deletingDomainId === domain.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-red-500/50 hover:text-red-300 disabled:opacity-50"
                          >
                            {deletingDomainId === domain.id ? (
                              <LoaderCircle size={15} className="animate-spin" />
                            ) : (
                              <Trash2 size={15} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/10 p-4">
          <div className="flex items-start gap-3">
            <Clipboard size={20} className="mt-0.5 shrink-0 text-cyan-200" />
            <div>
              <h3 className="text-sm font-semibold text-cyan-100">DNS-настройка</h3>
              <p className="mt-2 text-sm leading-6 text-cyan-100/75">
                Чтобы ваши прокладки работали, перейдите в панель Cloudflare/регистратора
                вашего домена и направьте A-запись домена на IP-адрес нашего сервера
                или настройте CNAME на технический домен проекта.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-white/5 bg-white/[0.02] p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-zinc-100">Конструктор Прокладок</h3>
            <p className="mt-1 text-sm text-zinc-500">
              Лендинги с автоматической подстановкой ref-кода и UTM-ключа.
            </p>
          </div>
          <button
            type="button"
            onClick={openCreateModal}
            disabled={domains.length === 0 || trackingLinks.length === 0}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-100 transition hover:border-emerald-500/50 hover:text-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={16} />
            Создать лендинг
          </button>
        </div>

        <div className="mt-4 overflow-x-auto rounded-lg border border-white/5">
          <table className="w-full min-w-[860px] text-left text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3">Название</th>
                <th className="px-4 py-3">Итоговая ссылка</th>
                <th className="px-4 py-3">Реф-ссылка</th>
                <th className="w-[96px] px-4 py-3 text-right">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {landers.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-sm text-zinc-500">
                    Лендинги пока не созданы.
                  </td>
                </tr>
              ) : (
                landers.map((lander) => {
                  const domain = domainById.get(lander.domain_id)
                  const link = lander.tracking_link_id
                    ? trackingLinkById.get(lander.tracking_link_id)
                    : null
                  const url = domain ? buildLanderUrl(domain.domain_name, lander.slug) : ''

                  return (
                    <tr key={lander.id} className="bg-white/[0.01]">
                      <td className="px-4 py-3">
                        <div className="font-medium text-zinc-100">{lander.name}</div>
                        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
                          <span>{landerTypeLabel(lander.type)}</span>
                          <span className="font-mono">/{lander.slug}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {url ? (
                          <div className="flex min-w-0 items-center gap-2">
                            <a
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="min-w-0 truncate font-mono text-sm text-cyan-200 hover:text-cyan-100"
                            >
                              {url}
                            </a>
                            <ExternalLink size={14} className="shrink-0 text-zinc-500" />
                            <button
                              type="button"
                              title="Скопировать ссылку"
                              onClick={() => void handleCopy(url)}
                              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-cyan-500/50 hover:text-cyan-200"
                            >
                              <Copy size={14} />
                            </button>
                            {copiedValue === url ? (
                              <span className="shrink-0 text-xs text-emerald-300">Скопировано</span>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-zinc-500">Домен удалён</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {link ? (
                          <div>
                            <div className="text-zinc-100">{link.title}</div>
                            <div className="font-mono text-xs text-zinc-500">{link.code}</div>
                          </div>
                        ) : (
                          <span className="text-zinc-500">Не найдена</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end">
                          <button
                            type="button"
                            title="Удалить лендинг"
                            onClick={() => void handleDeleteLander(lander)}
                            disabled={deletingLanderId === lander.id}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-white/5 text-zinc-400 transition hover:border-red-500/50 hover:text-red-300 disabled:opacity-50"
                          >
                            {deletingLanderId === lander.id ? (
                              <LoaderCircle size={15} className="animate-spin" />
                            ) : (
                              <Trash2 size={15} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {isModalOpen ? (
        <Modal
          title="Создать лендинг"
          description="Выберите домен, slug, ref-ссылку и тип прокладки."
          onClose={() => {
            if (!isSavingLander) {
              setIsModalOpen(false)
            }
          }}
          maxWidthClassName="max-w-2xl"
        >
          <form className="space-y-4" onSubmit={handleSaveLander}>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">Название</span>
              <input
                value={form.name}
                onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                placeholder="FB ES Telegram prelander"
                maxLength={255}
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Домен</span>
                <select
                  value={form.domainId}
                  onChange={(event) => setForm((current) => ({ ...current, domainId: event.target.value }))}
                  required
                  className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                >
                  <option value="">Выберите домен</option>
                  {domains.map((domain) => (
                    <option key={domain.id} value={domain.id}>
                      {domain.domain_name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Тип прокладки</span>
                <select
                  value={form.type}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      type: event.target.value as LanderType,
                      zipFile: event.target.value === 'custom_upload' ? current.zipFile : null,
                    }))
                  }
                  className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                >
                  <option value="default_tg_redirect">Дефолтный ТГ-перегон</option>
                  <option value="custom_upload">Кастомный HTML (ZIP архив)</option>
                </select>
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">
                  Slug (Путь ссылки)
                </span>
                <input
                  value={form.slug}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      slug: normalizeSlugInput(event.target.value),
                    }))
                  }
                  placeholder="0ZZVaOfQad"
                  required
                  maxLength={100}
                  className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
                <span className="mt-1 block text-xs text-zinc-500">
                  Только латиница, цифры, дефис и подчёркивание.
                </span>
              </label>
              <button
                type="button"
                onClick={() => setForm((current) => ({ ...current, slug: generateSlug() }))}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-200 transition hover:border-emerald-500/50 hover:text-emerald-200"
              >
                <RefreshCw size={15} />
                Сгенерировать
              </button>
            </div>

            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Целевая ссылка баера
              </span>
              <select
                value={form.trackingLinkId}
                onChange={(event) => setForm((current) => ({ ...current, trackingLinkId: event.target.value }))}
                required
                className="w-full rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
              >
                <option value="">Выберите tracking link</option>
                {trackingLinks.map((link) => (
                  <option key={link.id} value={link.id}>
                    {link.title} · {link.code}
                  </option>
                ))}
              </select>
            </label>

            {form.type === 'custom_upload' ? (
              <label className="block rounded-lg border border-dashed border-white/10 bg-white/[0.02] p-4">
                <span className="flex items-center gap-2 text-sm font-medium text-zinc-300">
                  <Upload size={16} />
                  ZIP-архив
                </span>
                <input
                  type="file"
                  accept=".zip,application/zip,application/x-zip-compressed"
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      zipFile: event.target.files?.[0] ?? null,
                    }))
                  }
                  className="mt-3 block w-full text-sm text-zinc-400 file:mr-4 file:rounded-lg file:border-0 file:bg-emerald-500 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-zinc-950 hover:file:bg-emerald-400"
                />
                <span className="mt-2 block text-xs text-zinc-500">
                  В архиве должен быть файл index.html на верхнем уровне.
                </span>
                {form.zipFile ? (
                  <span className="mt-2 block text-sm text-emerald-200">
                    Выбран файл: {form.zipFile.name}
                  </span>
                ) : null}
              </label>
            ) : null}

            <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                disabled={isSavingLander}
                className="inline-flex h-10 items-center justify-center rounded-lg border border-white/10 px-4 text-sm font-semibold text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isSavingLander}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSavingLander ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  )
}

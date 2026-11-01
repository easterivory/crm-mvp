import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import {
  Plus,
  Save,
  RefreshCw,
  Square,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
} from 'lucide-react'
import axios from 'axios'
import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'
import ContentStep from '../features/broadcasts/components/ContentStep'
import PhonePreview from '../features/broadcasts/components/PhonePreview'
import { uploadBroadcastMedia } from '../features/broadcasts/api'
import type { BroadcastContent } from '../features/broadcasts/types'

type Config = {
  name: string
  enabled: boolean
  bot_ids: string[]
  protected_tag_ids: string[]
  audience_tag_id: string | null
  timeout_minutes: number
}
type Slot = {
  id?: string
  name: string
  enabled: boolean
  position: number
  delay_minutes: number
  revision?: number
  content_json: BroadcastContent
}
type Option = {
  id: string
  name: string
  username?: string
  transport_type?: string
}
type Participant = {
  id: string
  chat_id: string
  contact_name?: string
  telegram_id?: string
  status: string
  started_at: string | null
  due_at: string | null
  reason: string | null
}
type Delivery = {
  id: string
  position: number
  status: string
  revision: number | null
  sent_at: string | null
  error: string | null
}
type Audit = {
  id: string
  created_at: string
  event: string
  details: Record<string, unknown>
}
type Report = {
  cohort_counts: Record<string, number>
  slots: { slot_id: string; name: string; status: string; count: number }[]
  sources: {
    tracking_link_id: string | null
    count: number
    name?: string
    code?: string
  }[]
}
const defaults: Config = {
  name: 'Основной',
  enabled: false,
  bot_ids: [],
  protected_tag_ids: [],
  audience_tag_id: null,
  timeout_minutes: 180,
}
const labels: Record<string, string> = {
  waiting: 'Основная воронка',
  active: 'Реклама',
  completed: 'Слоты завершены',
  protected: 'Защищён',
  stopped: 'Остановлен',
  returned: 'Вернулся в основную',
  pending: 'В очереди',
  sending: 'Отправляется',
  sent: 'Отправлен',
  uncertain: 'Доставка не подтверждена',
  skipped: 'Пропущен',
  cancelled: 'Отменён',
  failed: 'Ошибка',
}
const input =
  'w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm'
const button =
  'inline-flex items-center justify-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-sm disabled:opacity-40'
const dateText = (value: string | null) =>
  value
    ? new Date(value).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })
    : '—'
const today = () =>
  new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow' }).format(
    new Date(),
  )

export default function AdvertisingPage(props: { tracking?: boolean }) {
  const { selectedProjectId } = useProjectBotSelection()
  const { pathname, search } = useLocation()
  const [, setSearch] = useSearchParams()
  const previousProject = useRef(selectedProjectId)
  useEffect(() => {
    if (previousProject.current && previousProject.current !== selectedProjectId) setSearch({}, { replace: true })
    previousProject.current = selectedProjectId
  }, [selectedProjectId, setSearch])
  return (
    <AdvertisingPageContent
      key={`${selectedProjectId}:${pathname}:${search}`}
      initialSettings={pathname === '/settings/advertising'}
      {...props}
    />
  )
}

function AdvertisingPageContent({
  tracking = false,
  initialSettings = false,
}: {
  tracking?: boolean
  initialSettings?: boolean
}) {
  const { selectedProjectId } = useProjectBotSelection()
  const [search, setSearch] = useSearchParams()
  const scenarioId = search.get('scenario_id') || selectedProjectId
  const scenarioQuery = `?scenario_id=${scenarioId}`
  const [scenarios, setScenarios] = useState<{ id: string; name: string; enabled: boolean; bot_ids: string[] }[]>([])
  const [newName, setNewName] = useState('')
  const superAdmin = useAuthStore((s) => s.user?.role_name === 'super_admin')
  const [config, setConfig] = useState<Config>(defaults)
  const [slots, setSlots] = useState<Slot[]>([])
  const [draft, setDraft] = useState<Slot | null>(null)
  const [bots, setBots] = useState<Option[]>([])
  const [tags, setTags] = useState<Option[]>([])
  const [participants, setParticipants] = useState<Participant[]>([])
  const [deliveries, setDeliveries] = useState<Delivery[] | null>(null)
  const [logs, setLogs] = useState<Audit[]>([])
  const [tab, setTab] = useState('slots')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)
  const [loading, setLoading] = useState(true)
  const [enabledOnServer, setEnabledOnServer] = useState(false)
  const [notice, setNotice] = useState('')
  const [urls, setUrls] = useState<Record<string, string>>({})
  const urlsRef = useRef<Record<string, string>>({})
  const [offset, setOffset] = useState(0)
  const [before, setBefore] = useState(today())
  const [stopMain, setStopMain] = useState(true)
  const [startSlots, setStartSlots] = useState(false)
  const [preview, setPreview] = useState<{
    preview_id: string
    count: number
    sample_chat_ids: string[]
  } | null>(null)
  const [confirm, setConfirm] = useState('')
  const [start, setStart] = useState(today())
  const [end, setEnd] = useState(today())
  const [botFilter, setBotFilter] = useState('')
  const [report, setReport] = useState<Report | null>(null)
  const [token, setToken] = useState('')
  const [botEnabled, setBotEnabled] = useState(false)
  const [botName, setBotName] = useState('')
  const params = { project_id: selectedProjectId, scenario_id: scenarioId }
  const generation = useRef(0)
  const act = async (work: () => Promise<void>) => {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await work()
    } catch (e) {
      setError(
        axios.isAxiosError(e)
          ? typeof e.response?.data?.detail === 'string'
            ? e.response.data.detail
            : 'Не удалось выполнить запрос'
          : String(e),
      )
    } finally {
      setBusy(false)
    }
  }
  const load = useCallback(async () => {
    const current = ++generation.current
    setReady(false)
    setLoading(true)
    setError('')
    setDraft(null)
    setPreview(null)
    setReport(null)
    setDeliveries(null)
    setOffset(0)
    if (!selectedProjectId) {
      setLoading(false)
      return
    }
    let resource = 'настройки сценария'
    try {
      const p = { project_id: selectedProjectId, scenario_id: scenarioId }
      const list = await api.get('/advertising/scenarios', { params: p })
      const cfg = await api.get('/advertising/settings', { params: p })
      resource = 'слоты'
      const s = await api.get('/advertising/slots', { params: p })
      const options = async (path: string): Promise<Option[]> => {
        const result: Option[] = []
        for (let offset = 0; ; offset += 100) {
          const response = await api.get(path, {
            params: { ...p, limit: 100, offset },
          })
          if (current !== generation.current) return []
          const page: Option[] = response.data.items ?? response.data
          result.push(...page)
          if (page.length < 100 || result.length >= response.data.total) break
        }
        return result
      }
      resource = 'список ботов'
      const b = await options('/bots')
      resource = 'теги проекта'
      const t = await options('/tags')
      if (current !== generation.current) return
      setConfig(cfg.data)
      setScenarios(list.data)
      setEnabledOnServer(cfg.data.enabled)
      setSlots(s.data)
      setBots(b.filter((x: Option) => x.transport_type !== 'user_mtproto'))
      setTags(t)
      setError('')
      setReady(true)
      setTab(initialSettings || !cfg.data.enabled ? 'settings' : 'slots')
    } catch (e) {
      if (current === generation.current)
        setError(
          axios.isAxiosError(e) && typeof e.response?.data?.detail === 'string'
            ? e.response.data.detail
            : axios.isAxiosError(e) && (!e.response || e.response.status >= 500)
              ? `Не удалось загрузить ${resource}: API недоступен или вернул ошибку. Проверьте запуск серверной части и миграцию 0091.`
              : `Не удалось загрузить ${resource}${axios.isAxiosError(e) && e.response ? ` (HTTP ${e.response.status})` : ''}`,
        )
    } finally {
      if (current === generation.current) setLoading(false)
    }
  }, [selectedProjectId, initialSettings, scenarioId])
  useEffect(() => {
    void load()
    return () => {
      generation.current++
    }
  }, [load])
  useEffect(
    () => () => {
      Object.values(urlsRef.current).forEach(URL.revokeObjectURL)
    },
    [],
  )
  useEffect(() => {
    setPreview(null)
    setConfirm('')
  }, [before, stopMain, startSlots])
  const previewUploadId = draft?.content_json.messages[0]?.media?.upload_id
  useEffect(() => {
    if (!previewUploadId || urlsRef.current[previewUploadId]) return
    const controller = new AbortController()
    void api
      .get(`/advertising/media/${previewUploadId}`, {
        params: { project_id: selectedProjectId },
        responseType: 'blob',
        signal: controller.signal,
      })
      .then((r) => {
        if (controller.signal.aborted) return
        const url = URL.createObjectURL(r.data)
        urlsRef.current[previewUploadId] = url
        setUrls((prev) => ({ ...prev, [previewUploadId]: url }))
      })
      .catch(() => {})
    return () => controller.abort()
  }, [previewUploadId, selectedProjectId])
  const loadPeople = async (next = offset) => {
    const r = await api.get('/advertising/participants', {
      params: { ...params, offset: next },
    })
    setParticipants(r.data)
    setOffset(next)
    setDeliveries(null)
  }
  const showReport = async () => {
    const until = new Date(`${end}T00:00:00+03:00`)
    until.setTime(until.getTime() + 86400000)
    const r = await api.get('/advertising/tracking', {
      params: {
        ...params,
        start: `${start}T00:00:00+03:00`,
        end: until.toISOString(),
        bot_id: botFilter || undefined,
      },
    })
    setReport(r.data)
  }
  const options = () => ({
    created_before: `${before}T00:00:00+03:00`,
    stop_main: stopMain,
    start_slots: startSlots,
  })
  if (!selectedProjectId) return <p className="p-6">Выберите проект</p>
  return (
    <section className="h-full overflow-auto p-4 text-gray-100 md:p-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">
          {tracking ? 'Трекинг рекламы' : 'Рекламный сценарий'}
        </h1>
        <div className="flex gap-2">
          {!tracking && (
            <Link className={button} to={`/settings/advertising${scenarioQuery}`}>
              <SlidersHorizontal size={16} />
              Настройки сценария
            </Link>
          )}
          <Link
            className={button}
            to={`${tracking ? '/advertising' : '/tracking/advertising'}${scenarioQuery}`}
          >
            {tracking ? 'Сценарий' : 'Статистика'}
          </Link>
          <button
            className={button}
            title="Обновить"
            disabled={busy}
            onClick={() => void act(load)}
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </header>
      {ready && <div className="mb-5 flex flex-wrap items-end gap-3">
        <label className="min-w-0 w-full sm:w-80">Сценарий
          <select aria-label="Сценарий" className={input} value={scenarioId || ''} disabled={busy}
            onChange={(e) => setSearch({ scenario_id: e.target.value })}>
            {scenarios.map(s => <option key={s.id} value={s.id}>{s.name}{s.enabled ? '' : ' · выключен'}</option>)}
          </select>
        </label>
        {!tracking && <>
          <input aria-label="Название нового сценария" placeholder="Новый сценарий" className={`${input} sm:!w-64`}
            maxLength={255} value={newName} onChange={e => setNewName(e.target.value)} />
          <button className={button} disabled={busy || !newName.trim()} onClick={() => void act(async () => {
            const r = await api.post('/advertising/scenarios', { name: newName.trim() }, { params })
            setSearch({ scenario_id: r.data.id })
          })}><Plus size={16} />Создать сценарий</button>
        </>}
      </div>}
      {ready && !tracking && (
        <p
          className={`mb-4 text-sm ${enabledOnServer ? 'text-emerald-300' : 'text-gray-400'}`}
        >
          {enabledOnServer ? 'Сценарий включён' : 'Сценарий выключен'}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="mb-4 rounded-lg border border-red-400/30 p-3 text-red-200"
        >
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mb-4 text-emerald-300">
          {notice}
        </p>
      )}
      {!ready ? (
        loading ? (
          <p role="status">Загрузка…</p>
        ) : (
          <button
            className={button}
            disabled={busy}
            onClick={() => void act(load)}
          >
            <RefreshCw size={16} />
            Повторить загрузку
          </button>
        )
      ) : tracking ? (
        <>
          <div className="mb-5 flex flex-wrap gap-3">
            <label>
              С
              <input
                className={input}
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              По
              <input
                className={input}
                type="date"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            <label>
              Бот
              <select
                className={input}
                value={botFilter}
                onChange={(e) => setBotFilter(e.target.value)}
              >
                <option value="">Все боты</option>
                {bots.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              className={button}
              disabled={busy}
              onClick={() => void act(showReport)}
            >
              Рассчитать
            </button>
          </div>
          <p className="mb-4 text-sm text-gray-400">
            Участники, зарегистрированные в выбранный период · МСК
          </p>
          {report && (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                {Object.entries(report.cohort_counts).map(([k, v]) => (
                  <div key={k} className="border-b border-white/15 py-4">
                    <p className="text-sm text-gray-400">{labels[k] || k}</p>
                    <strong className="text-2xl">{v}</strong>
                  </div>
                ))}
              </div>
              <h2 className="my-4 font-semibold">Отправки по слотам</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr>
                      <th>Слот</th>
                      <th>Результат</th>
                      <th>Количество</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.slots.map((s) => (
                      <tr
                        key={`${s.slot_id}:${s.status}`}
                        className="border-b border-white/10"
                      >
                        <td className="py-3">{s.name}</td>
                        <td>{labels[s.status] || s.status}</td>
                        <td>{s.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h2 className="my-4 font-semibold">
                Первоначальный источник участников
              </h2>
              {report.sources.map((s) => (
                <div
                  key={s.tracking_link_id || 'none'}
                  className="flex justify-between gap-4 border-b border-white/10 py-3 text-sm"
                >
                  <span className="break-all">
                    {s.tracking_link_id
                      ? s.name || s.code || s.tracking_link_id
                      : 'Без рекламной ссылки'}
                  </span>
                  <strong>{s.count}</strong>
                </div>
              ))}
            </>
          )}
        </>
      ) : (
        <>
          <nav className="mb-5 flex flex-wrap gap-2">
            {[
              ['slots', 'Слоты'],
              ['settings', 'Настройки'],
              ['participants', 'Участники'],
              ['backfill', 'Старая база'],
              ['log', 'Журнал'],
              ...(superAdmin ? [['bot', 'Telegram-бот']] : []),
            ]
              .filter(
                ([key]) =>
                  config.enabled || key === 'settings' || key === 'bot',
              )
              .map(([key, label]) => (
                <button
                  className={`${button} ${tab === key ? 'bg-emerald-500/20 text-emerald-200' : ''}`}
                  key={key}
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      setTab(key)
                      if (key === 'participants') await loadPeople(0)
                      if (key === 'log')
                        setLogs(
                          (await api.get('/advertising/log', { params })).data,
                        )
                      if (key === 'bot') {
                        const r = await api.get('/advertising/bot')
                        setBotEnabled(r.data.enabled)
                        setBotName(r.data.username || '')
                      }
                    })
                  }
                >
                  {label}
                </button>
              ))}
          </nav>
          {(tab === 'settings' || (!config.enabled && tab !== 'bot')) && (
            <div className="max-w-3xl space-y-5">
              <label className="block">Название сценария
                <input className={input} maxLength={255} value={config.name || ''}
                  onChange={e => setConfig({ ...config, name: e.target.value })} />
              </label>
              <label className="flex gap-3">
                <input
                  type="checkbox"
                  checked={config.enabled}
                  onChange={(e) =>
                    setConfig({ ...config, enabled: e.target.checked })
                  }
                />
                Рекламный сценарий включён
              </label>
              <label className="block">
                Переход через, минут
                <input
                  type="number"
                  min="1"
                  max="43200"
                  className={input}
                  value={config.timeout_minutes}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      timeout_minutes: Number(e.target.value),
                    })
                  }
                />
              </label>
              <fieldset>
                <legend className="mb-2">Боты</legend>
                <div className="flex flex-wrap gap-4">
                  {bots.map((b) => (
                    <label key={b.id} className="flex gap-2">
                      <input
                        type="checkbox"
                        checked={config.bot_ids.includes(b.id)}
                        disabled={scenarios.some(s => s.id !== scenarioId && s.bot_ids.includes(b.id))}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            bot_ids: e.target.checked
                              ? [...config.bot_ids, b.id]
                              : config.bot_ids.filter((id) => id !== b.id),
                          })
                        }
                      />
                      {b.name}
                      {scenarios.filter(s => s.id !== scenarioId && s.bot_ids.includes(b.id)).map(s =>
                        <span className="text-gray-400" key={s.id}> · {s.name}</span>)}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset>
                <legend className="mb-2">Защищённые теги</legend>
                <div className="flex flex-wrap gap-4">
                  {tags.map((t) => (
                    <label key={t.id} className="flex gap-2">
                      <input
                        type="checkbox"
                        checked={config.protected_tag_ids.includes(t.id)}
                        onChange={(e) =>
                          setConfig({
                            ...config,
                            protected_tag_ids: e.target.checked
                              ? [...config.protected_tag_ids, t.id]
                              : config.protected_tag_ids.filter(
                                  (id) => id !== t.id,
                                ),
                          })
                        }
                      />
                      {t.name}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="block">
                Тег рекламной аудитории
                <select
                  className={input}
                  value={config.audience_tag_id || ''}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      audience_tag_id: e.target.value || null,
                    })
                  }
                >
                  <option value="">Выберите тег</option>
                  {tags.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className={button}
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const previous = scenarios.find(s => s.id === scenarioId)
                    if (previous?.bot_ids.some(id => !config.bot_ids.includes(id)) && !window.confirm(
                      'Убраны боты из сценария. Их незавершённые очереди остановятся при обработке и не перенесутся в другой сценарий. Сохранить?',
                    )) return
                    await api.put('/advertising/settings', config, { params })
                    setScenarios((await api.get('/advertising/scenarios', { params })).data)
                    setEnabledOnServer(config.enabled)
                    window.dispatchEvent(new Event('advertising-settings'))
                    setNotice(
                      'Настройки сохранены. Старая база не обрабатывается автоматически.',
                    )
                  })
                }
              >
                <Save size={16} />
                Сохранить настройки
              </button>
            </div>
          )}
          {config.enabled && tab === 'slots' && (
            <>
              <div className="mb-4 flex flex-wrap gap-2">
                {slots.map((s, i) => (
                  <button
                    className={button}
                    key={s.id}
                    disabled={busy}
                    onClick={() => setDraft(structuredClone(s))}
                  >
                    #{i + 1} {s.name}
                    {s.enabled ? '' : ' · выключен'}
                  </button>
                ))}
                <button
                  className={button}
                  onClick={() =>
                    setDraft({
                      name: `Слот ${slots.length + 1}`,
                      enabled: false,
                      position: slots.length,
                      delay_minutes: 120,
                      content_json: {
                        type: 'message',
                        messages: [{ type: 'text', text: '', buttons: [] }],
                      },
                    })
                  }
                >
                  <Plus size={16} />
                  Слот
                </button>
              </div>
              {draft && (
                <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
                  <div className="min-w-0 space-y-4">
                    <label className="block">
                      Название
                      <input
                        className={input}
                        value={draft.name}
                        onChange={(e) =>
                          setDraft({ ...draft, name: e.target.value })
                        }
                      />
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <label>
                        Позиция
                        <input
                          className={input}
                          type="number"
                          min="0"
                          value={draft.position}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              position: Number(e.target.value),
                            })
                          }
                        />
                      </label>
                      <label>
                        Интервал, мин.
                        <input
                          className={input}
                          type="number"
                          min="1"
                          value={draft.delay_minutes}
                          onChange={(e) =>
                            setDraft({
                              ...draft,
                              delay_minutes: Number(e.target.value),
                            })
                          }
                        />
                      </label>
                    </div>
                    <label className="flex gap-2">
                      <input
                        type="checkbox"
                        checked={draft.enabled}
                        onChange={(e) =>
                          setDraft({ ...draft, enabled: e.target.checked })
                        }
                      />
                      Активный слот
                    </label>
                    <ContentStep
                      urlOnly
                      content={draft.content_json}
                      botId={null}
                      funnels={[]}
                      snippets={[]}
                      mediaPreviewUrls={urls}
                      onChange={(content) =>
                        setDraft({ ...draft, content_json: content })
                      }
                      onSnippetSelected={() => {}}
                      onMediaPreview={(id, url) => {
                        urlsRef.current[id] = url
                        setUrls((prev) => ({ ...prev, [id]: url }))
                      }}
                      onUploadMedia={(file, type) =>
                        uploadBroadcastMedia(selectedProjectId, file, type)
                      }
                    />
                    <button
                      className={button}
                      disabled={busy}
                      onClick={() =>
                        void act(async () => {
                          const {
                            id,
                            name,
                            enabled,
                            position,
                            delay_minutes,
                            revision,
                            content_json,
                          } = draft
                          const body = {
                            name,
                            enabled,
                            position,
                            delay_minutes,
                            revision,
                            content_json,
                          }
                          const r = id
                            ? await api.put(`/advertising/slots/${id}`, body, {
                                params,
                              })
                            : await api.post('/advertising/slots', body, {
                                params,
                              })
                          setDraft(r.data)
                          setSlots(
                            (await api.get('/advertising/slots', { params }))
                              .data,
                          )
                          setNotice('Слот сохранён')
                        })
                      }
                    >
                      <Save size={16} />
                      Сохранить слот
                    </button>
                  </div>
                  <PhonePreview
                    content={draft.content_json}
                    mediaPreviewUrls={urls}
                  />
                </div>
              )}
            </>
          )}
          {config.enabled && tab === 'participants' && (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr>
                      <th>Чат</th>
                      <th>Состояние</th>
                      <th>Следующая отправка · МСК</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {participants.map((p) => (
                      <tr className="border-b border-white/10" key={p.id}>
                        <td className="max-w-48 break-all py-3">
                          <button
                            onClick={() =>
                              void act(async () =>
                                setDeliveries(
                                  (
                                    await api.get(
                                      `/advertising/participants/${p.id}/deliveries`,
                                      { params },
                                    )
                                  ).data,
                                ),
                              )
                            }
                          >
                            {p.contact_name || p.telegram_id || p.chat_id}
                            {p.contact_name && p.telegram_id && (
                              <span className="block text-xs text-gray-400">
                                ID {p.telegram_id}
                              </span>
                            )}
                          </button>
                        </td>
                        <td>
                          {labels[p.status] || p.status}
                          <div className="text-xs text-gray-400">
                            {p.reason}
                          </div>
                        </td>
                        <td>{dateText(p.due_at)}</td>
                        <td>
                          <button
                            title="Остановить рекламу"
                            className={button}
                            disabled={
                              busy || !['active', 'waiting'].includes(p.status)
                            }
                            onClick={() =>
                              void act(async () => {
                                await api.post(
                                  `/advertising/participants/${p.id}/stop`,
                                  {},
                                  { params },
                                )
                                await loadPeople()
                              })
                            }
                          >
                            <Square size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="my-3 flex gap-2">
                <button
                  className={button}
                  disabled={busy || offset === 0}
                  onClick={() =>
                    void act(() => loadPeople(Math.max(0, offset - 50)))
                  }
                  title="Назад"
                >
                  <ChevronLeft size={16} />
                </button>
                <button
                  className={button}
                  disabled={busy || participants.length < 50}
                  onClick={() => void act(() => loadPeople(offset + 50))}
                  title="Далее"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
              {deliveries && (
                <div>
                  {deliveries.map((d) => (
                    <div
                      className="border-b border-white/10 py-2 text-sm"
                      key={d.id}
                    >
                      #{d.position + 1} · {labels[d.status] || d.status} ·
                      версия {d.revision ?? '—'} · {dateText(d.sent_at)}
                      <p className="text-amber-200">{d.error}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          {config.enabled && tab === 'backfill' && (
            <div className="max-w-xl space-y-4">
              <label className="block">
                Чаты, созданные до (МСК)
                <input
                  className={input}
                  type="date"
                  value={before}
                  onChange={(e) => setBefore(e.target.value)}
                />
              </label>
              <label className="flex gap-2">
                <input
                  type="checkbox"
                  checked={stopMain}
                  onChange={(e) => {
                    setStopMain(e.target.checked)
                    if (!e.target.checked) setStartSlots(false)
                  }}
                />
                Остановить основную воронку и дожимы
              </label>
              <label className="flex gap-2">
                <input
                  type="checkbox"
                  disabled={!stopMain}
                  checked={startSlots}
                  onChange={(e) => setStartSlots(e.target.checked)}
                />
                Запустить рекламные слоты
              </label>
              <button
                className={button}
                disabled={busy}
                onClick={() =>
                  void act(async () =>
                    setPreview(
                      (
                        await api.post(
                          '/advertising/backfill/preview',
                          options(),
                          { params },
                        )
                      ).data,
                    ),
                  )
                }
              >
                Проверить аудиторию
              </button>
              {preview && (
                <>
                  <p>
                    Подходящих карточек: <strong>{preview.count}</strong>
                  </p>
                  <details>
                    <summary>Примеры карточек</summary>
                    {preview.sample_chat_ids.map((id) => (
                      <p className="break-all text-sm" key={id}>
                        {id}
                      </p>
                    ))}
                  </details>
                  <label className="block">
                    Подтверждение: ЗАПУСТИТЬ
                    <input
                      className={input}
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                    />
                  </label>
                  <button
                    className={button}
                    disabled={busy || confirm !== 'ЗАПУСТИТЬ'}
                    onClick={() =>
                      void act(async () => {
                        const r = await api.post(
                          '/advertising/backfill/start',
                          {
                            ...options(),
                            preview_id: preview.preview_id,
                            confirmation: confirm,
                          },
                          { params },
                        )
                        setPreview(null)
                        setNotice(
                          `Прогон поставлен в очередь: ${r.data.run_id}. Результат в журнале.`,
                        )
                      })
                    }
                  >
                    Запустить прогон
                  </button>
                </>
              )}
            </div>
          )}
          {config.enabled && tab === 'log' && (
            <div>
              {logs.map((l) => (
                <details key={l.id} className="border-b border-white/10 py-3">
                  <summary>
                    {dateText(l.created_at)} · {l.event}
                  </summary>
                  <pre className="whitespace-pre-wrap break-all text-xs text-gray-400">
                    {JSON.stringify(l.details, null, 2)}
                  </pre>
                </details>
              ))}
            </div>
          )}
          {superAdmin && tab === 'bot' && (
            <div className="max-w-xl space-y-4">
              <p>{botName ? `@${botName}` : 'Отдельный бот не подключён'}</p>
              <label className="block">
                Токен
                <input
                  type="password"
                  autoComplete="new-password"
                  className={input}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                />
              </label>
              <label className="flex gap-2">
                <input
                  type="checkbox"
                  checked={botEnabled}
                  onChange={(e) => setBotEnabled(e.target.checked)}
                />
                Бот включён
              </label>
              <button
                className={button}
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const r = await api.patch('/advertising/bot', {
                      enabled: botEnabled,
                      token: token || null,
                    })
                    setToken('')
                    setBotName(r.data.username || '')
                    setNotice('Настройки бота сохранены')
                  })
                }
              >
                <Save size={16} />
                Сохранить
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}

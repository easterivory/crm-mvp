import { useEffect, useState } from 'react'
import { LoaderCircle, Save } from 'lucide-react'
import axios from 'axios'
import api from '../../api/client'

type Config = { enabled: boolean; has_token: boolean; username: string | null }

export default function InfoBotSettings() {
  const [config, setConfig] = useState<Config>({ enabled: false, has_token: false, username: null })
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    let active = true
    api.get<Config>('/settings/info-bot').then(({ data }) => { if (active) { setConfig(data); setLoaded(true) } })
      .catch(() => { if (active) setError('Не удалось загрузить настройки инфобота') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  async function save() {
    setSaving(true); setSaved(false); setError('')
    try {
      const { data } = await api.patch<Config>('/settings/info-bot', { enabled: config.enabled, token: token.trim() || null })
      setConfig(data); setToken(''); setSaved(true)
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null
      setError(typeof detail === 'string' ? detail : 'Не удалось сохранить инфобота')
    } finally { setSaving(false) }
  }
  return <section className="space-y-4 border-t border-zinc-800 pt-5">
    <h3 className="text-sm font-semibold text-zinc-100">Инфобот статистики</h3>
    {config.username && <a className="text-sm text-cyan-400" href={`https://telegram.me/${config.username}`} target="_blank" rel="noreferrer">@{config.username}</a>}
    <label className="block">
      <span className="mb-1 block text-sm text-zinc-300">Токен отдельного инфобота</span>
      <input type="password" value={token} onChange={event => { setToken(event.target.value); setSaved(false) }}
        disabled={loading || saving} autoComplete="new-password" placeholder={config.has_token ? 'Токен сохранён' : '1234567890:AA...'}
        className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100" />
    </label>
    <label className="flex items-center justify-between gap-3 text-sm text-zinc-300">
      Инфобот включён
      <input type="checkbox" checked={config.enabled} disabled={loading || saving}
        onChange={event => { setConfig({ ...config, enabled: event.target.checked }); setSaved(false) }} className="h-5 w-5 accent-emerald-500" />
    </label>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
    {saved && <p role="status" className="text-sm text-emerald-400">Сохранено</p>}
    <button type="button" onClick={() => void save()} disabled={!loaded || loading || saving}
      className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50">
      {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />} Сохранить инфобота
    </button>
  </section>
}

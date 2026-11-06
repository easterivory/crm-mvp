import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import api from '../../../api/client'

export default function FunnelOfferSettings({ projectId, versionId, readOnly }: { projectId: string; versionId: string | null; readOnly: boolean }) {
  const [offers, setOffers] = useState<{ id: string; name: string; partner_name: string; is_active: boolean }[]>([])
  const [offerId, setOfferId] = useState('')
  const [gambling, setGambling] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => {
    let current = true
    setGambling(false); setError(''); setSaved(false)
    if (!versionId) return
    const params = { project_id: projectId }
    async function load() {
      try {
        const project = await api.get<{ project_format: string }>(`/projects/${projectId}`)
        if (!current || project.data.project_format !== 'gambling') return
        const [list, selected] = await Promise.all([api.get<typeof offers>('/gambling-offers', { params }),
          api.get<{ offer_id: string | null }>(`/gambling-offers/funnel-versions/${versionId}`, { params })])
        if (current) { setGambling(true); setOffers(list.data); setOfferId(selected.data.offer_id ?? '') }
      } catch { if (current) setError('Не удалось загрузить оффер воронки') }
    }
    void load()
    return () => { current = false }
  }, [projectId, versionId])
  async function save() {
    if (!versionId) return
    setBusy(true); setError(''); setSaved(false)
    try {
      await api.put(`/gambling-offers/funnel-versions/${versionId}`, { offer_id: offerId || null }, { params: { project_id: projectId } })
      setSaved(true)
    } catch { setError('Не удалось сохранить оффер. Проверьте доступность оффера и статус черновика.') }
    finally { setBusy(false) }
  }
  if (!gambling && !error) return null
  return <section className="min-w-0 space-y-3 border-b border-white/10 p-4" aria-label="Оффер воронки">
    <label className="grid gap-2 text-sm text-gray-200">Оффер
      <select disabled={readOnly || busy} className="min-w-0 rounded-md border border-white/15 bg-[#14151b] px-3 py-2" value={offerId} onChange={e => { setOfferId(e.target.value); setSaved(false) }}>
        <option value="">Не выбран</option>{offers.filter(o => o.is_active || o.id === offerId).map(o => <option key={o.id} value={o.id}>{o.name} · {o.partner_name}{o.is_active ? '' : ' · отключён'}</option>)}
      </select>
    </label>
    {!readOnly && <button disabled={busy} onClick={() => void save()} className="inline-flex min-h-9 items-center gap-2 rounded-md border border-white/15 px-3 py-2 text-sm text-gray-200 disabled:opacity-50"><Save size={16} />{saved ? 'Сохранено' : 'Сохранить оффер'}</button>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </section>
}

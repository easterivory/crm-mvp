import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import api from '../../../api/client'
import TrackingStepPreview, { stepLabel, type JourneyStepOption } from '../../tracking/TrackingStepPreview'

type Rules = { enabled: boolean; tag_ids: string[]; step_ids: string[] }
const empty: Rules = { enabled: false, tag_ids: [], step_ids: [] }

export default function PriorityChatSettings({ projectId }: { projectId: string }) {
  const [rules, setRules] = useState<Rules>(empty)
  const [tags, setTags] = useState<{ id: string; name: string }[]>([])
  const [steps, setSteps] = useState<JourneyStepOption[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setLoaded(false); setError(''); setSaved(false)
    void (async () => {
      const project = await api.get<{ priority_chat_rules: Partial<Rules> }>(`/projects/${projectId}`, { signal: controller.signal })
      const collected: { id: string; name: string }[] = []
      let total = Infinity
      while (collected.length < total) {
        const { data } = await api.get<{ items: typeof collected; total: number }>('/tags', {
          params: { project_id: projectId, limit: 100, offset: collected.length }, signal: controller.signal })
        total = data.total
        if (!data.items.length) break
        collected.push(...data.items)
      }
      const options = await api.get<JourneyStepOption[]>('/tracking/metrics/step-options', {
        params: { project_id: projectId, include_equivalent_ids: true }, signal: controller.signal })
      if (!controller.signal.aborted) {
        setRules({ ...empty, ...project.data.priority_chat_rules }); setTags(collected); setSteps(options.data); setLoaded(true)
      }
    })().catch(() => { if (!controller.signal.aborted) setError('Не удалось загрузить правила') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [projectId, retry])
  const toggle = (key: 'tag_ids' | 'step_ids', id: string) => {
    setSaved(false)
    setRules(current => ({ ...current, [key]: current[key].includes(id) ? current[key].filter(value => value !== id) : [...current[key], id] }))
  }
  const save = async () => {
    setSaving(true); setError(''); setSaved(false)
    try {
      const { data } = await api.patch<{ priority_chat_rules: Rules }>(`/projects/${projectId}`, { priority_chat_rules: rules })
      setRules(data.priority_chat_rules); setSaved(true)
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось сохранить правила')
    } finally { setSaving(false) }
  }
  const stepSelected = (step: JourneyStepOption) => (step.equivalent_step_ids || [step.id]).some(id => rules.step_ids.includes(id))
  const toggleStep = (step: JourneyStepOption) => {
    const ids = new Set(step.equivalent_step_ids || [step.id])
    const selected = stepSelected(step)
    setSaved(false)
    setRules(current => ({ ...current, step_ids: [...current.step_ids.filter(id => !ids.has(id)), ...(selected ? [] : [step.id])] }))
  }
  const needle = search.trim().toLocaleLowerCase()
  return <section className="space-y-3 border-y border-zinc-800 py-4">
    <label className="flex items-center justify-between gap-3 text-sm font-semibold text-zinc-100">
      Приоритетные чаты
      <input type="checkbox" checked={rules.enabled} disabled={!loaded || loading || saving}
        onChange={event => { setSaved(false); setRules(current => ({ ...current, enabled: event.target.checked })) }} />
    </label>
    {loading ? <p role="status">Загрузка…</p> : <>
      <input aria-label="Поиск тегов и шагов приоритета" placeholder="Поиск тега или шага" value={search}
        onChange={event => setSearch(event.target.value)} className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm" />
      <fieldset disabled={!loaded || saving} className="space-y-2"><legend className="mb-2 text-sm text-zinc-300">Теги · любой из выбранных</legend>
        <div className="grid max-h-48 grid-cols-2 gap-2 overflow-y-auto">
          {tags.filter(tag => tag.name.toLocaleLowerCase().includes(needle)).map(tag => <label key={tag.id} className="flex min-w-0 items-center gap-2 text-sm">
            <input type="checkbox" checked={rules.tag_ids.includes(tag.id)} onChange={() => toggle('tag_ids', tag.id)} />
            <span className="break-words">{tag.name}</span></label>)}
        </div>
      </fieldset>
      <fieldset disabled={!loaded || saving}><legend className="mb-2 text-sm text-zinc-300">Достигнутые шаги · любой из выбранных</legend>
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {steps.filter(step => stepLabel(step).toLocaleLowerCase().includes(needle)).map(step => <div key={step.id} className="flex items-center gap-2">
            <label className="flex min-w-0 flex-1 items-start gap-2 text-xs"><input type="checkbox" checked={stepSelected(step)}
              onChange={() => toggleStep(step)} /><span className="break-words">{stepLabel(step)}</span></label>
            <TrackingStepPreview projectId={projectId} step={step} />
          </div>)}
        </div>
      </fieldset>
      <button type="button" disabled={!loaded || saving || rules.enabled && !rules.tag_ids.length && !rules.step_ids.length}
        onClick={() => void save()} className="inline-flex items-center gap-2 rounded-md border border-zinc-700 px-3 py-2 text-sm disabled:opacity-40">
        <Save size={16} />{saving ? 'Сохранение…' : 'Сохранить приоритеты'}</button>
      {saved && <p role="status" className="text-sm text-emerald-300">Правила сохранены</p>}
    </>}
    {error && <p role="alert" className="text-sm text-red-300">{error} <button type="button" className="underline" onClick={() => setRetry(n => n + 1)}>Повторить загрузку</button></p>}
  </section>
}

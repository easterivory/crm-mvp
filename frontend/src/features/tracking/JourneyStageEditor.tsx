import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Plus, Save, Trash2, X } from 'lucide-react'
import api from '../../api/client'

export type Stage = { id: string; name: string; source: 'start' | 'entered' | 'answered' | 'tag';
  step_keys: string[]; step_refs: { funnel_id: string; key: string }[]; tag_ids: string[]; role: 'regular' | 'offer' | 'outcome' }
export type JourneyConfig = { stages: Stage[]; idle_hours: number; scope: 'bot' | 'funnel' }
export type Catalogue = { config: JourneyConfig | null; can_edit: boolean; has_legacy_tag_snapshot: boolean;
  steps: { funnel_id: string; key: string; name: string }[]; tags: { id: string; name: string }[] }
const makeStage = (name: string, source: Stage['source'], role: Stage['role'] = 'regular'): Stage =>
  ({ id: crypto.randomUUID(), name, source, role, step_keys: [], step_refs: [], tag_ids: [] })
const emptyConfig = (): JourneyConfig => ({ idle_hours: 24, scope: 'bot',
  stages: [makeStage('Старт', 'start'), makeStage('VIP', 'tag', 'outcome')] })

export default function JourneyStageEditor({ projectId, funnelId, catalogue, onSaved, onClose }: {
  projectId: string; funnelId: string; catalogue: Catalogue; onSaved: () => void; onClose: () => void
}) {
  const [draft, setDraft] = useState<JourneyConfig>(() => catalogue.config ? { ...catalogue.config,
    scope: catalogue.config.scope || 'bot', stages: catalogue.config.stages.map(s => ({ ...s, step_keys: [],
      step_refs: [...(s.step_refs || []), ...(s.step_keys || []).map(key => ({ funnel_id: funnelId, key }))] })) } : emptyConfig())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState<Record<string, string>>({})
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  const change = (index: number, patch: Partial<Stage>) => setDraft(current => ({ ...current,
    stages: current.stages.map((s, i) => i === index ? { ...s, ...patch } : s) }))
  const reorder = (index: number, delta: number) => setDraft(current => {
    const stages = [...current.stages]; [stages[index], stages[index + delta]] = [stages[index + delta], stages[index]]
    return { ...current, stages }
  })
  const save = async () => {
    setSaving(true); setError('')
    const controller = new AbortController(); request.current = controller
    try { await api.put('/tracking/journey/config', draft, { signal: controller.signal, params: { project_id: projectId, funnel_id: funnelId } });
      if (!controller.signal.aborted) onSaved() }
    catch (e: any) { const detail = e.response?.data?.detail
      if (controller.signal.aborted) return
      setError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg).join('; ') : 'Не удалось сохранить этапы') }
    finally { if (!controller.signal.aborted) setSaving(false) }
  }
  return <section className="journey-stage-editor" aria-label="Настройка этапов">
    <div className="tracking-tools"><h3>Этапы и итоговый тег</h3>
      <button type="button" title="Закрыть настройки" aria-label="Закрыть настройки" disabled={saving} onClick={onClose}><X size={17} /></button></div>
    <fieldset disabled={saving}>
      <div className="tracking-journey-filters">
        <label>Охват<select value={draft.scope} onChange={e => setDraft({ ...draft, scope: e.target.value as JourneyConfig['scope'],
          stages: draft.stages.map(s => ({ ...s, step_refs: e.target.value === 'funnel' ? s.step_refs.filter(r => r.funnel_id === funnelId) : s.step_refs })) })}>
          <option value="bot">Весь бот</option><option value="funnel">Только выбранная воронка</option></select></label>
        <label>Долго нет ответа, часов<input type="number" min={1} max={8760} value={draft.idle_hours}
          onChange={e => setDraft({ ...draft, idle_hours: Number(e.target.value) })} /></label>
        <button type="button" onClick={() => setDraft({ ...draft, stages: [makeStage('Старт', 'start'),
          ...['Возраст', 'Гражданство', 'Цели'].map(name => makeStage(name, 'answered')),
          makeStage('Описание', 'entered', 'offer'), makeStage('HOT', 'tag'), makeStage('HOT HOT', 'tag'), makeStage('VIP', 'tag', 'outcome')] })}>Вакансии</button>
      </div>
      {draft.stages.map((stage, index) => <div className="journey-stage-setting" key={stage.id}>
        <div className="tracking-journey-filters"><strong>#{index + 1}</strong>
          <label>Название<input value={stage.name} maxLength={80} onChange={e => change(index, { name: e.target.value })} /></label>
          <label>Основание<select value={stage.source} disabled={!index || stage.role === 'outcome'}
            onChange={e => change(index, { source: e.target.value as Stage['source'], step_keys: [], step_refs: [], tag_ids: [] })}>
            {!index && <option value="start">Первый приход</option>}
            {!!index && <><option value="entered">Вход на шаг</option><option value="answered">Принятый ответ на шаге</option><option value="tag">Присвоение тега</option></>}
          </select></label>
          {!!index && index < draft.stages.length - 1 && <label>Назначение<select value={stage.role}
            onChange={e => change(index, { role: e.target.value as Stage['role'] })}>
            <option value="regular">Обычный этап</option><option value="offer">Ознакомление с предложением</option>
          </select></label>}
          {!!index && index < draft.stages.length - 1 && <div className="tracking-actions">
            <button type="button" title="Выше" aria-label="Этап выше" disabled={index === 1} onClick={() => reorder(index, -1)}><ArrowUp size={16} /></button>
            <button type="button" title="Ниже" aria-label="Этап ниже" disabled={index === draft.stages.length - 2} onClick={() => reorder(index, 1)}><ArrowDown size={16} /></button>
            <button type="button" title="Удалить этап" aria-label="Удалить этап" onClick={() => setDraft({ ...draft, stages: draft.stages.filter(s => s.id !== stage.id) })}><Trash2 size={16} /></button>
          </div>}
        </div>
        {stage.source !== 'start' && <><input aria-label={`${stage.name}: поиск шага или тега`} placeholder="Поиск шага или тега"
          value={search[stage.id] || ''} onChange={e => setSearch({ ...search, [stage.id]: e.target.value })} />
        <div className="journey-stage-choices">
          {(stage.source === 'tag' ? catalogue.tags.map(t => ({ id: t.id, name: t.name, ref: null })) : catalogue.steps
            .filter(s => draft.scope === 'bot' || s.funnel_id === funnelId)
            .map(s => ({ id: JSON.stringify([s.funnel_id, s.key]), name: s.name, ref: { funnel_id: s.funnel_id, key: s.key } })))
            .filter(option => option.name.toLocaleLowerCase().includes((search[stage.id] || '').toLocaleLowerCase()))
            .map(option => <label key={option.id}><input type="checkbox"
              checked={option.ref ? stage.step_refs.some(r => r.funnel_id === option.ref!.funnel_id && r.key === option.ref!.key) : stage.tag_ids.includes(option.id)} onChange={e => {
                if (option.ref) change(index, { step_refs: e.target.checked ? [...stage.step_refs, option.ref] :
                  stage.step_refs.filter(r => r.funnel_id !== option.ref!.funnel_id || r.key !== option.ref!.key) })
                else change(index, { tag_ids: e.target.checked ? [...stage.tag_ids, option.id] : stage.tag_ids.filter(id => id !== option.id) })
              }} />{option.name}</label>)}
        </div></>}
      </div>)}
      <div className="tracking-actions">
        <button type="button" disabled={draft.stages.length >= 20} onClick={() => setDraft({ ...draft,
          stages: [...draft.stages.slice(0, -1), makeStage('Новый этап', 'entered'), draft.stages[draft.stages.length - 1]] })}><Plus size={16} />Добавить этап</button>
        <button type="button" onClick={() => void save()}><Save size={16} />{saving ? 'Сохранение…' : 'Сохранить этапы'}</button>
      </div>
    </fieldset>
    {error && <p role="alert" className="tracking-warning">{error}</p>}
  </section>
}

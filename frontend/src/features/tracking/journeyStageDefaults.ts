import type { Catalogue, JourneyConfig, Stage } from './JourneyStageEditor'

export const makeStage = (name: string, source: Stage['source'], role: Stage['role'] = 'regular'): Stage =>
  ({ id: crypto.randomUUID(), name, source, role, step_keys: [], step_refs: [], tag_ids: [] })
export const emptyConfig = (): JourneyConfig => ({ mode: 'stages', idle_hours: 24, scope: 'bot',
  stages: [makeStage('Старт', 'start'), makeStage('VIP', 'tag', 'outcome')] })
const normalized = (name: string) => name.normalize('NFKC').trim().toLocaleLowerCase().replace(/\s+/g, ' ')
export function sourceName(stage: Stage, catalogue: Catalogue): string {
  const names = stage.source === 'tag'
    ? stage.tag_ids.map(id => catalogue.tags.find(tag => tag.id === id)?.name)
    : stage.step_refs.map(ref => { const step = catalogue.steps.find(s => s.funnel_id === ref.funnel_id && s.key === ref.key)
      return step ? `#${step.number} · ${step.title}` : undefined })
  return [...new Set(names.filter((name): name is string => !!name))].join(' / ').slice(0, 80)
}
export function vacancyConfig(catalogue: Catalogue, funnelId: string, current: JourneyConfig): JourneyConfig {
  const specs: [string, string[], Stage['source'], Stage['role']][] = [
    ['Возраст', ['Возраст', 'Шаг 1'], 'answered', 'regular'],
    ['Гражданство', ['Гражданство', 'Шаг 2'], 'answered', 'regular'],
    ['Цели', ['Цели', 'Шаг 3'], 'answered', 'regular'],
    ['Описание', ['Описание', 'Описание предложения', 'Шаг 4'], 'entered', 'offer'],
    ['HOT', ['HOT', 'Контакты', 'Шаг 5'], 'tag', 'regular'],
    ['HOT HOT', ['HOT HOT', 'Выбор времени', 'Шаг 6'], 'tag', 'regular'],
    ['VIP', ['VIP', 'Лид передан'], 'tag', 'outcome'],
  ]
  return { ...current, mode: 'stages', stages: [makeStage('Старт', 'start'), ...specs.map(([name, aliases, source, role]) => {
    const stage = makeStage(name, source, role)
    const tag = aliases.map(alias => catalogue.tags.find(t => normalized(t.name) === normalized(alias))).find(Boolean)
    if (tag) { stage.source = 'tag'; stage.tag_ids = [tag.id] }
    else if (source !== 'tag') {
      const matches = catalogue.steps.filter(step => step.funnel_id === funnelId && aliases.some(alias => normalized(step.title) === normalized(alias)))
      stage.step_refs = matches.map(step => ({ funnel_id: step.funnel_id, key: step.key }))
    }
    return { ...stage, name: sourceName(stage, catalogue) || name }
  })] }
}

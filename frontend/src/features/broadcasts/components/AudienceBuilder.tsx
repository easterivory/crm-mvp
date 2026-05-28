import { Plus } from 'lucide-react'

import type { AudienceFilter, AudienceRule, AudienceRuleGroup, BroadcastOption } from '../types'
import AudienceRuleRow from './AudienceRuleRow'

type AudienceBuilderProps = {
  value: AudienceFilter
  tags: BroadcastOption[]
  statuses: BroadcastOption[]
  trackingLinks: BroadcastOption[]
  users: BroadcastOption[]
  bots: BroadcastOption[]
  funnels: BroadcastOption[]
  onChange: (value: AudienceFilter) => void
}

function newRule(): AudienceRule {
  return {
    id: crypto.randomUUID(),
    field: 'tag',
    operator: 'in',
    value: [],
  }
}

function RuleGroup({
  title,
  group,
  tags,
  statuses,
  trackingLinks,
  users,
  bots,
  funnels,
  onChange,
}: {
  title: string
  group: AudienceRuleGroup
  tags: BroadcastOption[]
  statuses: BroadcastOption[]
  trackingLinks: BroadcastOption[]
  users: BroadcastOption[]
  bots: BroadcastOption[]
  funnels: BroadcastOption[]
  onChange: (group: AudienceRuleGroup) => void
}) {
  return (
    <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <p className="text-xs text-gray-500">Условия внутри блока применяются выбранным режимом.</p>
        </div>
        <select
          value={group.mode}
          onChange={(event) => onChange({ ...group, mode: event.target.value as 'all' | 'any' })}
          className="h-9 rounded-lg border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none"
        >
          <option value="all">Все условия / AND</option>
          <option value="any">Любое условие / OR</option>
        </select>
      </div>

      <div className="space-y-3">
        {group.rules.length === 0 ? (
          <p className="rounded-lg border border-dashed border-white/10 px-3 py-3 text-sm text-gray-500">
            Условий пока нет.
          </p>
        ) : null}
        {group.rules.map((rule, index) => (
          <AudienceRuleRow
            key={rule.id}
            rule={rule}
            tags={tags}
            statuses={statuses}
            trackingLinks={trackingLinks}
            users={users}
            bots={bots}
            funnels={funnels}
            onChange={(nextRule) =>
              onChange({
                ...group,
                rules: group.rules.map((item, idx) => (idx === index ? nextRule : item)),
              })
            }
            onRemove={() =>
              onChange({ ...group, rules: group.rules.filter((_, idx) => idx !== index) })
            }
          />
        ))}
      </div>

      <button
        type="button"
        onClick={() => onChange({ ...group, rules: [...group.rules, newRule()] })}
        className="mt-3 inline-flex h-9 items-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
      >
        <Plus size={15} />
        Добавить условие
      </button>
    </section>
  )
}

export default function AudienceBuilder({
  value,
  tags,
  statuses,
  trackingLinks,
  users,
  bots,
  funnels,
  onChange,
}: AudienceBuilderProps) {
  return (
    <div className="space-y-4">
      <RuleGroup
        title="Включить"
        group={value.include}
        tags={tags}
        statuses={statuses}
        trackingLinks={trackingLinks}
        users={users}
        bots={bots}
        funnels={funnels}
        onChange={(include) => onChange({ ...value, include })}
      />
      <RuleGroup
        title="Исключить"
        group={value.exclude}
        tags={tags}
        statuses={statuses}
        trackingLinks={trackingLinks}
        users={users}
        bots={bots}
        funnels={funnels}
        onChange={(exclude) => onChange({ ...value, exclude })}
      />
    </div>
  )
}

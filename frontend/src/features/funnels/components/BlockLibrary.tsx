import {
  Bot,
  CheckCircle2,
  ChevronDown,
  Clock,
  GitBranch,
  Handshake,
  HelpCircle,
  MessageSquare,
  MousePointer2,
  Plus,
  Search,
  Shuffle,
  Sparkles,
  Workflow,
} from 'lucide-react'
import { useState } from 'react'

import { blockGroups, type BlockMenuItem } from '../blockCatalog'

type BlockLibraryProps = {
  onAdd: (item: BlockMenuItem) => void
  readOnly?: boolean
}

const iconByBlock: Record<string, typeof MessageSquare> = {
  generic_trigger: MousePointer2,
  generic_message: MessageSquare,
  generic_input: HelpCircle,
  generic_delay: Clock,
  generic_condition: GitBranch,
  reserved_randomizer: Shuffle,
  reserved_split: GitBranch,
  generic_crm_action: Workflow,
  generic_operator: Handshake,
  generic_finish: CheckCircle2,
  reserved_ai_reply: Sparkles,
  reserved_ai_text_analysis: Bot,
  reserved_ai_sentiment: Sparkles,
}

const accentClass = {
  cyan: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100',
  violet: 'border-violet-300/25 bg-violet-300/10 text-violet-100',
  emerald: 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100',
  amber: 'border-amber-300/25 bg-amber-300/10 text-amber-100',
  rose: 'border-rose-300/25 bg-rose-300/10 text-rose-100',
}

export default function BlockLibrary({ onAdd, readOnly = false }: BlockLibraryProps) {
  const [search, setSearch] = useState('')
  const [openGroups, setOpenGroups] = useState(() => new Set(blockGroups.map((group) => group.title)))

  const toggleGroup = (title: string) => {
    setOpenGroups((current) => {
      const next = new Set(current)
      if (next.has(title)) {
        next.delete(title)
      } else {
        next.add(title)
      }
      return next
    })
  }

  return (
    <aside className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-xl border border-white/8 bg-[#0d1324]/92 lg:rounded-none lg:border-y-0 lg:border-l-0 lg:border-r">
      <div className="border-b border-white/8 px-4 py-3">
        <h2 className="text-sm font-semibold text-white">Блоки</h2>
        <label className="mt-3 flex items-center gap-2 rounded border border-white/10 px-2">
          <Search size={14} className="shrink-0 text-gray-500" />
          <input aria-label="Поиск блоков" placeholder="Найти блок" value={search} onChange={(event) => setSearch(event.target.value)} className="h-8 min-w-0 w-full bg-transparent text-sm outline-none" />
        </label>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {blockGroups.map((group) => {
          const items = group.items.filter((item) => `${item.label} ${item.description ?? ''}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
          if (!items.length) return null
          const isOpen = Boolean(search) || openGroups.has(group.title)
          const accent = accentClass[group.accent ?? 'cyan']
          return (
            <section key={group.title} className="border-b border-white/8 pb-2">
              <button
                type="button"
                onClick={() => toggleGroup(group.title)}
                className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
              >
                <span className="text-xs font-semibold uppercase tracking-wide text-gray-300">
                  {group.title}
                </span>
                <ChevronDown
                  size={15}
                  className={`text-gray-500 transition ${isOpen ? 'rotate-180' : ''}`}
                />
              </button>

              {isOpen ? (
                <div className="space-y-2 px-2 pb-2">
                  {items.map((item) => {
                    const Icon = iconByBlock[item.blockType] ?? Workflow
                    return (
                      <button
                        key={`${group.title}:${item.blockType}`}
                        type="button"
                        onClick={() => {
                          if (!item.disabled) {
                            onAdd(item)
                          }
                        }}
                        disabled={item.disabled || readOnly}
                        title={item.description}
                        className="group flex w-full min-w-0 items-center gap-2 rounded px-2 py-2 text-left transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-55"
                      >
                        <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded border ${accent}`}>
                          <Icon size={17} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-gray-100">
                              {item.label}
                            </span>
                            {item.badge ? (
                              <span className="rounded-full border border-white/10 bg-white/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-wide text-gray-400">
                                {item.badge}
                              </span>
                            ) : null}
                          </span>
                        </span>
                        {!item.disabled ? (
                          <Plus
                            size={14}
                            className="mt-1 shrink-0 text-gray-600 transition group-hover:text-accent-200"
                          />
                        ) : null}
                      </button>
                    )
                  })}
                </div>
              ) : null}
            </section>
          )
        })}
      </div>
    </aside>
  )
}

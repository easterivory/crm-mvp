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
  Shuffle,
  Sparkles,
  Workflow,
} from 'lucide-react'
import { useState } from 'react'

import { blockGroups, type BlockMenuItem } from '../blockCatalog'

type BlockLibraryProps = {
  onAdd: (item: BlockMenuItem) => void
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

export default function BlockLibrary({ onAdd }: BlockLibraryProps) {
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
        <p className="mt-1 text-xs leading-5 text-gray-500">
          Добавьте шаг на холст, затем настройте его в панели «Настройки».
        </p>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {blockGroups.map((group) => {
          const isOpen = openGroups.has(group.title)
          const accent = accentClass[group.accent ?? 'cyan']
          return (
            <section key={group.title} className="rounded-xl border border-white/8 bg-white/[0.025]">
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
                  {group.items.map((item) => {
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
                        disabled={item.disabled}
                        className="group flex w-full min-w-0 items-start gap-3 rounded-xl border border-white/8 bg-[#101827]/80 p-3 text-left transition hover:border-accent-300/35 hover:bg-accent-300/10 disabled:cursor-not-allowed disabled:opacity-55 disabled:hover:border-white/8 disabled:hover:bg-[#101827]/80"
                      >
                        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${accent}`}>
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
                          <span className="mt-1 block text-xs leading-4 text-gray-500">
                            {item.description}
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

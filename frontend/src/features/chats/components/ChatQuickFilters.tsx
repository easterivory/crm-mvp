import type { ChatFiltersState } from '../types'

type ChatQuickFiltersProps = {
  filters: ChatFiltersState
  currentUserId: string | null
  counts: Record<'unread' | 'mine' | 'all' | 'favorites', number>
  onChange: (filters: ChatFiltersState) => void
}

const quickFilterBase = {
  assignedUserId: '',
  hasUnansweredIncoming: false,
  isHotLead: false,
  isRed: false,
  unassigned: false,
}

export default function ChatQuickFilters({
  filters,
  currentUserId,
  counts,
  onChange,
}: ChatQuickFiltersProps) {
  const setQuick = (key: ChatFiltersState['workspaceView']) => {
    if (key === 'mine' && !currentUserId) {
      return
    }
    onChange({
      ...filters,
      ...quickFilterBase,
      quickFilter: '',
      workspaceView: key,
    })
  }

  const items = [
    { key: 'unread', label: 'Непрочитанные' },
    { key: 'mine', label: 'Мои', disabled: !currentUserId },
    { key: 'all', label: 'Все' },
    { key: 'favorites', label: 'Избранные' },
  ] as const

  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
      {items.map((item) => {
        const isActive = filters.workspaceView === item.key
        return (
          <button
            key={item.key}
            type="button"
            disabled={'disabled' in item ? item.disabled : false}
            onClick={() => setQuick(item.key)}
            className={`inline-flex h-8 shrink-0 items-center rounded-full border px-3 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
              isActive
                ? 'border-primary-300/45 bg-primary-400/15 text-primary-50'
                : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-accent-300/35 hover:text-gray-100'
            }`}
          >
            <span>{item.label}</span>
            <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] tabular-nums ${
              isActive ? 'bg-white/10 text-white' : 'bg-white/[0.05] text-gray-500'
            }`}>
              {counts[item.key]}
            </span>
          </button>
        )
      })}
    </div>
  )
}

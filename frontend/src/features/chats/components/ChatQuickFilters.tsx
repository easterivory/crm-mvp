import type { ChatFiltersState } from '../types'

type ChatQuickFiltersProps = {
  filters: ChatFiltersState
  currentUserId: string | null
  onChange: (filters: ChatFiltersState) => void
}

const quickFilterBase = {
  assignedUserId: '',
  hasUnansweredIncoming: false,
  isRed: false,
  unassigned: false,
}

export default function ChatQuickFilters({
  filters,
  currentUserId,
  onChange,
}: ChatQuickFiltersProps) {
  const activeQuick =
    filters.isRed
      ? 'hot'
      : filters.hasUnansweredIncoming
        ? 'unanswered'
        : currentUserId && filters.assignedUserId === currentUserId
          ? 'mine'
          : 'all'

  const setQuick = (key: 'all' | 'mine' | 'unanswered' | 'hot') => {
    if (key === 'all') {
      onChange({ ...filters, ...quickFilterBase, quickFilter: 'all' })
      return
    }
    if (key === 'mine') {
      if (!currentUserId) {
        return
      }
      onChange({
        ...filters,
        ...quickFilterBase,
        assignedUserId: currentUserId,
        quickFilter: 'mine',
      })
      return
    }
    if (key === 'unanswered') {
      onChange({
        ...filters,
        ...quickFilterBase,
        hasUnansweredIncoming: true,
        quickFilter: 'unanswered',
      })
      return
    }
    onChange({
      ...filters,
      ...quickFilterBase,
      isRed: true,
      quickFilter: 'hot',
    })
  }

  const items = [
    { key: 'all', label: 'Все' },
    { key: 'mine', label: 'Мои', disabled: !currentUserId },
    { key: 'unanswered', label: 'Не отвечено' },
    { key: 'hot', label: 'Горячие' },
  ] as const

  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
      {items.map((item) => {
        const isActive = activeQuick === item.key
        return (
          <button
            key={item.key}
            type="button"
            disabled={'disabled' in item ? item.disabled : false}
            onClick={() => setQuick(item.key)}
            className={`h-8 shrink-0 rounded-full border px-3 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
              isActive
                ? 'border-primary-300/45 bg-primary-400/15 text-primary-50'
                : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-accent-300/35 hover:text-gray-100'
            }`}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

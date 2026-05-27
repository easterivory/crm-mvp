import type { ChatFiltersState } from '../types'

type ChatQuickFiltersProps = {
  filters: ChatFiltersState
  currentUserId: string | null
  onChange: (filters: ChatFiltersState) => void
}

const statusLabels = {
  new: 'Новые',
  in_progress: 'В работе',
} as const

export default function ChatQuickFilters({
  filters,
  currentUserId,
  onChange,
}: ChatQuickFiltersProps) {
  const toggleStatus = (status: keyof typeof statusLabels) => {
    const enabled = filters.leadStatuses.includes(status)
    onChange({
      ...filters,
      leadStatuses: enabled
        ? filters.leadStatuses.filter((item) => item !== status)
        : [...filters.leadStatuses.filter((item) => !Object.keys(statusLabels).includes(item)), status],
    })
  }

  const items = [
    {
      key: 'unanswered',
      label: 'Не отвечено',
      active: filters.hasUnansweredIncoming,
      onClick: () => onChange({ ...filters, hasUnansweredIncoming: !filters.hasUnansweredIncoming }),
    },
    {
      key: 'new',
      label: 'Новые',
      active: filters.leadStatuses.includes('new'),
      onClick: () => toggleStatus('new'),
    },
    {
      key: 'in_progress',
      label: 'В работе',
      active: filters.leadStatuses.includes('in_progress'),
      onClick: () => toggleStatus('in_progress'),
    },
    {
      key: 'completed',
      label: 'Завершили воронку',
      active: filters.funnelState === 'completed',
      onClick: () =>
        onChange({
          ...filters,
          funnelState: filters.funnelState === 'completed' ? '' : 'completed',
        }),
    },
    {
      key: 'unassigned',
      label: 'Без менеджера',
      active: filters.unassigned,
      onClick: () =>
        onChange({
          ...filters,
          unassigned: !filters.unassigned,
          assignedUserId: '',
        }),
    },
    {
      key: 'mine',
      label: 'Мои чаты',
      active: Boolean(currentUserId && filters.assignedUserId === currentUserId),
      disabled: !currentUserId,
      onClick: () =>
        currentUserId
          ? onChange({
              ...filters,
              assignedUserId: filters.assignedUserId === currentUserId ? '' : currentUserId,
              unassigned: false,
            })
          : undefined,
    },
  ]

  return (
    <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          disabled={item.disabled}
          onClick={item.onClick}
          className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
            item.active
              ? 'border-primary-300/45 bg-primary-400/15 text-primary-50'
              : 'border-white/10 bg-white/[0.03] text-gray-400 hover:border-accent-300/35 hover:text-gray-100'
          }`}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

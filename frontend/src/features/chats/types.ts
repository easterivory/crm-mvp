export type ChatFunnelStateFilter =
  | ''
  | 'in_funnel'
  | 'waiting_for_answer'
  | 'completed'
  | 'manual'

export type ChatDatePreset = '' | 'today' | 'yesterday' | '7d' | '30d' | 'custom'

export type ChatFiltersState = {
  q: string
  datePreset: ChatDatePreset
  dateFrom: string
  dateTo: string
  tagIds: string[]
  leadStatuses: string[]
  trackingLinkId: string
  funnelState: ChatFunnelStateFilter
  hasUnansweredIncoming: boolean
  isRed: boolean
  assignedUserId: string
  unassigned: boolean
}

export type FilterOption = {
  id: string
  label: string
}

export const EMPTY_CHAT_FILTERS: ChatFiltersState = {
  q: '',
  datePreset: '',
  dateFrom: '',
  dateTo: '',
  tagIds: [],
  leadStatuses: [],
  trackingLinkId: '',
  funnelState: '',
  hasUnansweredIncoming: false,
  isRed: false,
  assignedUserId: '',
  unassigned: false,
}

export function countActiveChatFilters(filters: ChatFiltersState) {
  return [
    filters.q,
    filters.dateFrom || filters.dateTo,
    ...filters.tagIds,
    ...filters.leadStatuses,
    filters.trackingLinkId,
    filters.funnelState,
    filters.hasUnansweredIncoming ? 'has_unanswered' : '',
    filters.isRed ? 'is_red' : '',
    filters.assignedUserId,
    filters.unassigned ? 'unassigned' : '',
  ].filter(Boolean).length
}

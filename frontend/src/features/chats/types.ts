export type ChatFunnelStateFilter =
  | ''
  | 'in_funnel'
  | 'waiting_for_answer'
  | 'completed'
  | 'manual'

export type ChatDatePreset = '' | 'today' | 'yesterday' | '7d' | '30d' | 'custom'
export type ChatTagMode = 'any' | 'all'
export type ChatQuickFilter = '' | 'all' | 'mine' | 'unanswered' | 'hot'
export type ChatSort = 'latest' | 'priority'

export type ChatFiltersState = {
  q: string
  datePreset: ChatDatePreset
  dateFrom: string
  dateTo: string
  tagIds: string[]
  tagMode: ChatTagMode
  leadStatuses: string[]
  trackingLinkId: string
  funnelState: ChatFunnelStateFilter
  hasUnansweredIncoming: boolean
  isRed: boolean
  isHotLead: boolean
  assignedUserId: string
  unassigned: boolean
  quickFilter: ChatQuickFilter
  sortBy: ChatSort
}

export type FilterOption = {
  id: string
  label: string
}

export type ChatFilterPreset = {
  id: string
  project_id: string
  user_id: string
  name: string
  filters_json: ChatFiltersState
  is_shared: boolean
  created_at: string
  updated_at: string
}

export type FunnelRuntimeLog = {
  step_id: string
  step_key: string
  step_title: string
  status: 'success' | 'failed'
  error_message: string | null
  created_at: string
}

export const EMPTY_CHAT_FILTERS: ChatFiltersState = {
  q: '',
  datePreset: '',
  dateFrom: '',
  dateTo: '',
  tagIds: [],
  tagMode: 'any',
  leadStatuses: [],
  trackingLinkId: '',
  funnelState: '',
  hasUnansweredIncoming: false,
  isRed: false,
  isHotLead: false,
  assignedUserId: '',
  unassigned: false,
  quickFilter: '',
  sortBy: 'latest',
}

export function countActiveChatFilters(filters: ChatFiltersState) {
  return [
    filters.q,
    filters.dateFrom || filters.dateTo,
    filters.tagIds.length > 0 ? 'tags' : '',
    ...filters.leadStatuses,
    filters.trackingLinkId,
    filters.funnelState,
    filters.hasUnansweredIncoming ? 'has_unanswered' : '',
    filters.isRed ? 'is_red' : '',
    filters.isHotLead ? 'is_hot_lead' : '',
    filters.assignedUserId,
    filters.unassigned ? 'unassigned' : '',
  ].filter(Boolean).length
}

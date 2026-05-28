export type BroadcastStatus =
  | 'draft'
  | 'audience_ready'
  | 'scheduled'
  | 'sending'
  | 'paused'
  | 'sent'
  | 'failed'
  | 'cancelled'

export type Broadcast = {
  id: string
  project_id: string
  bot_id: string | null
  name: string
  content_json: BroadcastContent
  audience_filter_json: AudienceFilter
  audience_count: number
  schedule_type: 'now' | 'scheduled'
  scheduled_at: string | null
  timezone_mode: 'project' | 'lead_local' | 'fixed'
  status: BroadcastStatus
  created_by_user_id: string | null
  created_by_name?: string | null
  started_at?: string | null
  created_at: string
  updated_at: string
  sent_at: string | null
}

export type BroadcastContent = {
  type: 'message'
  messages: Array<{
    type: 'text'
    text: string
    delay_seconds?: number
    buttons?: Array<Record<string, unknown>>
  }>
  after_send_action?: {
    type: 'start_funnel'
    funnel_id: string
    funnel_version_id?: string | null
    mode: 'restart' | 'skip_if_active' | 'skip_if_completed'
  } | null
}

export type AudienceRule = {
  id: string
  field: string
  operator: string
  value: unknown
  custom_field?: string
}

export type AudienceRuleGroup = {
  mode: 'all' | 'any'
  rules: AudienceRule[]
}

export type AudienceFilter = {
  include: AudienceRuleGroup
  exclude: AudienceRuleGroup
}

export type AudiencePreviewSample = {
  chat_id: string
  lead_id: string | null
  lead_name: string | null
  username: string | null
  status: string | null
}

export type AudiencePreview = {
  count: number
  in_funnel_count?: number
  sample: AudiencePreviewSample[]
}

export type BroadcastActionResponse = {
  broadcast: Broadcast
  audience: AudiencePreview
}

export type BroadcastReport = {
  total_recipients: number
  pending: number
  sent: number
  failed: number
  skipped: number
  cancelled: number
  started_at: string | null
  finished_at: string | null
  error_examples: string[]
}

export type BroadcastTemplate = {
  id: string
  project_id: string
  name: string
  content_json: BroadcastContent
  created_by_user_id: string | null
  created_by_name?: string | null
  created_at: string
  updated_at: string
}

export type BroadcastOption = {
  id: string
  label: string
  meta?: Record<string, unknown>
}

export const emptyAudienceFilter = (): AudienceFilter => ({
  include: { mode: 'all', rules: [] },
  exclude: { mode: 'any', rules: [] },
})

export const emptyBroadcastContent = (): BroadcastContent => ({
  type: 'message',
  messages: [{ type: 'text', text: '', delay_seconds: 0, buttons: [] }],
  after_send_action: null,
})

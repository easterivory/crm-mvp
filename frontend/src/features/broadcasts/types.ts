export type BroadcastStatus =
  | 'draft'
  | 'scheduled'
  | 'processing'
  | 'paused'
  | 'completed'
  | 'cancelled'

export type Broadcast = {
  id: string
  project_id: string
  bot_id: string | null
  name: string
  content_json: BroadcastContent
  audience_filter_json: AudienceFilter
  audience_count: number
  total_recipients?: number
  sent_count?: number
  failed_count?: number
  schedule_type: 'now' | 'scheduled'
  scheduled_at: string | null
  timezone_mode: 'project' | 'lead_local' | 'fixed'
  status: BroadcastStatus
  created_by_user_id: string | null
  created_by_name?: string | null
  snippet_id?: string | null
  media_type?: string | null
  file_id?: string | null
  trigger_funnel_id?: string | null
  stop_on_reply?: boolean
  started_at?: string | null
  created_at: string
  updated_at: string
  sent_at: string | null
}

export type BroadcastContent = {
  type: 'message'
  messages: BroadcastMessage[]
  after_send_action?: null
}

export type BroadcastMediaType = 'photo' | 'video' | 'voice' | 'video_note' | 'document'

export type BroadcastMedia = {
  source: 'upload' | 'telegram_file_id'
  upload_id?: string
  telegram_file_id?: string
  file_name?: string
  mime_type?: string
  file_size?: number
  media_type?: BroadcastMediaType
}

export type BroadcastMessage = {
  type?: 'text' | BroadcastMediaType
  text?: string
  caption?: string
  media?: BroadcastMedia
  delay_seconds?: number
  buttons?: Array<Record<string, unknown>>
}

export type BroadcastUpload = {
  upload_id: string
  project_id: string
  file_name: string
  mime_type: string
  file_size: number
  media_type: BroadcastMediaType
  status: string
  expires_at: string | null
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
  status: BroadcastStatus
  total_recipients: number
  sent_count: number
  failed_count: number
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

export type ProjectSnippet = {
  id: string
  project_id: string
  channel: string
  name: string
  type: 'text' | BroadcastMediaType
  content: string | null
  file_id: string | null
  created_at: string
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

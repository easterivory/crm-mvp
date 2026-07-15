export type FunnelStatus = 'active' | 'archived'
export type FunnelVersionStatus = 'draft' | 'published' | 'archived'

export type FunnelPublishedVersion = {
  id: string
  version_number: number
  published_at: string | null
  is_active_for_bot: boolean
  is_current_for_funnel: boolean
}

export type FunnelStepType =
  | 'trigger'
  | 'message'
  | 'input'
  | 'condition'
  | 'action'
  | 'delay'
  | 'operator'
  | 'integration'
  | 'finish'

export type Funnel = {
  id: string
  project_id: string
  bot_id: string
  name: string
  description: string | null
  status: FunnelStatus
  created_by_user_id: string | null
  created_at: string
  updated_at: string
  draft_version_id: string | null
  published_version_id: string | null
  current_version_id: string | null
  published_versions: FunnelPublishedVersion[]
  is_active_for_bot: boolean
}

export type FunnelSelfRestartResult = {
  chat_id: string
  funnel_id: string
  funnel_version_id: string
  version_number: number
  bot_id: string
}

export type FunnelVersion = {
  id: string
  funnel_id: string
  version_number: number
  status: FunnelVersionStatus
  created_by_user_id: string | null
  created_by_id: string | null
  change_log: string | null
  created_at: string
  updated_at: string
  published_at: string | null
  is_active_for_bot: boolean
  is_current_for_funnel: boolean
  is_hold_active: boolean
}

export type FunnelStep = {
  id: string
  funnel_version_id?: string
  key: string
  title: string
  step_type: FunnelStepType
  block_type: string
  position_x: number
  position_y: number
  config_json: Record<string, unknown>
  validation_json: Record<string, unknown> | null
  ui_schema_json: Record<string, unknown> | null
  created_at?: string
  updated_at?: string
}

export type FunnelEdge = {
  id: string
  funnel_version_id?: string
  from_step_id: string
  to_step_id: string
  condition_json: Record<string, unknown> | null
  priority: number
  created_at?: string
  updated_at?: string
}

export type FunnelPushRule = {
  id: string
  funnel_version_id?: string
  step_id: string
  delay_minutes: number
  message_text: string
  action_after_send: 'stay' | 'move_to_step' | 'finish' | 'assign_operator'
  target_step_id: string | null
  is_active: boolean
  created_at?: string
  updated_at?: string
}

export type FunnelFieldMapping = {
  id: string
  funnel_version_id?: string
  step_id: string
  source: 'user_answer' | 'button_value' | 'computed_value'
  lead_field_key: string
  transform_rule_json: Record<string, unknown> | null
  is_required: boolean
  created_at?: string
  updated_at?: string
}

export type FunnelGraph = {
  steps: FunnelStep[]
  edges: FunnelEdge[]
  push_rules: FunnelPushRule[]
  field_mappings: FunnelFieldMapping[]
}

export type FunnelValidationIssue = {
  code: string
  message: string
  severity: 'error' | 'warning'
  step_id: string | null
  step_key: string | null
  step_title: string | null
  step_type: string | null
  block_type: string | null
  edge_id: string | null
}

export type FunnelValidationResult = {
  can_publish: boolean
  errors: FunnelValidationIssue[]
  warnings: FunnelValidationIssue[]
}

export type FunnelGraphValidationResult = {
  is_valid: boolean
  errors: string[]
  warnings: string[]
}

export type FunnelGraphValidatePayload = {
  nodes: Array<Record<string, unknown>>
  edges: Array<Record<string, unknown>>
}

export type FunnelDropOffStep = {
  step_id: string
  step_title: string
  step_type: string
  block_type: string
  entered_leads: number
  conversion_from_start: number
  conversion_from_previous: number
}

export type FunnelDropOffAnalytics = {
  funnel_id: string
  version_id: string
  steps: FunnelDropOffStep[]
}

export type FunnelBlockDefinition = {
  step_type: FunnelStepType | string
  block_type: string
  label: string
  status: 'mvp' | 'supported' | 'reserved'
  description: string | null
}

export type FunnelBlockRegistry = {
  allowed_step_types: string[]
  lead_field_keys: string[]
  blocks: Record<string, FunnelBlockDefinition[]>
  reserved_future_blocks: string[]
}

export type CreateFunnelPayload = {
  project_id: string
  bot_id: string
  name: string
  description?: string | null
}

export type CopyFunnelPayload = {
  target_project_id: string
  target_bot_id: string
  copy_from_version_id?: string | null
}

export type CopyFunnelResult = {
  new_funnel_id: string
  new_version_id: string
}

export type BotActiveFunnel = {
  bot_id: string
  active_funnel_id: string | null
  active_funnel_version_id: string | null
  funnel: Funnel | null
  version: FunnelVersion | null
  version_status: FunnelVersionStatus | null
  version_number: number | null
  graph_summary: {
    steps_count: number
    edges_count: number
    has_trigger: boolean
    first_message_text: string | null
  } | null
}

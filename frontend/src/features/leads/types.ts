export type LeadTag = {
  id: string
  name: string
  color: string
}

export type Lead = {
  id: string
  project_id: string
  chat_id: string
  manager_id: string | null
  status_id: string
  name: string | null
  phone: string | null
  username: string | null
  age: number | null
  country: string | null
  call_time_text: string | null
  preferred_call_time: string | null
  has_card: boolean | null
  score_percent: number | null
  custom_fields?: Record<string, unknown> | null
  updated_at: string
  created_at: string
  is_deleted: boolean
  is_trash: boolean
  tags: LeadTag[]
  bot_id?: string | null
  bot_name?: string | null
  bot_username?: string | null
  tracking_link_id?: string | null
  tracking_code?: string | null
  tracking_ref_code?: string | null
  tracking_title?: string | null
  contact_name?: string | null
  external_chat_id?: string | null
  external_user_id?: string | null
  manager_name?: string | null
  status_code?: string | null
  status_name?: string | null
}

export type LeadStatus = {
  id: string
  code: string
  name: string
  sort_order: number
  is_final: boolean
  created_at: string
}

export type DuplicateSubmissionHistory = {
  partner_integration_id: string
  partner_name: string
  status: string
  partner_status: string | null
  error_message: string | null
  partner_feedback: string | null
  created_at: string
}

export type DuplicateLeadDetail = {
  lead_id: string
  project_name: string
  bot_name: string | null
  created_at: string
  match_type: string
  matched_fields: string[]
  lead_status: string | null
  is_trash: boolean
  is_deleted: boolean
  submission_history: DuplicateSubmissionHistory[]
}

export type LeadListParams = {
  project_id: string
  bot_ids?: string[]
  status?: string
  date_from?: string
  date_to?: string
  tag_ids?: string[]
  search?: string
  q?: string
  is_trash?: boolean
  partner_id?: string
  age_from?: number
  age_to?: number
  country?: string
  limit?: number
  offset?: number
}

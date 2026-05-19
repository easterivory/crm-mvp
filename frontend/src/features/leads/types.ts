export type LeadTag = {
  id: string
  name: string
}

export type Lead = {
  id: string
  project_id: string
  chat_id: string
  manager_id: string | null
  status_id: string
  phone: string | null
  username: string | null
  updated_at: string
  created_at: string
  is_deleted: boolean
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

export type LeadListParams = {
  project_id: string
  bot_ids?: string[]
  status?: string
  date_from?: string
  date_to?: string
  tag_ids?: string[]
  search?: string
  limit?: number
  offset?: number
}

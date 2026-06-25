export type ProjectStatus = 'active' | 'archived'

export type Project = {
  id: string
  name: string
  slug: string
  description: string | null
  status: ProjectStatus
  sla_threshold_minutes?: number
  tracking_lead_status_codes?: string[]
  created_at: string
  updated_at: string
  is_deleted?: boolean
}

export type ProjectCreatePayload = {
  name: string
  slug?: string
  description?: string | null
}

export type ProjectStatus = 'active' | 'archived'

export type Project = {
  id: string
  name: string
  slug: string
  description: string | null
  status: ProjectStatus
  sla_threshold_minutes?: number
  created_at: string
  updated_at: string
  is_deleted?: boolean
}

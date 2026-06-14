export type ProjectDomain = {
  id: string
  project_id: string
  domain_name: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ProjectDomainCreatePayload = {
  domain_name: string
}

export type LanderType = 'default_tg_redirect' | 'custom_upload'

export type ProjectLander = {
  id: string
  project_id: string
  domain_id: string
  name: string
  type: LanderType
  slug: string
  tracking_link_id: string | null
  custom_html_path: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ProjectLanderCreatePayload = {
  domain_id: string
  name: string
  type: LanderType
  slug: string
  tracking_link_id: string | null
}

export type ProjectLanderUploadResult = {
  success: boolean
  custom_html_path: string
}

export type TrackingLinkOption = {
  id: string
  project_id: string
  code: string
  title: string
  buyer_name: string | null
  is_active: boolean
}

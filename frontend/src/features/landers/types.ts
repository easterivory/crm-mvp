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

export type LanderPixelProvider = 'meta'

export type LanderPixel = {
  provider: LanderPixelProvider
  pixel_id: string
}

export type LanderMetaEvent = {
  name: string
}

export type LanderTrackingCampaign = {
  bot_id: string
  title: string
  code?: string | null
  buyer_name?: string | null
  ad_type?: string | null
  payment_type?: string | null
  base_conversion_rate?: number
  min_sample_size?: number
  target_funnel_step_key?: string | null
}

export type LanderTargetStep = {
  key: string
  title: string
  step_type: string
  block_type: string
}

export type ProjectLander = {
  id: string
  project_id: string
  domain_id: string
  name: string
  type: LanderType
  slug: string
  tracking_link_id: string | null
  pixels_json: LanderPixel[]
  meta_events_json: LanderMetaEvent[]
  utm_defaults_json: Record<string, string>
  custom_html_path: string | null
  auto_redirect_enabled: boolean
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
  campaign?: LanderTrackingCampaign | null
  pixels?: LanderPixel[]
  meta_events?: LanderMetaEvent[]
  utm_defaults?: Record<string, string>
  auto_redirect_enabled?: boolean
}

export type ProjectLanderUpdatePayload = {
  pixels?: LanderPixel[]
  meta_events?: LanderMetaEvent[]
  auto_redirect_enabled?: boolean
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

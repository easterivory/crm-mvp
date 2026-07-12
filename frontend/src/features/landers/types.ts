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

export type FacebookEventMapping = {
  source_event: string
  event_name: string
  enabled: boolean
  parameters: Record<string, string>
}

export type FacebookSourceEvent = {
  key: string
  label: string
  delivery: 'browser' | 'server'
  trigger: 'automatic' | 'funnel'
}

export type LanderRuntimeConfig = {
  technical_domain: string
  source_events: FacebookSourceEvent[]
  default_event_mappings: FacebookEventMapping[]
}

export type LanderTrackingCampaign = {
  bot_id: string
  title: string
  code?: string | null
  buyer_name?: string | null
  ad_type?: string | null
  payment_type?: string | null
  fb_pixel_id?: string | null
  fb_capi_token?: string | null
  fb_proxy_url?: string | null
  fb_test_event_code?: string | null
  fb_event_mappings?: FacebookEventMapping[]
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
  domain_id: string | null
  domain_name: string | null
  public_url: string
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
  facebook_campaign_enabled: boolean
  fb_pixel_id: string | null
  has_fb_capi_token: boolean
  has_fb_proxy: boolean
  fb_test_event_code: string | null
  fb_event_mappings_json: FacebookEventMapping[]
  facebook_campaign: {
    bot_id: string
    title: string
    code: string
    buyer_name: string | null
    ad_type: string | null
    payment_type: string | null
    base_conversion_rate: number
    min_sample_size: number
    target_funnel_step_key: string | null
  } | null
  created_at: string
  updated_at: string
}

export type ProjectLanderCreatePayload = {
  domain_id: string | null
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
  domain_id?: string | null
  name?: string
  type?: LanderType
  slug?: string
  pixels?: LanderPixel[]
  meta_events?: LanderMetaEvent[]
  utm_defaults?: Record<string, string>
  auto_redirect_enabled?: boolean
  facebook_campaign?: {
    enabled: boolean
    bot_id?: string
    title?: string
    code?: string
    buyer_name?: string | null
    ad_type?: string | null
    payment_type?: string | null
    base_conversion_rate?: number
    min_sample_size?: number
    target_funnel_step_key?: string | null
    fb_pixel_id: string | null
    fb_capi_token?: string | null
    clear_fb_capi_token?: boolean
    fb_proxy_url?: string | null
    clear_fb_proxy_url?: boolean
    fb_test_event_code: string | null
    fb_event_mappings: FacebookEventMapping[]
  }
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

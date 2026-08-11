export type TrackingCostModel = 'fix_pdp' | 'cpa' | 'cpm'

export type TrackingFacebookEventMapping = {
  source_event: string
  event_name: string
  enabled: boolean
  parameters: Record<string, string>
  triggers?: Array<{
    type: 'funnel_action' | 'lead_status' | 'lead_tag'
    value?: string
  }>
}

export type TrackingLink = {
  id: string
  project_id: string
  bot_id: string
  destination_type: 'bot' | 'channel'
  channel_id: string | null
  channel_title: string | null
  channel_join_request: boolean
  code: string
  title: string
  buyer_id: string | null
  buyer_name: string | null
  ad_type: string | null
  payment_type: string | null
  invite_link: string | null
  tracking_url: string | null
  is_active: boolean
  created_by_user_id: string | null
  created_at: string
  updated_at: string
  cost_model: TrackingCostModel
  price_per_unit: string | number
  spend: string | number
  base_conversion_rate: number
  min_sample_size: number
  target_funnel_id: string | null
  target_funnel_step_key: string | null
  target_funnel_step_title: string | null
  fb_pixel_id: string | null
  has_fb_capi_token: boolean
  fb_campaign_enabled: boolean
  fb_event_mappings_json: TrackingFacebookEventMapping[]
  has_fb_proxy: boolean
  fb_test_event_code: string | null
  total_spend?: string | number | null
}

export type TrackingLinkCreatePayload = {
  project_id: string
  bot_id?: string | null
  destination_type?: 'bot' | 'channel'
  channel_id?: string | null
  channel_join_request?: boolean
  title: string
  code?: string
  buyer_id?: string | null
  buyer_name?: string | null
  ad_type?: string | null
  payment_type?: string | null
  invite_link?: string | null
  base_conversion_rate?: number
  min_sample_size?: number
  target_funnel_step_key?: string | null
  fb_pixel_id?: string | null
  fb_capi_token?: string | null
  fb_campaign_enabled?: boolean
  fb_event_mappings?: TrackingFacebookEventMapping[]
  fb_proxy_url?: string | null
  fb_test_event_code?: string | null
  cost_model?: TrackingCostModel
  price_per_unit?: number
  spend?: number
}

export type TrackingLinkUpdatePayload = Partial<{
  title: string
  code: string
  buyer_id: string | null
  buyer_name: string | null
  ad_type: string | null
  payment_type: string | null
  invite_link: string | null
  is_active: boolean
  base_conversion_rate: number
  min_sample_size: number
  target_funnel_step_key: string | null
  fb_pixel_id: string | null
  fb_capi_token: string | null
  fb_campaign_enabled: boolean
  fb_event_mappings: TrackingFacebookEventMapping[]
  fb_proxy_url: string | null
  fb_test_event_code: string | null
  cost_model: TrackingCostModel
  price_per_unit: number
  spend: number
  channel_join_request: boolean
}>

export type TrackingFunnelStepOption = {
  key: string
  title: string
  step_type: string
  block_type: string
  number: number
}

export type TrackingSpend = {
  id: string
  tracking_link_id: string
  spend_date: string
  amount: string | number
  currency: string
  comment: string | null
  source: 'crm_manual' | 'buyer_bot'
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

export type TrackingSpendCreatePayload = {
  spend_date: string
  amount: number
  currency?: string
  comment?: string | null
}

export type TrackingSpendUpdatePayload = Partial<TrackingSpendCreatePayload>

export type TrackingMetricSummary = {
  clicks: number
  starts: number
  leads: number
  submitted_leads: number
  deposits: number
  registrations: number
  first_deposits: number
  redeposits: number
  channel_join_requests: number
  channel_joins: number
  channel_leaves: number
  channel_active_subscribers: number
  cr_click_to_channel_join: string | number
  spend: string | number
  cr_to_lead: string | number
  cr_to_submit: string | number
  cr_to_deposit: string | number
  cr_to_registration: string | number
  cr_registration_to_deposit: string | number
  cr_deposit_to_redeposit: string | number
  cpl: string | number
  cpsl: string | number
  cpd: string | number
  cpr: string | number
  cpfd: string | number
  cprd: string | number
}

export type TrackingDailyMetric = {
  date: string
  clicks: number
  starts: number
  leads: number
  submitted_leads: number
  deposits: number
  registrations: number
  first_deposits: number
  redeposits: number
  channel_join_requests: number
  channel_joins: number
  channel_leaves: number
  spend: string | number
}

export type TrackingLifecycleSourceMetric = {
  source: string
  registrations: number
  first_deposits: number
  redeposits: number
}

export type TrackingConversionStatus =
  | 'insufficient_data'
  | 'high_cr'
  | 'low_cr'
  | 'normal_cr'

export type TrackingLinkMetric = {
  link_id: string
  code: string
  title: string
  buyer_name: string | null
  ad_type: string | null
  payment_type: string | null
  is_active: boolean
  destination_type: 'bot' | 'channel'
  channel_id: string | null
  channel_join_request: boolean
  base_conversion_rate: number
  min_sample_size: number
  conversion_status: TrackingConversionStatus
  summary: TrackingMetricSummary
}

export type BreakdownItem = {
  key: string
  label: string
  count: number
  percent: string | number
}

export type FunnelStepMetric = {
  step_key: string
  label: string
  count: number
  dropoff_count: number
  dropoff_percent: string | number
}

export type TrackingProjectMetricsResponse = {
  project_id: string
  bot_id: string | null
  date_from: string
  date_to: string
  project_format: 'submission' | 'gambling'
  tracking_lead_status_codes: string[]
  summary: TrackingMetricSummary
  unattributed_summary: TrackingMetricSummary
  unattributed_daily: TrackingDailyMetric[]
  links: TrackingLinkMetric[]
  daily: TrackingDailyMetric[]
  lifecycle_sources: TrackingLifecycleSourceMetric[]
}

export type TrackingLinkMetricsResponse = {
  link_id: string
  project_id: string
  bot_id: string
  destination_type: 'bot' | 'channel'
  channel_id: string | null
  channel_join_request: boolean
  code: string
  title: string
  base_conversion_rate: number
  min_sample_size: number
  conversion_status: TrackingConversionStatus
  date_from: string
  date_to: string
  project_format: 'submission' | 'gambling'
  tracking_lead_status_codes: string[]
  summary: TrackingMetricSummary
  daily: TrackingDailyMetric[]
  funnel_steps: FunnelStepMetric[]
  age_breakdown: BreakdownItem[]
  country_breakdown: BreakdownItem[]
  city_breakdown: BreakdownItem[]
  status_breakdown: BreakdownItem[]
  card_breakdown: BreakdownItem[]
  lifecycle_sources: TrackingLifecycleSourceMetric[]
}

export type TrackingDateRangeParams = {
  date_from?: string
  date_to?: string
}

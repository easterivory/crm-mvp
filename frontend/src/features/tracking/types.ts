export type TrackingLink = {
  id: string
  project_id: string
  bot_id: string
  code: string
  title: string
  buyer_name: string | null
  ad_type: string | null
  payment_type: string | null
  invite_link: string | null
  is_active: boolean
  created_by_user_id: string | null
  created_at: string
  updated_at: string
  base_conversion_rate: number
  min_sample_size: number
  target_funnel_id: string | null
  target_funnel_step_key: string | null
  target_funnel_step_title: string | null
  total_spend?: string | number | null
}

export type TrackingLinkCreatePayload = {
  project_id: string
  bot_id: string
  title: string
  code?: string
  buyer_name?: string | null
  ad_type?: string | null
  payment_type?: string | null
  invite_link?: string | null
  base_conversion_rate?: number
  min_sample_size?: number
  target_funnel_step_key?: string | null
}

export type TrackingLinkUpdatePayload = Partial<{
  title: string
  code: string
  buyer_name: string | null
  ad_type: string | null
  payment_type: string | null
  invite_link: string | null
  is_active: boolean
  base_conversion_rate: number
  min_sample_size: number
  target_funnel_step_key: string | null
}>

export type TrackingFunnelStepOption = {
  key: string
  title: string
  step_type: string
  block_type: string
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
  spend: string | number
  cr_to_lead: string | number
  cr_to_submit: string | number
  cr_to_deposit: string | number
  cpl: string | number
  cpsl: string | number
  cpd: string | number
}

export type TrackingDailyMetric = {
  date: string
  clicks: number
  starts: number
  leads: number
  submitted_leads: number
  deposits: number
  spend: string | number
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
  summary: TrackingMetricSummary
  links: TrackingLinkMetric[]
  daily: TrackingDailyMetric[]
}

export type TrackingLinkMetricsResponse = {
  link_id: string
  project_id: string
  bot_id: string
  code: string
  title: string
  base_conversion_rate: number
  min_sample_size: number
  conversion_status: TrackingConversionStatus
  date_from: string
  date_to: string
  summary: TrackingMetricSummary
  daily: TrackingDailyMetric[]
  funnel_steps: FunnelStepMetric[]
  age_breakdown: BreakdownItem[]
  country_breakdown: BreakdownItem[]
}

export type TrackingDateRangeParams = {
  date_from?: string
  date_to?: string
}

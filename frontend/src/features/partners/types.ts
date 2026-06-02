export type AuthType = 'header' | 'query_param' | 'bearer'

export type PartnerAuthConfig = {
  header_name?: string | null
  query_param_name?: string | null
  token?: string | null
}

export type PartnerResponseMapping = {
  status_path?: string
  success_key?: string | null
  success_value?: string | null
  success_values?: string[]
  duplicate_key?: string | null
  duplicate_value?: string | null
  duplicate_values?: string[]
  rejected_value?: string | null
  rejected_values?: string[]
  error_path?: string | null
  external_id_path?: string | null
  lead_id_path?: string | null
  submission_id_path?: string | null
  partner_status_path?: string | null
  status_mapping?: Record<string, string>
}

export type PartnerRetryConfig = {
  max_attempts: number
  delays_seconds: number[]
  timeout_seconds: number
}

export type PartnerIntegration = {
  id: string
  project_id: string
  name: string
  postback_url: string
  has_auth_token: boolean
  auth_type: AuthType
  auth_config: PartnerAuthConfig
  field_mapping: Record<string, string>
  required_fields: string[]
  response_mapping: PartnerResponseMapping
  retry_config: PartnerRetryConfig
  is_active: boolean
  created_at: string
  updated_at: string
}

export type PartnerIntegrationPayload = {
  project_id: string
  name: string
  postback_url: string
  auth_type: AuthType
  auth_config: PartnerAuthConfig
  field_mapping: Record<string, string>
  required_fields: string[]
  response_mapping: PartnerResponseMapping
  retry_config: PartnerRetryConfig
  is_active: boolean
}

export type PartnerConnectionTestResult = {
  ok: boolean
  connected: boolean
  mapping_valid: boolean
  accepted: boolean
  status: string
  status_code?: number | null
  request_payload: Record<string, unknown>
  response_payload?: Record<string, unknown> | null
  parsed_response?: Record<string, unknown> | null
  error_message?: string | null
}

export type LeadSubmissionPreview = {
  lead_id: string
  partner_id: string
  payload: Record<string, unknown>
}

export type SubmitLeadResponse = {
  status: string
  submission_id: string
}

export type LeadSubmission = {
  id: string
  lead_id: string
  partner_integration_id: string
  status: string
  request_payload: Record<string, unknown> | null
  response_payload: Record<string, unknown> | null
  error_message: string | null
  partner_status: string | null
  partner_status_updated_at: string | null
  submitted_at: string
  completed_at: string | null
}

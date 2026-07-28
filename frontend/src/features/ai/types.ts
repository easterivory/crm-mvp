export type AIAPIStyle = 'openai_compatible' | 'gemini'

export type AIModelPricing = {
  input_usd_per_million: number | string
  output_usd_per_million: number | string
}

export type AIProviderConnection = {
  id: string
  name: string
  provider: string
  api_style: AIAPIStyle
  base_url: string
  default_model: string | null
  is_active: boolean
  request_timeout_seconds: number
  supports_json_mode: boolean
  pricing: Record<string, AIModelPricing>
  has_api_key: boolean
  api_key_mask: string | null
  created_at: string
  updated_at: string
}

export type AIProviderOption = Pick<
  AIProviderConnection,
  'id' | 'name' | 'provider' | 'default_model'
>

export type AIProviderConnectionInput = {
  name: string
  provider: string
  api_style: AIAPIStyle
  base_url: string
  api_key?: string
  clear_api_key?: boolean
  default_model: string | null
  is_active: boolean
  request_timeout_seconds: number
  supports_json_mode: boolean
  pricing: Record<string, AIModelPricing>
}

export type AIProjectSettings = {
  project_id: string
  is_enabled: boolean
  primary_connection_id: string | null
  primary_model: string | null
  fallback_connection_id: string | null
  fallback_model: string | null
  master_prompt: string | null
  history_message_limit: number
  max_context_chars: number
  default_temperature: number | string
  default_max_output_tokens: number
  typing_delay_per_char_ms: number
  min_delay_ms: number
  max_delay_ms: number
  daily_budget_usd: number | string | null
  monthly_budget_usd: number | string | null
  created_at: string | null
  updated_at: string | null
}

export type AIProjectSettingsInput = Omit<
  AIProjectSettings,
  'project_id' | 'created_at' | 'updated_at'
>

export type AIModelList = {
  models: string[]
  live: boolean
  warning: string | null
}

export type AIProviderTestResult = {
  ok: boolean
  model: string
  latency_ms: number
  message: string
}

export type AIUsageLog = {
  id: string
  connection_id: string | null
  connection_name: string | null
  api_key_mask: string | null
  provider: string
  model: string
  status: 'success' | 'failed'
  used_fallback: boolean
  prompt_tokens: number | null
  completion_tokens: number | null
  total_tokens: number | null
  estimated_cost_usd: number | string | null
  latency_ms: number | null
  error_code: string | null
  error_message: string | null
  created_at: string
}

export type AIUsageList = {
  items: AIUsageLog[]
  total: number
}

export type AIUsageModelSummary = {
  provider: string
  model: string
  requests: number
  total_tokens: number
  estimated_cost_usd: number | string
  unknown_cost_requests: number
}

export type AIUsageConnectionSummary = {
  connection_id: string | null
  connection_name: string
  provider: string
  api_key_mask: string | null
  requests: number
  total_tokens: number
  estimated_cost_usd: number | string
  unknown_cost_requests: number
}

export type AIUsageSummary = {
  date_from: string
  date_to: string
  requests: number
  successful_requests: number
  failed_requests: number
  total_tokens: number
  estimated_cost_usd: number | string
  unknown_cost_requests: number
  average_latency_ms: number
  by_model: AIUsageModelSummary[]
  by_connection: AIUsageConnectionSummary[]
}

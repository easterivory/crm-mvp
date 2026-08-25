export type ManagerPerformance = {
  manager_id: string
  name: string
  email: string
  handler_code: string | null
  chats_taken: number
  chats_retained: number
  chats_expired: number
  answered_chats: number
  unanswered_chats: number
  average_first_response_seconds: number
  submitted_leads: number
  submissions_total: number
  manual_submissions: number
  auto_submissions: number
  valid_leads: number
  funnels_pushed: number
  returned_to_funnel: number
  registrations: number
  deposits: number
  redeposits: number
  taken_to_submitted_percent: number
  submitted_to_valid_percent: number
  taken_to_valid_percent: number
}

export type ManagerPerformanceParams = {
  project_id: string
  date_from?: string
  date_to?: string
}

export type ProjectCalculatorSnapshot = {
  project_id: string
  project_name: string
  project_format: 'submission' | 'gambling'
  bot_id: string | null
  date_from: string
  date_to: string
  clicks: number
  starts: number
  leads: number
  submitted_leads: number
  registrations: number
  first_deposits: number
  redeposits: number
  channel_join_requests: number
  channel_joins: number
  spend: number | string
}

export type ProjectCalculatorSnapshotParams = {
  project_id: string
  date_from?: string
  date_to?: string
  bot_id?: string
}

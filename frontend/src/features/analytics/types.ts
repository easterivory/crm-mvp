export type ManagerPerformance = {
  manager_id: string
  name: string
  email: string
  handler_code: string | null
  chats_taken: number
  submitted_leads: number
  valid_leads: number
  returned_to_funnel: number
  taken_to_submitted_percent: number
  submitted_to_valid_percent: number
  taken_to_valid_percent: number
}

export type ManagerPerformanceParams = {
  project_id: string
  date_from?: string
  date_to?: string
}

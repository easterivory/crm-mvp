export type GoogleSheetsConfig = {
  id: string
  project_id: string
  is_enabled: boolean
  spreadsheet_id: string | null
  sheet_name: string
  trigger_statuses: string[]
  service_account_email: string | null
  created_at: string
  updated_at: string
}

export type GoogleSheetsConfigUpdate = {
  spreadsheet_id?: string | null
  sheet_name?: string
  is_enabled?: boolean
  trigger_statuses?: string[]
}

export type GoogleSheetsTestConnectionResult = {
  success: boolean
  message: string
}

export type LeadStatusOption = {
  id: string
  code: string
  name: string
  sort_order: number
  is_final: boolean
  created_at: string
}

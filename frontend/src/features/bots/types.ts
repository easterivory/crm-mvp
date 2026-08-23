export type Bot = {
  id: string
  project_id: string
  name: string
  transport_type: 'bot_api' | 'user_mtproto'
  crm_description: string | null
  telegram_description: string | null
  telegram_about: string | null
  has_telegram_token: boolean
  telegram_bot_id: number | null
  telegram_first_name: string | null
  bot_username: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
  telegram_setup_warning?: string | null
}

export type TelegramAccountConnection = {
  bot_id: string
  auth_status: 'disconnected' | 'awaiting_code' | 'awaiting_password' | 'authorized' | 'error'
  connection_status: 'disconnected' | 'connecting' | 'connected' | 'error'
  api_id: number | null
  api_hash_last_four: string | null
  phone_number_masked: string | null
  telegram_user_id: number | null
  telegram_first_name: string | null
  telegram_last_name: string | null
  telegram_username: string | null
  auth_expires_at: string | null
  last_connected_at: string | null
  last_synced_at: string | null
  last_error: string | null
}

export type BotLeadImportStatus = 'created' | 'validated' | 'completed' | 'failed'

export type BotLeadImport = {
  id: string
  project_id: string
  bot_id: string
  source_system: string
  spreadsheet_id: string
  spreadsheet_url: string
  worksheet_title: string
  status: BotLeadImportStatus
  total_rows: number
  imported_count: number
  updated_count: number
  skipped_count: number
  error_count: number
  completed_at: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type LeadImportIssue = {
  row: number
  field: string
  level: 'error' | 'warning'
  message: string
}

export type LeadImportPreview = {
  import_id: string
  checksum: string
  can_import: boolean
  total_rows: number
  create_count: number
  skip_count: number
  error_count: number
  warning_count: number
  new_tags: string[]
  new_statuses: string[]
  issues: LeadImportIssue[]
}

export type LeadImportExecuteResult = {
  import_batch: BotLeadImport
  created_count: number
  skipped_count: number
  created_tag_count: number
  created_status_count: number
}

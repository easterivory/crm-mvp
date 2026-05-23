export type Bot = {
  id: string
  project_id: string
  name: string
  has_telegram_token: boolean
  telegram_bot_id: number | null
  telegram_first_name: string | null
  bot_username: string | null
  created_at: string
  updated_at: string
  is_deleted: boolean
}

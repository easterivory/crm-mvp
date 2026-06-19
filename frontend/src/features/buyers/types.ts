export type BuyerCreatePayload = {
  name: string
  email: string
  password: string
}

export type BuyerUser = {
  id: string
  email: string
  name: string
  project_id: string | null
  role_name?: string | null
  buyer_telegram_id: number | null
  created_at: string
}

export type BuyerInvite = {
  buyer: BuyerUser
  invite_token: string
  invite_link: string
}

export type BuyerBotConfig = {
  token: string | null
  username: string | null
}

export type BuyerPerformance = {
  buyer_id: string
  name: string
  email: string
  buyer_telegram_id: number | null
  links_count: number
  total_spend: number | string
  clicks: number
  leads: number
  lead_conversion_percent: number | string
  cpl: number | string
  submitted_leads: number
  submitted_conversion_percent: number | string
}

export type SnippetMediaType = 'photo' | 'video' | 'voice' | 'video_note' | 'document'
export type SnippetType = 'text' | SnippetMediaType

export type ProjectSnippet = {
  id: string
  project_id: string
  channel: 'telegram'
  name: string
  type: SnippetType
  content: string | null
  file_id: string | null
  file_name: string | null
  mime_type: string | null
  file_size: number | null
  preview_available: boolean
  created_at: string
}

export type SnippetUpdatePayload = {
  name?: string
  content?: string | null
}

export const TELEGRAM_TEXT_LIMIT = 4096
export const TELEGRAM_CAPTION_LIMIT = 1024

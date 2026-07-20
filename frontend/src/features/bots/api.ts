import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type { Bot } from './types'

export async function fetchBots(projectId?: string): Promise<Bot[]> {
  const { data } = await api.get<PaginatedResponse<Bot>>('/bots', {
    params: {
      limit: 100,
      offset: 0,
      ...(projectId ? { project_id: projectId } : {}),
    },
  })

  return data.items
}

export type BotUpdatePayload = Partial<{
  name: string
  telegram_token: string
  crm_description: string | null
  telegram_description: string | null
  telegram_about: string | null
}>

export async function updateBot(
  botId: string,
  payload: BotUpdatePayload,
  projectId?: string | null,
): Promise<Bot> {
  const { data } = await api.patch<Bot>(`/bots/${botId}`, payload, {
    params: projectId ? { project_id: projectId } : undefined,
  })

  return data
}

export async function uploadBotAvatar(
  botId: string,
  file: File,
  projectId?: string | null,
): Promise<void> {
  const formData = new FormData()
  formData.append('file', file)
  await api.post(`/bots/${botId}/avatar`, formData, {
    params: projectId ? { project_id: projectId } : undefined,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export async function fetchBotAvatar(
  botId: string,
  projectId?: string | null,
): Promise<Blob> {
  const { data } = await api.get<Blob>(`/bots/${botId}/avatar`, {
    params: projectId ? { project_id: projectId } : undefined,
    responseType: 'blob',
  })
  return data
}

export async function downloadBotAuditLogs(
  botId: string,
  projectId?: string | null,
): Promise<void> {
  const { data } = await api.get<Blob>(`/bots/${botId}/audit-logs/export`, {
    params: projectId ? { project_id: projectId } : undefined,
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = 'bot_audit_logs.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000)
}

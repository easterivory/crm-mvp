import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  Bot,
  BotLeadImport,
  LeadImportExecuteResult,
  LeadImportPreview,
  TelegramAccountConnection,
} from './types'

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

function telegramAccountParams(projectId?: string | null) {
  return projectId ? { project_id: projectId } : undefined
}

export async function fetchTelegramAccountConnection(
  botId: string,
  projectId?: string | null,
): Promise<TelegramAccountConnection> {
  const { data } = await api.get<TelegramAccountConnection>(`/bots/${botId}/telegram-account`, {
    params: telegramAccountParams(projectId),
  })
  return data
}

export async function requestTelegramAccountCode(
  botId: string,
  payload: { api_id: number; api_hash: string; phone_number: string },
  projectId?: string | null,
): Promise<TelegramAccountConnection> {
  const { data } = await api.post<TelegramAccountConnection>(
    `/bots/${botId}/telegram-account/request-code`,
    payload,
    { params: telegramAccountParams(projectId) },
  )
  return data
}

export async function confirmTelegramAccountCode(
  botId: string,
  code: string,
  projectId?: string | null,
): Promise<TelegramAccountConnection> {
  const { data } = await api.post<TelegramAccountConnection>(
    `/bots/${botId}/telegram-account/confirm-code`,
    { code },
    { params: telegramAccountParams(projectId) },
  )
  return data
}

export async function confirmTelegramAccountPassword(
  botId: string,
  password: string,
  projectId?: string | null,
): Promise<TelegramAccountConnection> {
  const { data } = await api.post<TelegramAccountConnection>(
    `/bots/${botId}/telegram-account/confirm-password`,
    { password },
    { params: telegramAccountParams(projectId) },
  )
  return data
}

export async function syncTelegramAccount(
  botId: string,
  projectId?: string | null,
): Promise<TelegramAccountConnection> {
  const { data } = await api.post<TelegramAccountConnection>(
    `/bots/${botId}/telegram-account/sync`,
    null,
    { params: telegramAccountParams(projectId) },
  )
  return data
}

export async function disconnectTelegramAccount(
  botId: string,
  projectId?: string | null,
): Promise<void> {
  await api.delete(`/bots/${botId}/telegram-account`, {
    params: telegramAccountParams(projectId),
  })
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

export async function fetchBotLeadImports(
  botId: string,
  projectId: string,
): Promise<BotLeadImport[]> {
  const { data } = await api.get<BotLeadImport[]>(`/bots/${botId}/lead-imports`, {
    params: { project_id: projectId },
  })
  return data
}

export async function createBotLeadImportTemplate(
  botId: string,
  projectId: string,
): Promise<BotLeadImport> {
  const { data } = await api.post<BotLeadImport>(`/bots/${botId}/lead-imports`, null, {
    params: { project_id: projectId },
  })
  return data
}

export async function previewBotLeadImport(
  botId: string,
  importId: string,
  projectId: string,
): Promise<LeadImportPreview> {
  const { data } = await api.post<LeadImportPreview>(
    `/bots/${botId}/lead-imports/${importId}/preview`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function executeBotLeadImport(
  botId: string,
  importId: string,
  projectId: string,
  previewChecksum: string,
): Promise<LeadImportExecuteResult> {
  const { data } = await api.post<LeadImportExecuteResult>(
    `/bots/${botId}/lead-imports/${importId}/execute`,
    { preview_checksum: previewChecksum },
    { params: { project_id: projectId } },
  )
  return data
}

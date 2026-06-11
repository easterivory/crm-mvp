import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  AudienceFilter,
  AudiencePreview,
  Broadcast,
  BroadcastActionResponse,
  BroadcastContent,
  BroadcastDeliveryAnalytics,
  BroadcastReport,
  BroadcastTemplate,
  BroadcastUpload,
  BroadcastMediaType,
  ProjectSnippet,
} from './types'

export async function fetchBroadcasts(projectId: string) {
  const { data } = await api.get<PaginatedResponse<Broadcast>>('/broadcasts', {
    params: { project_id: projectId, limit: 100, offset: 0 },
  })
  return data.items
}

export async function fetchBroadcastReport(broadcastId: string, projectId: string) {
  const { data } = await api.get<BroadcastReport>(`/broadcasts/${broadcastId}/report`, {
    params: { project_id: projectId },
  })
  return data
}

export async function fetchBroadcastDetailedAnalytics(broadcastId: string, projectId: string) {
  const { data } = await api.get<BroadcastDeliveryAnalytics>(`/broadcasts/${broadcastId}/detailed-analytics`, {
    params: { project_id: projectId },
  })
  return data
}

export async function downloadBroadcastErrorsCsv(broadcastId: string, projectId: string) {
  const { data } = await api.get<Blob>(`/broadcasts/${broadcastId}/report`, {
    params: { project_id: projectId, format: 'csv' },
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = `broadcast-${broadcastId}-errors.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000)
}

export async function fetchProjectSnippets(projectId: string) {
  const { data } = await api.get<ProjectSnippet[]>(`/projects/${projectId}/snippets`, {
    params: { project_id: projectId },
  })
  return data
}

export async function fetchBroadcastTemplates(projectId: string) {
  const { data } = await api.get<BroadcastTemplate[]>('/broadcasts/templates', {
    params: { project_id: projectId, limit: 100, offset: 0 },
  })
  return data
}

export async function createBroadcastTemplate(payload: {
  project_id: string
  name: string
  content_json: BroadcastContent
}) {
  const { data } = await api.post<BroadcastTemplate>('/broadcasts/templates', payload, {
    params: { project_id: payload.project_id },
  })
  return data
}

export async function updateBroadcastTemplate(
  templateId: string,
  projectId: string,
  payload: Partial<{ name: string; content_json: BroadcastContent }>,
) {
  const { data } = await api.patch<BroadcastTemplate>(
    `/broadcasts/templates/${templateId}`,
    payload,
    { params: { project_id: projectId } },
  )
  return data
}

export async function deleteBroadcastTemplate(templateId: string, projectId: string) {
  await api.delete(`/broadcasts/templates/${templateId}`, {
    params: { project_id: projectId },
  })
}

export async function uploadBroadcastMedia(
  projectId: string,
  file: File,
  mediaType: BroadcastMediaType,
) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('media_type', mediaType)
  const { data } = await api.post<BroadcastUpload>('/broadcasts/uploads', formData, {
    params: { project_id: projectId },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function createBroadcast(payload: {
  project_id: string
  bot_id: string | null
  name: string
  content_json: BroadcastContent
  audience_filter_json: AudienceFilter
  schedule_type?: 'now' | 'scheduled'
  scheduled_at?: string | null
  timezone_mode?: 'project' | 'lead_local' | 'fixed'
  snippet_id?: string | null
  media_type?: 'text' | BroadcastMediaType | null
  file_id?: string | null
  trigger_funnel_id?: string | null
  stop_on_reply?: boolean
}) {
  const { data } = await api.post<Broadcast>('/broadcasts', payload, {
    params: { project_id: payload.project_id },
  })
  return data
}

export async function updateBroadcast(
  broadcastId: string,
  projectId: string,
  payload: Partial<{
    bot_id: string | null
    name: string
    content_json: BroadcastContent
    audience_filter_json: AudienceFilter
    schedule_type: 'now' | 'scheduled'
    scheduled_at: string | null
    timezone_mode: 'project' | 'lead_local' | 'fixed'
    snippet_id: string | null
    media_type: 'text' | BroadcastMediaType | null
    file_id: string | null
    trigger_funnel_id: string | null
    stop_on_reply: boolean
  }>,
) {
  const { data } = await api.patch<Broadcast>(`/broadcasts/${broadcastId}`, payload, {
    params: { project_id: projectId },
  })
  return data
}

export async function deleteBroadcast(broadcastId: string, projectId: string) {
  await api.delete(`/broadcasts/${broadcastId}`, {
    params: { project_id: projectId },
  })
}

export async function previewAudience(payload: {
  project_id: string
  bot_id: string | null
  audience_filter: AudienceFilter
}) {
  const { data } = await api.post<AudiencePreview>('/broadcasts/audience/preview', payload, {
    params: { project_id: payload.project_id },
  })
  return data
}

export async function sendBroadcastNow(
  broadcastId: string,
  projectId: string,
  confirmation?: string,
) {
  const { data } = await api.post<BroadcastActionResponse>(
    `/broadcasts/${broadcastId}/send-now`,
    { confirmation },
    { params: { project_id: projectId } },
  )
  return data
}

export async function scheduleBroadcast(
  broadcastId: string,
  projectId: string,
  payload: {
    scheduled_at: string
    timezone_mode: 'project' | 'lead_local' | 'fixed'
    confirmation?: string
  },
) {
  const { data } = await api.post<BroadcastActionResponse>(
    `/broadcasts/${broadcastId}/schedule`,
    payload,
    { params: { project_id: projectId } },
  )
  return data
}

export async function cancelBroadcast(broadcastId: string, projectId: string) {
  const { data } = await api.post<Broadcast>(
    `/broadcasts/${broadcastId}/cancel`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function pauseBroadcast(broadcastId: string, projectId: string) {
  const { data } = await api.post<Broadcast>(
    `/broadcasts/${broadcastId}/pause`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function resumeBroadcast(broadcastId: string, projectId: string) {
  const { data } = await api.post<Broadcast>(
    `/broadcasts/${broadcastId}/resume`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  AudienceFilter,
  AudiencePreview,
  Broadcast,
  BroadcastActionResponse,
  BroadcastContent,
  BroadcastReport,
  BroadcastTemplate,
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

export async function createBroadcast(payload: {
  project_id: string
  bot_id: string | null
  name: string
  content_json: BroadcastContent
  audience_filter_json: AudienceFilter
  schedule_type?: 'now' | 'scheduled'
  scheduled_at?: string | null
  timezone_mode?: 'project' | 'lead_local' | 'fixed'
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
  }>,
) {
  const { data } = await api.patch<Broadcast>(`/broadcasts/${broadcastId}`, payload, {
    params: { project_id: projectId },
  })
  return data
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

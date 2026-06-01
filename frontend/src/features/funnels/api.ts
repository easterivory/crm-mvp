import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  CopyFunnelPayload,
  CopyFunnelResult,
  CreateFunnelPayload,
  Funnel,
  BotActiveFunnel,
  FunnelBlockRegistry,
  FunnelDropOffAnalytics,
  FunnelGraph,
  FunnelValidationResult,
  FunnelVersion,
} from './types'

export async function fetchFunnels(params: {
  projectId: string
  botId?: string | null
  status?: string
}): Promise<PaginatedResponse<Funnel>> {
  const { data } = await api.get<PaginatedResponse<Funnel>>('/funnels', {
    params: {
      limit: 100,
      offset: 0,
      project_id: params.projectId,
      ...(params.botId ? { bot_id: params.botId } : {}),
      ...(params.status ? { status: params.status } : {}),
    },
  })
  return data
}

export async function createFunnel(payload: CreateFunnelPayload): Promise<Funnel> {
  const { data } = await api.post<Funnel>('/funnels', payload, {
    params: { project_id: payload.project_id },
  })
  return data
}

export async function archiveFunnel(funnel: Funnel): Promise<Funnel> {
  const { data } = await api.post<Funnel>(`/funnels/${funnel.id}/archive`, null, {
    params: { project_id: funnel.project_id },
  })
  return data
}

export async function fetchFunnel(
  funnelId: string,
  projectId: string,
): Promise<Funnel> {
  const { data } = await api.get<Funnel>(`/funnels/${funnelId}`, {
    params: { project_id: projectId },
  })
  return data
}

export async function fetchVersions(
  funnelId: string,
  projectId: string,
): Promise<FunnelVersion[]> {
  const { data } = await api.get<FunnelVersion[]>(`/funnels/${funnelId}/versions`, {
    params: { project_id: projectId },
  })
  return data
}

export async function createDraftVersion(
  funnelId: string,
  projectId: string,
): Promise<FunnelVersion> {
  const { data } = await api.post<FunnelVersion>(
    `/funnels/${funnelId}/versions/draft`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function createDraftFromVersion(
  funnelId: string,
  versionId: string,
  projectId: string,
): Promise<FunnelVersion> {
  const { data } = await api.post<FunnelVersion>(
    `/funnels/${funnelId}/versions/${versionId}/draft`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function fetchGraph(
  funnelId: string,
  versionId: string,
  projectId: string,
): Promise<FunnelGraph> {
  const { data } = await api.get<FunnelGraph>(
    `/funnels/${funnelId}/versions/${versionId}/graph`,
    { params: { project_id: projectId } },
  )
  return data
}

export async function saveGraph(
  funnelId: string,
  versionId: string,
  projectId: string,
  graph: FunnelGraph,
): Promise<FunnelGraph> {
  const { data } = await api.put<FunnelGraph>(
    `/funnels/${funnelId}/versions/${versionId}/graph`,
    graph,
    { params: { project_id: projectId } },
  )
  return data
}

export async function validateFunnelVersion(
  funnelId: string,
  versionId: string,
  projectId: string,
): Promise<FunnelValidationResult> {
  const { data } = await api.post<FunnelValidationResult>(
    `/funnels/${funnelId}/versions/${versionId}/validate`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function publishFunnelVersion(
  funnelId: string,
  versionId: string,
  projectId: string,
): Promise<FunnelVersion> {
  const { data } = await api.post<FunnelVersion>(
    `/funnels/${funnelId}/versions/${versionId}/publish`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function setFunnelHoldMode(
  funnelId: string,
  versionId: string,
  projectId: string,
  isHoldActive: boolean,
): Promise<FunnelVersion> {
  const { data } = await api.post<FunnelVersion>(
    `/funnels/${funnelId}/versions/${versionId}/toggle-hold`,
    { is_hold_active: isHoldActive },
    { params: { project_id: projectId } },
  )
  return data
}

export async function fetchDropOffAnalytics(
  funnelId: string,
  versionId: string,
  projectId: string,
): Promise<FunnelDropOffAnalytics> {
  const { data } = await api.get<FunnelDropOffAnalytics>(
    `/funnels/${funnelId}/versions/${versionId}/analytics/drop-off`,
    { params: { project_id: projectId } },
  )
  return data
}

export async function fetchBotActiveFunnel(
  botId: string,
  projectId: string,
): Promise<BotActiveFunnel> {
  const { data } = await api.get<BotActiveFunnel>(`/bots/${botId}/active-funnel`, {
    params: { project_id: projectId },
  })
  return data
}

export async function setBotActiveFunnel(
  botId: string,
  projectId: string,
  payload: { funnel_id: string; version_id: string },
): Promise<BotActiveFunnel> {
  const { data } = await api.post<BotActiveFunnel>(
    `/bots/${botId}/active-funnel`,
    payload,
    { params: { project_id: projectId } },
  )
  return data
}

export async function copyFunnel(
  funnel: Funnel,
  payload: CopyFunnelPayload,
): Promise<CopyFunnelResult> {
  const { data } = await api.post<CopyFunnelResult>(
    `/funnels/${funnel.id}/copy`,
    payload,
    { params: { project_id: funnel.project_id } },
  )
  return data
}

export async function fetchBlockRegistry(): Promise<FunnelBlockRegistry> {
  const { data } = await api.get<FunnelBlockRegistry>('/funnels/block-registry')
  return data
}

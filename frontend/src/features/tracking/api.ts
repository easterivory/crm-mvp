import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  TrackingDateRangeParams,
  TrackingLink,
  TrackingLinkCreatePayload,
  TrackingLinkMetricsResponse,
  TrackingLinkUpdatePayload,
  TrackingFunnelStepOption,
  ManagerPerformance,
  TrackingMetricSummary,
  TrackingProjectMetricsResponse,
  TrackingSpend,
  TrackingSpendCreatePayload,
  TrackingSpendUpdatePayload,
} from './types'

type TrackingLinksParams = {
  project_id: string
  bot_id?: string
  is_active?: boolean
  limit?: number
  offset?: number
}

type ProjectMetricsParams = TrackingDateRangeParams & {
  project_id: string
  bot_id?: string
}

type SpendListParams = TrackingDateRangeParams

type ManagerPerformanceParams = TrackingDateRangeParams & {
  project_id: string
}

export async function fetchTrackingLinks(
  params: TrackingLinksParams,
): Promise<PaginatedResponse<TrackingLink>> {
  const { data } = await api.get<PaginatedResponse<TrackingLink>>('/tracking/links', {
    params: {
      limit: 50,
      offset: 0,
      ...params,
    },
  })

  return data
}

export async function fetchTrackingTargetSteps(
  projectId: string,
  botId: string,
): Promise<TrackingFunnelStepOption[]> {
  const { data } = await api.get<TrackingFunnelStepOption[]>('/tracking/links/target-steps', {
    params: { project_id: projectId, bot_id: botId },
  })
  return data
}

export async function createTrackingLink(
  payload: TrackingLinkCreatePayload,
): Promise<TrackingLink> {
  const { data } = await api.post<TrackingLink>('/tracking/links', payload)
  return data
}

export async function updateTrackingLink(
  linkId: string,
  payload: TrackingLinkUpdatePayload,
): Promise<TrackingLink> {
  const { data } = await api.patch<TrackingLink>(`/tracking/links/${linkId}`, payload)
  return data
}

export async function archiveTrackingLink(linkId: string): Promise<TrackingLink> {
  const { data } = await api.post<TrackingLink>(`/tracking/links/${linkId}/archive`)
  return data
}

export async function restoreTrackingLink(linkId: string): Promise<TrackingLink> {
  const { data } = await api.post<TrackingLink>(`/tracking/links/${linkId}/restore`)
  return data
}

export async function fetchTrackingSpends(
  linkId: string,
  params?: SpendListParams,
): Promise<TrackingSpend[]> {
  const { data } = await api.get<TrackingSpend[]>(
    `/tracking/links/${linkId}/spends`,
    { params },
  )
  return data
}

export async function createTrackingSpend(
  linkId: string,
  payload: TrackingSpendCreatePayload,
): Promise<TrackingSpend> {
  const { data } = await api.post<TrackingSpend>(
    `/tracking/links/${linkId}/spends`,
    payload,
  )
  return data
}

export async function updateTrackingSpend(
  spendId: string,
  payload: TrackingSpendUpdatePayload,
): Promise<TrackingSpend> {
  const { data } = await api.patch<TrackingSpend>(`/tracking/spends/${spendId}`, payload)
  return data
}

export async function deleteTrackingSpend(spendId: string): Promise<void> {
  await api.delete(`/tracking/spends/${spendId}`)
}

export async function fetchProjectTrackingMetrics(
  params: ProjectMetricsParams,
): Promise<TrackingProjectMetricsResponse> {
  const { data } = await api.get<TrackingProjectMetricsResponse>(
    '/tracking/metrics/project',
    { params },
  )
  return data
}

export async function fetchLinkTrackingMetrics(
  linkId: string,
  params?: TrackingDateRangeParams,
): Promise<TrackingLinkMetricsResponse> {
  const { data } = await api.get<TrackingLinkMetricsResponse>(
    `/tracking/metrics/links/${linkId}`,
    { params },
  )
  return data
}

export async function fetchTrackingHeaderMetrics(
  params: ProjectMetricsParams,
): Promise<TrackingMetricSummary> {
  const { data } = await api.get<TrackingMetricSummary>('/tracking/metrics/header', {
    params,
  })
  return data
}

export async function fetchManagerPerformance(
  params: ManagerPerformanceParams,
): Promise<ManagerPerformance[]> {
  const { data } = await api.get<ManagerPerformance[]>('/analytics/managers', { params })
  return data
}

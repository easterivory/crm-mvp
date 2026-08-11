import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  ProjectDomain,
  ProjectDomainCreatePayload,
  ProjectLander,
  ProjectLanderCreatePayload,
  ProjectLanderUpdatePayload,
  ProjectLanderUploadResult,
  LanderTargetStep,
  LanderRuntimeConfig,
  TrackingLinkOption,
  TelegramChannel,
  TelegramChannelCreatePayload,
} from './types'

export async function fetchProjectDomains(projectId: string): Promise<ProjectDomain[]> {
  const { data } = await api.get<ProjectDomain[]>(`/projects/${projectId}/domains`)
  return data
}

export async function createProjectDomain(
  projectId: string,
  payload: ProjectDomainCreatePayload,
): Promise<ProjectDomain> {
  const { data } = await api.post<ProjectDomain>(
    `/projects/${projectId}/domains`,
    payload,
  )
  return data
}

export async function deleteProjectDomain(
  projectId: string,
  domainId: string,
): Promise<void> {
  await api.delete(`/projects/${projectId}/domains/${domainId}`)
}

export async function fetchProjectLanders(projectId: string): Promise<ProjectLander[]> {
  const { data } = await api.get<ProjectLander[]>(`/projects/${projectId}/landers`)
  return data
}

export async function fetchLanderRuntimeConfig(
  projectId: string,
): Promise<LanderRuntimeConfig> {
  const { data } = await api.get<LanderRuntimeConfig>(`/projects/${projectId}/landers/config`)
  return data
}

export async function createProjectLander(
  projectId: string,
  payload: ProjectLanderCreatePayload,
): Promise<ProjectLander> {
  const { data } = await api.post<ProjectLander>(
    `/projects/${projectId}/landers`,
    payload,
  )
  return data
}

export async function updateProjectLander(
  projectId: string,
  landerId: string,
  payload: ProjectLanderUpdatePayload,
): Promise<ProjectLander> {
  const { data } = await api.patch<ProjectLander>(
    `/projects/${projectId}/landers/${landerId}`,
    payload,
  )
  return data
}

export async function uploadProjectLanderZip(
  projectId: string,
  landerId: string,
  file: File,
): Promise<ProjectLanderUploadResult> {
  const formData = new FormData()
  formData.append('file', file)
  const { data } = await api.post<ProjectLanderUploadResult>(
    `/projects/${projectId}/landers/${landerId}/upload`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  )
  return data
}

export async function deleteProjectLander(
  projectId: string,
  landerId: string,
): Promise<void> {
  await api.delete(`/projects/${projectId}/landers/${landerId}`)
}

export async function fetchActiveTrackingLinks(
  projectId: string,
): Promise<TrackingLinkOption[]> {
  const { data } = await api.get<PaginatedResponse<TrackingLinkOption>>(
    '/tracking/links',
    {
      params: {
        project_id: projectId,
        is_active: true,
        limit: 100,
        offset: 0,
      },
    },
  )
  return data.items
}

export async function fetchLanderTargetSteps(
  projectId: string,
  botId: string,
): Promise<LanderTargetStep[]> {
  const { data } = await api.get<LanderTargetStep[]>('/tracking/links/target-steps', {
    params: { project_id: projectId, bot_id: botId },
  })
  return data
}

export async function fetchTelegramChannels(
  projectId: string,
): Promise<TelegramChannel[]> {
  const { data } = await api.get<TelegramChannel[]>(
    `/projects/${projectId}/telegram-channels`,
  )
  return data
}

export async function createTelegramChannel(
  projectId: string,
  payload: TelegramChannelCreatePayload,
): Promise<TelegramChannel> {
  const { data } = await api.post<TelegramChannel>(
    `/projects/${projectId}/telegram-channels`,
    payload,
  )
  return data
}

export async function verifyTelegramChannel(
  projectId: string,
  channelId: string,
): Promise<TelegramChannel> {
  const { data } = await api.post<TelegramChannel>(
    `/projects/${projectId}/telegram-channels/${channelId}/verify`,
  )
  return data
}

export async function deleteTelegramChannel(
  projectId: string,
  channelId: string,
): Promise<void> {
  await api.delete(`/projects/${projectId}/telegram-channels/${channelId}`)
}

export async function fetchTelegramChannelAvatar(
  projectId: string,
  channelId: string,
): Promise<Blob> {
  const { data } = await api.get<Blob>(
    `/projects/${projectId}/telegram-channels/${channelId}/avatar`,
    { responseType: 'blob' },
  )
  return data
}

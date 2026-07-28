import api from '../../api/client'
import type {
  AIModelList,
  AIProjectSettings,
  AIProjectSettingsInput,
  AIProviderConnection,
  AIProviderConnectionInput,
  AIProviderOption,
  AIProviderTestResult,
  AIUsageList,
  AIUsageSummary,
} from './types'

export async function fetchAIProviders() {
  const { data } = await api.get<AIProviderConnection[]>('/ai/providers')
  return data
}

export async function fetchAIProviderOptions(projectId: string) {
  const { data } = await api.get<AIProviderOption[]>(
    `/ai/projects/${projectId}/provider-options`,
  )
  return data
}

export async function createAIProvider(payload: AIProviderConnectionInput) {
  const { data } = await api.post<AIProviderConnection>('/ai/providers', payload)
  return data
}

export async function updateAIProvider(
  connectionId: string,
  payload: Partial<AIProviderConnectionInput>,
) {
  const { data } = await api.patch<AIProviderConnection>(
    `/ai/providers/${connectionId}`,
    payload,
  )
  return data
}

export async function deleteAIProvider(connectionId: string) {
  await api.delete(`/ai/providers/${connectionId}`)
}

export async function testAIProvider(connectionId: string, model?: string | null) {
  const { data } = await api.post<AIProviderTestResult>(
    `/ai/providers/${connectionId}/test`,
    { model: model || null },
  )
  return data
}

export async function fetchAIProviderModels(connectionId: string) {
  const { data } = await api.get<AIModelList>(
    `/ai/providers/${connectionId}/models`,
  )
  return data
}

export async function fetchAIProjectSettings(projectId: string) {
  const { data } = await api.get<AIProjectSettings>(
    `/ai/projects/${projectId}/settings`,
  )
  return data
}

export async function updateAIProjectSettings(
  projectId: string,
  payload: AIProjectSettingsInput,
) {
  const { data } = await api.put<AIProjectSettings>(
    `/ai/projects/${projectId}/settings`,
    payload,
  )
  return data
}

export async function fetchAIUsage(
  projectId: string,
  dateFrom: string,
  dateTo: string,
) {
  const { data } = await api.get<AIUsageList>('/ai/usage', {
    params: {
      project_id: projectId,
      date_from: dateFrom,
      date_to: dateTo,
      limit: 100,
      offset: 0,
    },
  })
  return data
}

export async function fetchAIUsageSummary(
  projectId: string,
  dateFrom: string,
  dateTo: string,
) {
  const { data } = await api.get<AIUsageSummary>('/ai/usage/summary', {
    params: {
      project_id: projectId,
      date_from: dateFrom,
      date_to: dateTo,
    },
  })
  return data
}

import api from '../../api/client'

import type { ChatFilterPreset, ChatFiltersState, FunnelRuntimeLog } from './types'

export async function fetchChatFilterPresets(projectId: string) {
  const { data } = await api.get<ChatFilterPreset[]>('/chats/filter-presets', {
    params: { project_id: projectId },
  })
  return data
}

export async function createChatFilterPreset(payload: {
  project_id: string
  name: string
  filters_json: ChatFiltersState
  is_shared: boolean
}) {
  const { data } = await api.post<ChatFilterPreset>('/chats/filter-presets', payload)
  return data
}

export async function updateChatFilterPreset(
  presetId: string,
  payload: Partial<{
    name: string
    filters_json: ChatFiltersState
    is_shared: boolean
  }>,
) {
  const { data } = await api.patch<ChatFilterPreset>(
    `/chats/filter-presets/${presetId}`,
    payload,
  )
  return data
}

export async function deleteChatFilterPreset(presetId: string) {
  await api.delete(`/chats/filter-presets/${presetId}`)
}

export async function fetchFunnelTrace(
  chatId: string,
  projectId: string,
): Promise<FunnelRuntimeLog[]> {
  const { data } = await api.get<FunnelRuntimeLog[]>(`/chats/${chatId}/funnel-trace`, {
    params: { project_id: projectId },
  })
  return data
}

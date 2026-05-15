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

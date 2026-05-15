import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type { Project } from './types'

export async function fetchProjects(): Promise<Project[]> {
  const { data } = await api.get<PaginatedResponse<Project>>('/projects', {
    params: { limit: 100, offset: 0 },
  })

  return data.items
}

import api from '../../api/client'

import type { ManagerPerformance, ManagerPerformanceParams } from './types'

export async function fetchManagerPerformance(
  params: ManagerPerformanceParams,
): Promise<ManagerPerformance[]> {
  const { data } = await api.get<ManagerPerformance[]>('/analytics/managers', { params })
  return data
}

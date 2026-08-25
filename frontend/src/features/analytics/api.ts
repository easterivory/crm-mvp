import api from '../../api/client'

import type {
  ManagerPerformance,
  ManagerPerformanceParams,
  ProjectCalculatorSnapshot,
  ProjectCalculatorSnapshotParams,
} from './types'

export async function fetchManagerPerformance(
  params: ManagerPerformanceParams,
): Promise<ManagerPerformance[]> {
  const { data } = await api.get<ManagerPerformance[]>('/analytics/managers', { params })
  return data
}

export async function fetchProjectCalculatorSnapshot(
  params: ProjectCalculatorSnapshotParams,
): Promise<ProjectCalculatorSnapshot> {
  const { data } = await api.get<ProjectCalculatorSnapshot>(
    '/analytics/project-calculator',
    { params },
  )
  return data
}

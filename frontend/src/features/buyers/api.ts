import api from '../../api/client'

import type { BuyerCreatePayload, BuyerInvite, BuyerPerformance } from './types'

export async function createBuyer(
  payload: BuyerCreatePayload,
  projectId: string | null,
): Promise<BuyerInvite> {
  const { data } = await api.post<BuyerInvite>('/buyers', payload, {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return data
}

export async function fetchBuyerPerformance(
  projectId: string | null,
): Promise<BuyerPerformance[]> {
  const { data } = await api.get<BuyerPerformance[]>('/analytics/buyers', {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return data
}

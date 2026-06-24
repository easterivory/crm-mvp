import api from '../../api/client'

import type { BuyerBotConfig, BuyerCreatePayload, BuyerInvite, BuyerPerformance } from './types'

export async function createBuyer(
  payload: BuyerCreatePayload,
  projectId: string | null,
): Promise<BuyerInvite> {
  const { data } = await api.post<BuyerInvite>('/buyers', payload, {
    params: projectId ? { project_id: projectId } : undefined,
  })
  return data
}

export async function deleteBuyer(buyerId: string, projectId: string | null): Promise<void> {
  await api.delete(`/buyers/${buyerId}`, {
    params: projectId ? { project_id: projectId } : undefined,
  })
}

export async function fetchBuyerPerformance(
  projectId: string | null,
  filters?: { date_from?: string; date_to?: string; bot_id?: string },
): Promise<BuyerPerformance[]> {
  const { data } = await api.get<BuyerPerformance[]>('/analytics/buyers', {
    params: {
      ...(projectId ? { project_id: projectId } : {}),
      ...filters,
    },
  })
  return data
}

export async function fetchBuyerBotConfig(): Promise<BuyerBotConfig> {
  const { data } = await api.get<BuyerBotConfig>('/settings/buyer-bot')
  return data
}

export async function updateBuyerBotConfig(payload: BuyerBotConfig): Promise<BuyerBotConfig> {
  const { data } = await api.patch<BuyerBotConfig>('/settings/buyer-bot', payload)
  return data
}

import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type { Lead, LeadListParams, LeadStatus } from './types'

export async function fetchLeads(params: LeadListParams) {
  const { data } = await api.get<PaginatedResponse<Lead>>('/leads', {
    params: {
      project_id: params.project_id,
      bot_ids: params.bot_ids?.length ? params.bot_ids.join(',') : undefined,
      status: params.status || undefined,
      date_from: params.date_from || undefined,
      date_to: params.date_to || undefined,
      tag_ids: params.tag_ids?.length ? params.tag_ids.join(',') : undefined,
      search: params.search?.trim() || undefined,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  })

  return data
}

export async function fetchLeadStatuses() {
  const { data } = await api.get<LeadStatus[]>('/leads/statuses')
  return data
}

export async function submitLead(leadId: string, projectId: string) {
  const { data } = await api.post<Lead>(`/leads/${leadId}/submit`, null, {
    params: { project_id: projectId },
  })
  return data
}

export async function rejectLead(leadId: string, projectId: string) {
  const { data } = await api.post<Lead>(`/leads/${leadId}/reject`, null, {
    params: { project_id: projectId },
  })
  return data
}

export async function fetchPartnerIntegrations(projectId: string) {
  const { data } = await api.get<PaginatedResponse<{ id: string; name: string; is_active: boolean }>>('/partners', {
    params: { project_id: projectId, limit: 100, offset: 0 },
  })
  return data.items
}

export async function submitLeadToPartner(
  leadId: string,
  partnerIntegrationId: string,
  projectId: string,
) {
  const { data } = await api.post(
    '/partners/submit',
    { lead_id: leadId, partner_integration_id: partnerIntegrationId },
    { params: { project_id: projectId } },
  )
  return data
}

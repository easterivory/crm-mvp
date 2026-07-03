import api from '../../api/client'
import type { PaginatedResponse } from '../../shared/types'
import type {
  LeadSubmission,
  LeadSubmissionPreview,
  PartnerConnectionTestResult,
  PartnerIntegration,
  PartnerIntegrationPayload,
  SubmitLeadResponse,
} from './types'

export async function fetchPartnerIntegrations(projectId: string, limit = 100) {
  const { data } = await api.get<PaginatedResponse<PartnerIntegration>>('/partners', {
    params: { project_id: projectId, limit, offset: 0 },
  })
  return data
}

export async function createPartnerIntegration(payload: PartnerIntegrationPayload) {
  const { data } = await api.post<PartnerIntegration>('/partners', payload)
  return data
}

export async function updatePartnerIntegration(
  partnerId: string,
  projectId: string,
  payload: Partial<PartnerIntegrationPayload>,
) {
  const { project_id: _projectId, ...updatePayload } = payload
  const { data } = await api.put<PartnerIntegration>(`/partners/${partnerId}`, updatePayload, {
    params: { project_id: projectId },
  })
  return data
}

export async function deletePartnerIntegration(partnerId: string, projectId: string) {
  await api.delete(`/partners/${partnerId}`, { params: { project_id: projectId } })
}

export async function testPartnerConnection(partnerId: string, projectId: string) {
  const { data } = await api.post<PartnerConnectionTestResult>(
    `/partners/${partnerId}/test-connection`,
    null,
    { params: { project_id: projectId } },
  )
  return data
}

export async function fetchLeadSubmissionPreview(
  leadId: string,
  partnerId: string,
  projectId: string,
) {
  const { data } = await api.get<LeadSubmissionPreview>(
    `/leads/${leadId}/submission-preview`,
    { params: { partner_id: partnerId, project_id: projectId } },
  )
  return data
}

export async function submitLeadToPartner(
  leadId: string,
  partnerIntegrationId: string,
  projectId: string,
) {
  const { data } = await api.post<SubmitLeadResponse>(
    '/partners/submit',
    { lead_id: leadId, partner_integration_id: partnerIntegrationId },
    { params: { project_id: projectId } },
  )
  return data
}

export async function fetchLeadSubmissions(leadId: string, projectId: string) {
  const { data } = await api.get<LeadSubmission[]>(`/partners/submissions/${leadId}`, {
    params: { project_id: projectId },
  })
  return data
}

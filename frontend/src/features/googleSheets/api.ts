import api from '../../api/client'
import type {
  GoogleSheetsConfig,
  GoogleSheetsConfigUpdate,
  GoogleSheetsTestConnectionResult,
  LeadStatusOption,
} from './types'

export async function fetchGoogleSheetsConfig(
  projectId: string,
): Promise<GoogleSheetsConfig> {
  const { data } = await api.get<GoogleSheetsConfig>(
    `/projects/${projectId}/google-sheets`,
  )
  return data
}

export async function updateGoogleSheetsConfig(
  projectId: string,
  payload: GoogleSheetsConfigUpdate,
): Promise<GoogleSheetsConfig> {
  const { data } = await api.patch<GoogleSheetsConfig>(
    `/projects/${projectId}/google-sheets`,
    payload,
  )
  return data
}

export async function testGoogleSheetsConnection(
  projectId: string,
): Promise<GoogleSheetsTestConnectionResult> {
  const { data } = await api.post<GoogleSheetsTestConnectionResult>(
    `/projects/${projectId}/google-sheets/test-connection`,
  )
  return data
}

export async function fetchLeadStatusOptions(): Promise<LeadStatusOption[]> {
  const { data } = await api.get<LeadStatusOption[]>('/leads/statuses')
  return data
}

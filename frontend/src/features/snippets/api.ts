import api from '../../api/client'
import type {
  ProjectSnippet,
  SnippetMediaType,
  SnippetUpdatePayload,
} from './types'

export async function fetchProjectSnippets(projectId: string, signal?: AbortSignal) {
  const { data } = await api.get<ProjectSnippet[]>(`/projects/${projectId}/snippets`, {
    signal,
  })
  return data
}
export async function createTextSnippet(
  projectId: string,
  payload: { name: string; content: string },
) {
  const { data } = await api.post<ProjectSnippet>(`/projects/${projectId}/snippets`, {
    ...payload,
    type: 'text',
    channel: 'telegram',
  })
  return data
}

function mediaFormData(payload: {
  name: string
  type: SnippetMediaType
  content: string | null
  file: File
}) {
  const formData = new FormData()
  formData.append('name', payload.name)
  formData.append('type', payload.type)
  if (payload.content) formData.append('content', payload.content)
  formData.append('file', payload.file, payload.file.name)
  return formData
}

export async function createMediaSnippet(
  projectId: string,
  payload: {
    name: string
    type: SnippetMediaType
    content: string | null
    file: File
  },
) {
  const { data } = await api.post<ProjectSnippet>(
    `/projects/${projectId}/snippets/media`,
    mediaFormData(payload),
  )
  return data
}

export async function updateSnippet(
  projectId: string,
  snippetId: string,
  payload: SnippetUpdatePayload,
) {
  const { data } = await api.patch<ProjectSnippet>(
    `/projects/${projectId}/snippets/${snippetId}`,
    payload,
  )
  return data
}

export async function replaceMediaSnippet(
  projectId: string,
  snippetId: string,
  payload: {
    name: string
    type: SnippetMediaType
    content: string | null
    file: File
  },
) {
  const { data } = await api.put<ProjectSnippet>(
    `/projects/${projectId}/snippets/${snippetId}/media`,
    mediaFormData(payload),
  )
  return data
}

export async function deleteSnippet(projectId: string, snippetId: string) {
  await api.delete(`/projects/${projectId}/snippets/${snippetId}`)
}

export async function fetchSnippetMedia(
  projectId: string,
  snippetId: string,
  signal?: AbortSignal,
) {
  const { data } = await api.get<Blob>(
    `/projects/${projectId}/snippets/${snippetId}/media`,
    { responseType: 'blob', signal },
  )
  return data
}

import axios from 'axios'

type ValidationIssueLike = {
  message?: unknown
  detail?: unknown
  code?: unknown
  errors?: unknown
  step_id?: unknown
  step_key?: unknown
  step_title?: unknown
  step_type?: unknown
  block_type?: unknown
  edge_id?: unknown
  funnel_id?: unknown
  version_id?: unknown
  version_status?: unknown
  error_type?: unknown
}

function diagnosticPart(label: string, value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? `${label}: ${value.trim()}` : null
}

function issueToMessage(item: unknown): string | null {
  if (typeof item === 'string') {
    return item.trim() || null
  }
  if (!item || typeof item !== 'object') {
    return null
  }
  const issue = item as ValidationIssueLike
  const base =
    typeof issue.message === 'string' && issue.message.trim()
      ? issue.message.trim()
      : typeof issue.detail === 'string' && issue.detail.trim()
        ? issue.detail.trim()
        : typeof issue.code === 'string' && issue.code.trim()
          ? issue.code.trim()
          : null
  const diagnostics = [
    diagnosticPart('step_id', issue.step_id),
    diagnosticPart('step_key', issue.step_key),
    diagnosticPart('step_title', issue.step_title),
    diagnosticPart('step_type', issue.step_type),
    diagnosticPart('block_type', issue.block_type),
    diagnosticPart('edge_id', issue.edge_id),
    diagnosticPart('version_id', issue.version_id),
    diagnosticPart('status', issue.version_status),
    diagnosticPart('error_type', issue.error_type),
  ].filter((part): part is string => Boolean(part))

  if (!base && diagnostics.length === 0) {
    return null
  }
  return diagnostics.length > 0 ? `${base ?? 'Ошибка'} (${diagnostics.join(', ')})` : base
}

function detailToMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim()
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        return issueToMessage(item)
      })
      .filter((message): message is string => Boolean(message?.trim()))

    return messages.length > 0 ? messages.join('\n') : null
  }

  if (detail && typeof detail === 'object') {
    const issue = detail as ValidationIssueLike
    const messages: string[] = []
    if (typeof issue.message === 'string' && issue.message.trim()) {
      messages.push(issue.message.trim())
    }
    if (typeof issue.detail === 'string' && issue.detail.trim()) {
      messages.push(issue.detail.trim())
    }
    if (Array.isArray(issue.errors)) {
      for (const item of issue.errors) {
        const message = issueToMessage(item)
        if (message) {
          messages.push(message)
        }
      }
    }
    const diagnostic = issueToMessage(issue)
    if (diagnostic && !messages.includes(diagnostic)) {
      messages.push(diagnostic)
    }
    return messages.length > 0 ? messages.join('\n') : null
  }

  return null
}

export function getFunnelApiErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const message = detailToMessage(error.response?.data?.detail)
    if (message) {
      return message
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message
  }

  return fallback
}

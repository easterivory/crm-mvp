import axios from 'axios'

type ValidationIssueLike = {
  message?: unknown
  detail?: unknown
  code?: unknown
}

function detailToMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim()
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') {
          return item
        }
        if (item && typeof item === 'object') {
          const issue = item as ValidationIssueLike
          if (typeof issue.message === 'string') {
            return issue.message
          }
          if (typeof issue.detail === 'string') {
            return issue.detail
          }
          if (typeof issue.code === 'string') {
            return issue.code
          }
        }
        return null
      })
      .filter((message): message is string => Boolean(message?.trim()))

    return messages.length > 0 ? messages.join('\n') : null
  }

  if (detail && typeof detail === 'object') {
    const issue = detail as ValidationIssueLike
    if (typeof issue.message === 'string' && issue.message.trim()) {
      return issue.message.trim()
    }
    if (typeof issue.detail === 'string' && issue.detail.trim()) {
      return issue.detail.trim()
    }
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

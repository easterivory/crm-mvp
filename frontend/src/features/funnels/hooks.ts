import { useEffect, useState } from 'react'

import { fetchBlockRegistry } from './api'
import type { FunnelBlockRegistry } from './types'

export function useFunnelBlockRegistry() {
  const [registry, setRegistry] = useState<FunnelBlockRegistry | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let isMounted = true
    setIsLoading(true)
    fetchBlockRegistry()
      .then((data) => {
        if (isMounted) {
          setRegistry(data)
        }
      })
      .catch(() => undefined)
      .finally(() => {
        if (isMounted) {
          setIsLoading(false)
        }
      })

    return () => {
      isMounted = false
    }
  }, [])

  return { registry, isLoading }
}

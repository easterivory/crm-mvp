import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { isManagerRole } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type ManagerRestrictedRouteProps = {
  children: ReactNode
}

export default function ManagerRestrictedRoute({ children }: ManagerRestrictedRouteProps) {
  const roleName = useAuthStore((state) => state.user?.role_name)

  if (isManagerRole(roleName)) {
    return <Navigate to="/chats" replace />
  }

  return <>{children}</>
}

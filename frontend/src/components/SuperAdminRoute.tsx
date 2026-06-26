import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { isSuperAdminRole } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type SuperAdminRouteProps = {
  children: ReactNode
}

export default function SuperAdminRoute({ children }: SuperAdminRouteProps) {
  const user = useAuthStore((state) => state.user)

  if (!user) {
    return null
  }

  if (!isSuperAdminRole(user.role_name)) {
    return <Navigate to="/chats" replace />
  }

  return <>{children}</>
}

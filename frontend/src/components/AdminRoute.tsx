import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { isAdminOrSuperAdminRole } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type AdminRouteProps = {
  children: ReactNode
}

export default function AdminRoute({ children }: AdminRouteProps) {
  const user = useAuthStore((state) => state.user)

  if (!user) {
    return null
  }

  if (!isAdminOrSuperAdminRole(user.role_name)) {
    return <Navigate to="/chats" replace />
  }

  return <>{children}</>
}

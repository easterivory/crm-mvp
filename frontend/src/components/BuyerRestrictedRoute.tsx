import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { isBuyerRole } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

type BuyerRestrictedRouteProps = {
  children: ReactNode
}

export default function BuyerRestrictedRoute({ children }: BuyerRestrictedRouteProps) {
  const roleName = useAuthStore((state) => state.user?.role_name)
  return isBuyerRole(roleName) ? <Navigate to="/chats" replace /> : <>{children}</>
}

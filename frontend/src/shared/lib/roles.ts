const USER_ROLES = ['super_admin', 'admin', 'manager', 'buyer', 'operator'] as const

type UserRole = (typeof USER_ROLES)[number]

export function normalizeRoleName(roleName?: string | null): UserRole | null {
  const normalized = roleName?.trim()

  if (USER_ROLES.includes(normalized as UserRole)) {
    return normalized as UserRole
  }

  return null
}

export function isKnownRole(roleName?: string | null): boolean {
  return normalizeRoleName(roleName) !== null
}

export function isSuperAdminRole(roleName?: string | null): boolean {
  return normalizeRoleName(roleName) === 'super_admin'
}

export function isAdminRole(roleName?: string | null): boolean {
  return normalizeRoleName(roleName) === 'admin'
}

export function isAdminOrSuperAdminRole(roleName?: string | null): boolean {
  const role = normalizeRoleName(roleName)
  return role === 'admin' || role === 'super_admin'
}

export function isManagerRole(roleName?: string | null): boolean {
  return normalizeRoleName(roleName) === 'manager'
}

export function isBuyerRole(roleName?: string | null): boolean {
  return normalizeRoleName(roleName) === 'buyer'
}

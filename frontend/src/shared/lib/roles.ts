const USER_ROLES = ['super_admin', 'admin', 'manager', 'operator'] as const

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

export function isManagerRole(roleName?: string | null): boolean {
  return normalizeRoleName(roleName) === 'manager'
}

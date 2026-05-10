export interface AuthUser {
  id: number
  username: string
  role: 'admin' | 'owner'
  telegramId?: number
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem('auth_user')
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

export function storeAuth(token: string, user: AuthUser) {
  localStorage.setItem('auth_token', token)
  localStorage.setItem('auth_user', JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem('auth_token')
}

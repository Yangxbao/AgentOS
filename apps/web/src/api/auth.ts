import { api } from './client'

export interface AuthStatus {
  enabled: boolean
}

export interface AuthUser {
  id: string
  username: string
  display_name: string
  owner_id: string
}

export interface LoginResult {
  token: string
  user: AuthUser
}

const TOKEN_KEY = 'agentos_token'
const USER_KEY = 'agentos_user'

export const authStore = {
  token: () => localStorage.getItem(TOKEN_KEY) ?? '',
  user: (): AuthUser | null => {
    const raw = localStorage.getItem(USER_KEY)
    if (!raw) return null
    try {
      return JSON.parse(raw) as AuthUser
    } catch {
      return null
    }
  },
  save: (token: string, user: AuthUser) => {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
    window.dispatchEvent(new Event('agentos-auth-changed'))
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    window.dispatchEvent(new Event('agentos-auth-changed'))
  },
}

export const authApi = {
  status: () => api.get<AuthStatus>('/api/v1/auth/status'),
  login: (username: string, password: string) =>
    api.post<LoginResult>('/api/v1/auth/login', { username, password }),
  register: (username: string, password: string, display_name: string) =>
    api.post<{ ok: boolean }>('/api/v1/auth/register', { username, password, display_name }),
  me: () => api.get<{ actor: string; owner_id: string }>('/api/v1/auth/me'),
  logout: () => api.post<{ ok: boolean }>('/api/v1/auth/logout', {}),
  changePassword: (oldPassword: string, newPassword: string) =>
    api.post<{ ok: boolean; message: string }>('/api/v1/auth/change-password', {
      old_password: oldPassword,
      new_password: newPassword,
    }),
}

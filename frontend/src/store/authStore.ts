import { create } from 'zustand'

import api from '../api/client'

type User = {
  id: string
  email: string
  name: string
  project_id: string | null
  project_ids?: string[]
  role_id: string
  role_name?: string | null
  created_at: string
  is_deleted: boolean
}

type LoginPayload = {
  email: string
  password: string
}

export type TelegramAuthPayload = Record<string, unknown>

type AuthState = {
  token: string | null
  user: User | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  loginWithTelegram: (authData: TelegramAuthPayload) => Promise<void>
  logout: () => void
  fetchMe: () => Promise<void>
}

const TOKEN_KEY = 'token'
const USER_KEY = 'user'

const getInitialUser = (): User | null => {
  const rawUser = localStorage.getItem(USER_KEY)

  if (!rawUser) {
    return null
  }

  try {
    return JSON.parse(rawUser) as User
  } catch {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

const initialToken = localStorage.getItem(TOKEN_KEY)

export const useAuthStore = create<AuthState>((set) => ({
  token: initialToken,
  user: getInitialUser(),
  isAuthenticated: Boolean(initialToken),

  login: async (email: string, password: string) => {
    const payload: LoginPayload = { email, password }
    const { data } = await api.post<{ access_token: string }>('/users/login', payload)

    localStorage.setItem(TOKEN_KEY, data.access_token)

    set({ token: data.access_token, isAuthenticated: true })

    await useAuthStore.getState().fetchMe()
  },

  loginWithTelegram: async (authData: TelegramAuthPayload) => {
    const { data } = await api.post<{ access_token: string }>('/auth/telegram-login', authData)

    localStorage.setItem(TOKEN_KEY, data.access_token)

    set({ token: data.access_token, isAuthenticated: true })

    await useAuthStore.getState().fetchMe()
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)

    set({ token: null, user: null, isAuthenticated: false })
  },

  fetchMe: async () => {
    try {
      const { data } = await api.get<User>('/users/me')

      localStorage.setItem(USER_KEY, JSON.stringify(data))
      set({ user: data, isAuthenticated: true })
    } catch {
      useAuthStore.getState().logout()
      throw new Error('Unable to fetch current user')
    }
  },
}))

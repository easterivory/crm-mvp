import { create } from 'zustand'

export type NotificationTone = 'success' | 'error' | 'info' | 'warning'

export type AppNotification = {
  id: string
  title?: string
  message: string
  tone: NotificationTone
  durationMs: number
}

type NotificationInput = {
  title?: string
  message: string
  tone?: NotificationTone
  durationMs?: number
}

type NotificationState = {
  notifications: AppNotification[]
  notify: (notification: NotificationInput) => string
  dismiss: (id: string) => void
  clear: () => void
}

const MAX_NOTIFICATIONS = 4

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  notify: ({ title, message, tone = 'info', durationMs = 4000 }) => {
    const id = crypto.randomUUID()
    set((state) => ({
      notifications: [
        { id, title, message, tone, durationMs },
        ...state.notifications,
      ].slice(0, MAX_NOTIFICATIONS),
    }))
    return id
  },
  dismiss: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((item) => item.id !== id),
    })),
  clear: () => set({ notifications: [] }),
}))

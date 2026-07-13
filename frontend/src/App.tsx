import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import MainLayout from './components/MainLayout'
import BuyerRestrictedRoute from './components/BuyerRestrictedRoute'
import ManagerRestrictedRoute from './components/ManagerRestrictedRoute'
import ProtectedRoute from './components/ProtectedRoute'
import SuperAdminRoute from './components/SuperAdminRoute'
import BotsPage from './pages/BotsPage'
import BroadcastsPage from './pages/BroadcastsPage'
import DashboardPage from './pages/DashboardPage'
import FunnelsPage from './pages/FunnelsPage'
import LeadsPage from './pages/LeadsPage'
import LoginPage from './pages/LoginPage'
import ChatsPage from './pages/ChatsPage'
import DocsPage from './pages/DocsPage'
import SettingsPage from './pages/SettingsPage'
import TrackingPage from './pages/TrackingPage'
import NotFoundPage from './pages/NotFoundPage'
import { isKnownRole, ProjectBotSelectionProvider } from './shared/lib'
import { NotificationViewport } from './shared/ui'
import { useAuthStore } from './store/authStore'

type UiHostContext = {
  crm_ui_allowed: boolean
}

type HostAccessState = 'checking' | 'allowed' | 'denied'

function PublicHostNotFound() {
  useEffect(() => {
    const previousTitle = document.title
    document.title = '404'
    return () => {
      document.title = previousTitle
    }
  }, [])

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-neutral-950 p-6 text-center">
      <h1 className="text-4xl font-semibold text-zinc-100">404</h1>
      <p className="text-sm text-zinc-500">Страница не найдена</p>
    </div>
  )
}

function CrmApplication() {
  const token = useAuthStore((state) => state.token)
  const user = useAuthStore((state) => state.user)
  const fetchMe = useAuthStore((state) => state.fetchMe)

  useEffect(() => {
    if (token && (!user || !isKnownRole(user.role_name))) {
      fetchMe().catch(() => undefined)
    }
  }, [fetchMe, token, user])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <ProtectedRoute>
              <ProjectBotSelectionProvider>
                <MainLayout />
              </ProjectBotSelectionProvider>
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Navigate to="/chats" replace />} />
          <Route path="/dashboard" element={<BuyerRestrictedRoute><DashboardPage /></BuyerRestrictedRoute>} />
          <Route path="/analytics" element={<BuyerRestrictedRoute><DashboardPage /></BuyerRestrictedRoute>} />
          <Route path="/chats" element={<ChatsPage />} />
          <Route path="/funnels" element={<FunnelsPage />} />
          <Route path="/funnels/:funnelId/builder" element={<FunnelsPage />} />
          <Route path="/broadcasts" element={<BuyerRestrictedRoute><BroadcastsPage /></BuyerRestrictedRoute>} />
          <Route path="/bots" element={<BuyerRestrictedRoute><ManagerRestrictedRoute><BotsPage /></ManagerRestrictedRoute></BuyerRestrictedRoute>} />
          <Route path="/leads" element={<BuyerRestrictedRoute><LeadsPage /></BuyerRestrictedRoute>} />
          <Route path="/tracking" element={<ManagerRestrictedRoute><TrackingPage /></ManagerRestrictedRoute>} />
          <Route path="/docs" element={<SuperAdminRoute><DocsPage /></SuperAdminRoute>} />
          <Route path="/settings" element={<BuyerRestrictedRoute><ManagerRestrictedRoute><SettingsPage /></ManagerRestrictedRoute></BuyerRestrictedRoute>} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      <NotificationViewport />
    </BrowserRouter>
  )
}

export default function App() {
  const [hostAccess, setHostAccess] = useState<HostAccessState>('checking')

  useEffect(() => {
    const controller = new AbortController()

    const checkHostAccess = async () => {
      try {
        const response = await fetch('/api/ui-host-context', {
          cache: 'no-store',
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        })
        if (!response.ok) {
          throw new Error(`Host context returned HTTP ${response.status}`)
        }
        const context = await response.json() as Partial<UiHostContext>
        setHostAccess(context.crm_ui_allowed === true ? 'allowed' : 'denied')
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }
        setHostAccess('denied')
      }
    }

    void checkHostAccess()
    return () => controller.abort()
  }, [])

  if (hostAccess === 'checking') {
    return <div className="min-h-screen bg-neutral-950" aria-hidden="true" />
  }
  if (hostAccess === 'denied') {
    return <PublicHostNotFound />
  }
  return <CrmApplication />
}

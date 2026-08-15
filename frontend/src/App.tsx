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
import FacebookCampaignsPage from './pages/FacebookCampaignsPage'
import AISettingsPage from './pages/AISettingsPage'
import NotFoundPage from './pages/NotFoundPage'
import SnippetsPage from './pages/SnippetsPage'
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
    <div className="grid min-h-screen place-items-center bg-[#090b11] px-5 text-center text-zinc-100">
      <main className="w-full max-w-[460px]">
        <div className="mx-auto mb-6 grid h-[58px] w-[58px] place-items-center rounded-lg border border-[#303541] bg-[#11141c] text-sm font-bold text-zinc-400">
          404
        </div>
        <h1 className="text-[28px] font-semibold leading-tight sm:text-[34px]">Page unavailable</h1>
        <p className="mx-auto mt-3.5 max-w-[390px] text-[15px] leading-6 text-[#8b909c]">
          This address is unavailable. Check the link and try again.
        </p>
      </main>
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
          <Route path="/snippets" element={<BuyerRestrictedRoute><SnippetsPage /></BuyerRestrictedRoute>} />
          <Route path="/funnels" element={<FunnelsPage />} />
          <Route path="/funnels/:funnelId/builder" element={<FunnelsPage />} />
          <Route path="/broadcasts" element={<BuyerRestrictedRoute><BroadcastsPage /></BuyerRestrictedRoute>} />
          <Route path="/bots" element={<BuyerRestrictedRoute><ManagerRestrictedRoute><BotsPage /></ManagerRestrictedRoute></BuyerRestrictedRoute>} />
          <Route path="/leads" element={<BuyerRestrictedRoute><LeadsPage /></BuyerRestrictedRoute>} />
          <Route path="/tracking" element={<ManagerRestrictedRoute><TrackingPage /></ManagerRestrictedRoute>} />
          <Route path="/tracking/facebook" element={<ManagerRestrictedRoute><FacebookCampaignsPage /></ManagerRestrictedRoute>} />
          <Route path="/docs" element={<SuperAdminRoute><DocsPage /></SuperAdminRoute>} />
          <Route path="/settings/ai" element={<BuyerRestrictedRoute><ManagerRestrictedRoute><AISettingsPage /></ManagerRestrictedRoute></BuyerRestrictedRoute>} />
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

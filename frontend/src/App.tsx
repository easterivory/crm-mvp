import { useEffect } from 'react'
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

export default function App() {
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

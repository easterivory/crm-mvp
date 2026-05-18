import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import MainLayout from './components/MainLayout'
import ProtectedRoute from './components/ProtectedRoute'
import BotsPage from './pages/BotsPage'
import DashboardPage from './pages/DashboardPage'
import LoginPage from './pages/LoginPage'
import ChatsPage from './pages/ChatsPage'
import SettingsPage from './pages/SettingsPage'
import NotFoundPage from './pages/NotFoundPage'
import { isKnownRole, ProjectBotSelectionProvider } from './shared/lib'
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
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/chats" element={<ChatsPage />} />
          <Route path="/bots" element={<BotsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}

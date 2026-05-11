import { Bot, LogOut, MessageSquareText, Settings } from 'lucide-react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/authStore'

export default function MainLayout() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const navigate = useNavigate()
  const location = useLocation()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-neutral-950 text-zinc-100 md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-zinc-800 bg-zinc-950 p-4 md:w-64 md:border-b-0 md:border-r md:p-5">
        <div className="mb-4 text-2xl font-bold text-zinc-100 md:mb-7">CRM</div>

        <nav className="flex min-h-0 gap-2 overflow-x-auto md:flex-1 md:flex-col md:overflow-x-visible md:overflow-y-auto">
          <button
            type="button"
            onClick={() => navigate('/chats')}
            className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition md:w-full ${
              location.pathname.startsWith('/chats')
                ? 'bg-zinc-900 text-emerald-300'
                : 'text-zinc-300 hover:bg-zinc-900'
            }`}
          >
            <MessageSquareText size={18} />
            Chats
          </button>
          <button
            type="button"
            onClick={() => navigate('/settings')}
            className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition md:w-full ${
              location.pathname.startsWith('/settings')
                ? 'bg-zinc-900 text-emerald-300'
                : 'text-zinc-300 hover:bg-zinc-900'
            }`}
          >
            <Settings size={18} />
            Settings
          </button>
          <button
            type="button"
            onClick={() => navigate('/bots')}
            className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition md:w-full ${
              location.pathname.startsWith('/bots')
                ? 'bg-zinc-900 text-emerald-300'
                : 'text-zinc-300 hover:bg-zinc-900'
            }`}
          >
            <Bot size={18} />
            Bots
          </button>
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-zinc-800 bg-zinc-950 px-4 py-3 md:px-6 md:py-4">
          <p className="min-w-0 truncate text-sm text-zinc-400">
            {user?.name ?? user?.email ?? 'User'}
          </p>

          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-950 transition hover:bg-emerald-300"
          >
            <LogOut size={16} />
            Logout
          </button>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden p-3 md:p-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

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
    <div className="flex min-h-screen bg-neutral-950 text-zinc-100">
      <aside className="w-64 border-r border-zinc-800 bg-zinc-950 p-6">
        <div className="mb-8 text-2xl font-bold text-zinc-100">CRM</div>

        <nav>
          <button
            type="button"
            onClick={() => navigate('/chats')}
            className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
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
            className={`mt-2 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
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
            className={`mt-2 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
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

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-zinc-800 bg-zinc-950 px-6 py-4">
          <p className="text-sm text-zinc-400">{user?.name ?? user?.email ?? 'User'}</p>

          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-950 transition hover:bg-emerald-300"
          >
            <LogOut size={16} />
            Logout
          </button>
        </header>

        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

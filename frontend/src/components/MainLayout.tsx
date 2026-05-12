import {
  Bot,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  Settings,
  Sparkles,
} from 'lucide-react'
import clsx from 'clsx'
import { twMerge } from 'tailwind-merge'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuthStore } from '../store/authStore'

const navItems = [
  { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
  { label: 'Chats', path: '/chats', icon: MessageSquareText },
  { label: 'Bots', path: '/bots', icon: Bot },
  { label: 'Settings', path: '/settings', icon: Settings },
]

function cn(...inputs: Array<string | false | null | undefined>) {
  return twMerge(clsx(inputs))
}

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
    <div className="flex h-screen flex-col overflow-hidden bg-background bg-neon-radial text-gray-200 md:flex-row">
      <aside className="relative flex shrink-0 flex-col border-b border-white/5 bg-[#090D16]/90 p-4 backdrop-blur-xl md:w-72 md:border-b-0 md:border-r md:p-5">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-primary-500/10 to-transparent" />
        <div className="relative mb-5 flex items-center gap-3 md:mb-8">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-primary-400/30 bg-primary-500/15 text-primary-100 shadow-glow-primary">
            <Sparkles size={20} />
          </div>
          <div>
            <div className="text-xl font-bold tracking-wide text-white">SFERA</div>
            <div className="text-xs uppercase tracking-[0.28em] text-accent-300/70">
              CRM Core
            </div>
          </div>
        </div>

        <nav className="relative flex min-h-0 gap-2 overflow-x-auto md:flex-1 md:flex-col md:overflow-x-visible md:overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname.startsWith(item.path)

            return (
              <button
                key={item.path}
                type="button"
                onClick={() => navigate(item.path)}
                className={cn(
                  'group relative flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition duration-200 md:w-full',
                  isActive
                    ? 'border-l-2 border-accent-300 bg-gradient-to-r from-primary-500/30 via-primary-500/12 to-transparent text-white shadow-glow-primary'
                    : 'border-l-2 border-transparent text-gray-500 hover:bg-white/[0.04] hover:text-gray-100',
                )}
              >
                <Icon
                  size={18}
                  className={cn(
                    'transition',
                    isActive
                      ? 'text-accent-300 drop-shadow-[0_0_10px_rgba(34,211,238,0.65)]'
                      : 'text-gray-500 group-hover:text-accent-300',
                  )}
                />
                <span>{item.label}</span>
              </button>
            )
          })}
        </nav>

        <div className="relative mt-4 hidden rounded-xl border border-white/5 bg-white/[0.03] p-4 shadow-card md:block">
          <p className="text-xs uppercase tracking-[0.2em] text-gray-500">Signed in</p>
          <p className="mt-1 truncate text-sm font-semibold text-white">
            {user?.name ?? user?.email ?? 'User'}
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-white/5 bg-background/65 px-4 py-3 backdrop-blur-xl md:px-6 md:py-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-white">
              {user?.name ?? user?.email ?? 'User'}
            </p>
            <p className="text-xs text-gray-500">Neon operations console</p>
          </div>

          <button
            type="button"
            onClick={handleLogout}
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm font-medium text-gray-200 transition hover:border-accent-300/50 hover:text-white hover:shadow-glow-accent"
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

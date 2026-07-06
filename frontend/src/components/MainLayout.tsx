import {
  BarChart3,
  BookOpen,
  Bot,
  LogOut,
  Megaphone,
  Menu,
  MessageSquareText,
  MousePointerClick,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  SlidersHorizontal,
  Sparkles,
  UsersRound,
  Workflow,
} from 'lucide-react'
import clsx from 'clsx'
import { twMerge } from 'tailwind-merge'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'

import { BotSelector } from '../features/bots'
import { ProjectSelector } from '../features/projects'
import { isBuyerRole, isManagerRole, isSuperAdminRole, t } from '../shared/lib'
import { useAuthStore } from '../store/authStore'
import DashboardHeaderMetrics from './DashboardHeaderMetrics'

const SIDEBAR_COLLAPSED_KEY = 'crm:sidebarCollapsed'

const navItems = [
  { label: t('chats'), path: '/chats', icon: MessageSquareText },
  { label: t('funnels'), path: '/funnels', icon: Workflow },
  { label: t('broadcasts'), path: '/broadcasts', icon: Megaphone },
  { label: t('bots'), path: '/bots', icon: Bot },
  { label: t('leads'), path: '/leads', icon: UsersRound },
  { label: t('analytics'), path: '/analytics', icon: BarChart3 },
  { label: t('tracking'), path: '/tracking', icon: MousePointerClick },
  { label: t('docs'), path: '/docs', icon: BookOpen },
  { label: t('settings'), path: '/settings', icon: Settings },
]

function cn(...inputs: Array<string | false | null | undefined>) {
  return twMerge(clsx(inputs))
}

function readCollapsed() {
  return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === 'true'
}

function initials(name?: string | null) {
  const label = name?.trim() || 'U'
  return label
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

export default function MainLayout() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const navigate = useNavigate()
  const location = useLocation()
  const [isCollapsed, setIsCollapsed] = useState(readCollapsed)
  const [isMobileOpen, setIsMobileOpen] = useState(false)
  const [isMobileScopeOpen, setIsMobileScopeOpen] = useState(false)

  useEffect(() => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(isCollapsed))
  }, [isCollapsed])

  useEffect(() => {
    setIsMobileOpen(false)
    setIsMobileScopeOpen(false)
  }, [location.pathname])

  useEffect(() => {
    const setAppHeight = () => {
      const activeElement = document.activeElement
      if (
        activeElement instanceof HTMLElement &&
        activeElement.matches('input, textarea, select, [contenteditable="true"]')
      ) {
        return
      }
      const height = window.innerHeight
      document.documentElement.style.setProperty('--app-height', `${height}px`)
    }

    setAppHeight()
    window.addEventListener('resize', setAppHeight)
    document.addEventListener('focusout', setAppHeight)

    return () => {
      window.removeEventListener('resize', setAppHeight)
      document.removeEventListener('focusout', setAppHeight)
    }
  }, [])

  const displayName = user?.name ?? user?.email ?? 'Пользователь'
  const isChatPage = location.pathname.startsWith('/chats')
  const visibleNavItems = useMemo(
    () =>
      navItems.filter((item) => {
        if (isBuyerRole(user?.role_name)) {
          return ['/chats', '/funnels', '/tracking'].includes(item.path)
        }
        if (item.path === '/docs') {
          return isSuperAdminRole(user?.role_name)
        }

        return !isManagerRole(user?.role_name) || !['/bots', '/tracking', '/settings'].includes(item.path)
      }),
    [user?.role_name],
  )
  const roleLabel = useMemo(() => {
    const role = user?.role_name ?? 'user'
    if (role === 'buyer') {
      return 'Баер'
    }
    return role.replace('_', ' ')
  }, [user?.role_name])

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const sidebar = (
    <aside
      className={cn(
        'relative flex h-full shrink-0 flex-col border-white/5 bg-[#0e1325] p-4 text-gray-200 shadow-card backdrop-blur-xl transition-all duration-200 md:bg-[#090D16]/95',
        isCollapsed ? 'md:w-20 md:px-3 md:py-4' : 'md:w-72 md:p-5',
        'w-64 border-r',
      )}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-primary-500/10 to-transparent" />
      <div className={cn('relative mb-6 flex items-center gap-3', isCollapsed && 'md:justify-center')}>
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-primary-400/30 bg-primary-500/15 text-primary-100 shadow-glow-primary">
          <Sparkles size={20} />
        </div>
        <div className={cn('min-w-0', isCollapsed && 'md:hidden')}>
          <div className="truncate text-xl font-bold tracking-wide text-white">SFERA</div>
          <div className="text-xs uppercase tracking-[0.28em] text-accent-300/70">
            CRM Core
          </div>
        </div>
      </div>

      <nav className="relative flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
        {visibleNavItems.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname.startsWith(item.path)

          return (
            <button
              key={item.path}
              type="button"
              title={isCollapsed ? item.label : undefined}
              onClick={() => navigate(item.path)}
              className={cn(
                'group relative flex min-h-11 items-center gap-3 rounded-xl border-l-2 px-3 text-left text-sm font-medium transition duration-200',
                isCollapsed && 'md:justify-center md:px-0',
                isActive
                  ? 'border-accent-300 bg-gradient-to-r from-primary-500/30 via-primary-500/12 to-transparent text-white shadow-glow-primary'
                  : 'border-transparent text-gray-500 hover:bg-white/[0.04] hover:text-gray-100',
              )}
            >
              <Icon
                size={18}
                className={cn(
                  'shrink-0 transition',
                  isActive
                    ? 'text-accent-300 drop-shadow-[0_0_10px_rgba(34,211,238,0.65)]'
                    : 'text-gray-500 group-hover:text-accent-300',
                )}
              />
              <span className={cn('truncate', isCollapsed && 'md:hidden')}>{item.label}</span>
            </button>
          )
        })}
      </nav>

      <div className="relative mt-4 space-y-3">
        <button
          type="button"
          title={isCollapsed ? 'Развернуть меню' : 'Свернуть меню'}
          onClick={() => setIsCollapsed((value) => !value)}
          className="hidden h-10 w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] text-sm font-medium text-gray-300 transition hover:border-accent-300/50 hover:text-white md:inline-flex"
        >
          {isCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          <span className={cn(isCollapsed && 'md:hidden')}>
            {isCollapsed ? 'Развернуть' : 'Свернуть'}
          </span>
        </button>

        <div
          className={cn(
            'max-w-full rounded-xl border border-white/5 bg-white/[0.03] p-4 shadow-card transition-all duration-200',
            isCollapsed &&
              'md:flex md:h-12 md:w-12 md:items-center md:justify-center md:self-center md:overflow-hidden md:p-0',
          )}
          title={isCollapsed ? `${displayName} · ${roleLabel}` : undefined}
        >
          {isCollapsed ? (
            <div className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-400/10 text-sm font-semibold text-accent-100 md:flex">
              {initials(displayName)}
            </div>
          ) : null}
          <div className={cn(isCollapsed && 'md:hidden')}>
            <p className="text-xs uppercase tracking-[0.2em] text-gray-500">В системе</p>
            <p className="mt-1 truncate text-sm font-semibold text-white">{displayName}</p>
            <p className="truncate text-xs text-gray-500">{roleLabel}</p>
          </div>
        </div>
      </div>
    </aside>
  )

  return (
    <div
      className={cn(
        'flex min-w-0 flex-col bg-background bg-neon-radial text-gray-200 md:h-screen md:overflow-hidden md:flex-row',
        isChatPage
          ? 'h-[var(--app-height,100dvh)] overflow-hidden'
          : 'min-h-[var(--app-height,100dvh)] overflow-x-hidden',
      )}
    >
      <div className="hidden md:block">{sidebar}</div>

      <button
        type="button"
        aria-label="Закрыть меню"
        className={cn(
          'fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-300 md:hidden',
          isMobileOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={() => setIsMobileOpen(false)}
      />
      <div
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 transform transition-transform duration-300 md:hidden',
          isMobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        {sidebar}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        {!isBuyerRole(user?.role_name) ? (
          <div className="hidden md:block">
            <DashboardHeaderMetrics />
          </div>
        ) : null}
        {isMobileScopeOpen ? (
          <button
            type="button"
            aria-label="Закрыть выбор проекта и ботов"
            className="fixed inset-0 z-30 bg-black/20 md:hidden"
            onClick={() => setIsMobileScopeOpen(false)}
          />
        ) : null}

        <header className="relative z-40 flex shrink-0 flex-col gap-2 border-b border-white/5 bg-background/90 px-2.5 py-2 backdrop-blur-xl md:px-3 md:py-3 lg:flex-row lg:items-center lg:justify-between lg:px-6 lg:py-4">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setIsMobileOpen(true)}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 md:hidden"
              aria-label="Открыть меню"
            >
              <Menu size={18} />
            </button>
            <div className="min-w-0 flex-1 md:flex-none">
              <p className="truncate text-sm font-medium text-white">{displayName}</p>
              <p className="text-xs text-gray-500">Рабочая панель CRM</p>
            </div>
            <button
              type="button"
              onClick={() => setIsMobileScopeOpen((value) => !value)}
              className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 md:hidden"
              aria-expanded={isMobileScopeOpen}
              aria-label="Проект и боты"
            >
              <SlidersHorizontal size={17} />
            </button>
          </div>

          {isMobileScopeOpen ? (
            <div className="touch-scroll absolute left-2 right-2 top-[calc(100%+0.5rem)] z-50 grid max-h-[calc(var(--app-height,100dvh)-5rem)] min-w-0 grid-cols-1 gap-2 overflow-y-auto rounded-xl border border-white/10 bg-[#0B0F19]/98 p-2 shadow-2xl backdrop-blur-xl md:hidden">
              <ProjectSelector compact />
              <BotSelector compact />

              <button
                type="button"
                onClick={handleLogout}
                className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm font-medium text-gray-200 transition hover:border-accent-300/50 hover:text-white"
              >
                <LogOut size={16} />
                {t('logout')}
              </button>
            </div>
          ) : null}

          <div className="hidden min-w-0 grid-cols-1 gap-3 md:mt-3 md:grid sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end lg:mt-0 lg:flex lg:justify-end">
            <ProjectSelector />
            <BotSelector />

            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-sm font-medium text-gray-200 transition hover:border-accent-300/50 hover:text-white hover:shadow-glow-accent"
            >
              <LogOut size={16} />
              {t('logout')}
            </button>
          </div>
        </header>

        <main
          className={cn(
            'touch-scroll min-w-0 flex-1 overflow-y-auto overscroll-contain pb-[calc(0.5rem+env(safe-area-inset-bottom))] md:min-h-0 md:overflow-hidden md:p-5',
            isChatPage ? 'p-0' : 'p-2',
          )}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}

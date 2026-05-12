import {
  ArrowDownRight,
  ArrowUpRight,
  Clock3,
  DollarSign,
  Flame,
  Link2,
  Target,
  Users,
} from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type KpiCard = {
  title: string
  value: string
  delta: string
  positive: boolean
  icon: typeof Users
  color: string
  sparkline: Array<{ label: string; value: number }>
}

const kpiCards: KpiCard[] = [
  {
    title: 'Всего лидов',
    value: '1,248',
    delta: '+15%',
    positive: true,
    icon: Users,
    color: '#22D3EE',
    sparkline: [18, 24, 22, 29, 34, 31, 42].map((value, index) => ({
      label: String(index),
      value,
    })),
  },
  {
    title: 'Квалифицировано',
    value: '386',
    delta: '+9%',
    positive: true,
    icon: Target,
    color: '#8B5CF6',
    sparkline: [8, 13, 16, 14, 20, 23, 28].map((value, index) => ({
      label: String(index),
      value,
    })),
  },
  {
    title: 'Spend',
    value: '$12.4k',
    delta: '-4%',
    positive: false,
    icon: DollarSign,
    color: '#FB923C',
    sparkline: [35, 31, 36, 29, 26, 25, 24].map((value, index) => ({
      label: String(index),
      value,
    })),
  },
  {
    title: 'Ср. время ответа',
    value: '4м 12с',
    delta: '+21%',
    positive: true,
    icon: Clock3,
    color: '#34D399',
    sparkline: [28, 24, 22, 18, 16, 14, 11].map((value, index) => ({
      label: String(index),
      value,
    })),
  },
]

const growthData = [
  { day: 'Пн', chats: 42, leads: 18 },
  { day: 'Вт', chats: 58, leads: 23 },
  { day: 'Ср', chats: 51, leads: 29 },
  { day: 'Чт', chats: 76, leads: 37 },
  { day: 'Пт', chats: 92, leads: 46 },
  { day: 'Сб', chats: 84, leads: 41 },
  { day: 'Вс', chats: 118, leads: 59 },
]

const funnels = [
  {
    label: 'New',
    value: 342,
    percent: 72,
    glow: 'shadow-glow-accent',
    color: 'from-accent-400 to-blue-500',
  },
  {
    label: 'In Progress',
    value: 186,
    percent: 48,
    glow: 'shadow-glow-primary',
    color: 'from-primary-400 to-fuchsia-500',
  },
  {
    label: 'Qualified',
    value: 91,
    percent: 24,
    glow: 'shadow-[0_0_28px_rgba(52,211,153,0.25)]',
    color: 'from-emerald-400 to-teal-400',
  },
]

const trackingLinks = [
  { source: 'FB_Ad_1', clicks: 1240, conversion: 18 },
  { source: 'Таргет Инста', clicks: 983, conversion: 22 },
  { source: 'TG Launch', clicks: 641, conversion: 14 },
  { source: 'Retarget CPA', clicks: 408, conversion: 31 },
]

function formatNumber(value: number) {
  return new Intl.NumberFormat('ru-RU').format(value)
}

export default function DashboardPage() {
  return (
    <section className="h-full min-h-0 overflow-y-auto rounded-2xl border border-white/5 bg-background/55 p-4 text-gray-200 shadow-card backdrop-blur-xl md:p-6">
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-accent-300/70">
            Live Revenue Console
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white md:text-3xl">
            Dashboard
          </h1>
        </div>
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-accent-300/25 bg-accent-400/10 px-3 py-1.5 text-sm text-accent-100 shadow-glow-accent">
          <Flame size={15} />
          Сегодня выше плана на 15%
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {kpiCards.map((card) => {
          const Icon = card.icon

          return (
            <div
              key={card.title}
              className="rounded-xl border border-white/5 bg-surface/90 p-4 shadow-card"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm text-gray-500">{card.title}</p>
                  <p className="mt-2 text-3xl font-semibold tracking-tight text-white">
                    {card.value}
                  </p>
                </div>
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04]"
                  style={{ color: card.color, boxShadow: `0 0 22px ${card.color}44` }}
                >
                  <Icon size={18} />
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between gap-3">
                <span
                  className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-semibold ${
                    card.positive
                      ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300'
                      : 'border-red-400/25 bg-red-400/10 text-red-300'
                  }`}
                >
                  {card.positive ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
                  {card.delta}
                </span>
                <div className="h-10 w-24">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={card.sparkline}>
                      <XAxis hide dataKey="label" />
                      <YAxis hide domain={['dataMin - 2', 'dataMax + 2']} />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={card.color}
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,0.8fr)]">
        <div className="rounded-xl border border-white/5 bg-surface/90 p-4 shadow-card">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-white">Динамика чатов и лидов</h2>
              <p className="text-sm text-gray-500">Mock data for the current week</p>
            </div>
            <div className="flex gap-2 text-xs">
              <span className="rounded-full bg-accent-400/10 px-2 py-1 text-accent-200">
                Chats
              </span>
              <span className="rounded-full bg-orange-400/10 px-2 py-1 text-orange-200">
                Leads
              </span>
            </div>
          </div>
          <div className="h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={growthData} margin={{ left: -18, right: 8, top: 16, bottom: 0 }}>
                <defs>
                  <linearGradient id="chatsGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22D3EE" stopOpacity={0.38} />
                    <stop offset="100%" stopColor="#22D3EE" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="leadsGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#FB923C" stopOpacity={0.34} />
                    <stop offset="100%" stopColor="#FB923C" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fill: '#6B7280' }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6B7280' }} />
                <Tooltip
                  contentStyle={{
                    background: '#111827',
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: 12,
                    color: '#E5E7EB',
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="chats"
                  stroke="#22D3EE"
                  strokeWidth={3}
                  fill="url(#chatsGradient)"
                  dot={false}
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="leads"
                  stroke="#FB923C"
                  strokeWidth={3}
                  fill="url(#leadsGradient)"
                  dot={false}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-xl border border-white/5 bg-surface/90 p-4 shadow-card">
          <div className="mb-4 flex items-center gap-2">
            <Link2 size={18} className="text-accent-300" />
            <h2 className="text-base font-semibold text-white">Топ ссылок</h2>
          </div>
          <div className="space-y-4">
            {trackingLinks.map((link) => (
              <div key={link.source}>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white">{link.source}</p>
                    <p className="text-xs text-gray-500">{formatNumber(link.clicks)} переходов</p>
                  </div>
                  <span className="rounded-full border border-primary-300/25 bg-primary-500/10 px-2 py-1 text-xs font-semibold text-primary-100">
                    CR {link.conversion}%
                  </span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-accent-400 to-primary-400 shadow-glow-accent"
                    style={{ width: `${Math.min(link.conversion * 3, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-white/5 bg-surface/90 p-4 shadow-card">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Мои воронки</h2>
            <p className="text-sm text-gray-500">Статусы лидов по основному проекту</p>
          </div>
          <span className="rounded-full bg-white/[0.04] px-3 py-1 text-xs text-gray-400">
            619 active
          </span>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {funnels.map((funnel) => (
            <div
              key={funnel.label}
              className={`rounded-xl border border-white/5 bg-white/[0.03] p-4 ${funnel.glow}`}
            >
              <div className="mb-4 flex items-center justify-between">
                <h3 className="font-semibold text-white">{funnel.label}</h3>
                <span className="text-2xl font-semibold text-white">{funnel.value}</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${funnel.color}`}
                  style={{ width: `${funnel.percent}%` }}
                />
              </div>
              <p className="mt-3 text-xs text-gray-500">{funnel.percent}% от недельной цели</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

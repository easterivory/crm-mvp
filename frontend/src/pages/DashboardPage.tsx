import { BarChart3, MessageSquareText } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export default function DashboardPage() {
  const navigate = useNavigate()

  return (
    <section className="flex h-full min-h-0 items-center justify-center rounded-xl border border-white/5 bg-surface/80 p-6 text-gray-200 shadow-card">
      <div className="max-w-xl text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl border border-accent-300/25 bg-accent-400/10 text-accent-100">
          <BarChart3 size={22} />
        </div>
        <h1 className="mt-4 text-2xl font-semibold text-white">Обзор аналитики будет добавлен позже</h1>
        <p className="mt-2 text-sm leading-6 text-gray-500">
          Здесь больше нет демонстрационных метрик. Для ежедневной работы используйте реальные чаты, воронки и трекинг.
        </p>
        <button
          type="button"
          onClick={() => navigate('/chats')}
          className="mt-5 inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 text-sm font-semibold text-gray-100 transition hover:border-accent-300/50"
        >
          <MessageSquareText size={16} />
          Перейти в чаты
        </button>
      </div>
    </section>
  )
}

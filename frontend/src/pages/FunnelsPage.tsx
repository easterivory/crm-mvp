import { Workflow } from 'lucide-react'

export default function FunnelsPage() {
  return (
    <section className="flex h-full min-h-0 items-center justify-center overflow-y-auto rounded-xl border border-white/5 bg-surface p-6 text-center shadow-card">
      <div>
        <Workflow className="mx-auto text-accent-300" size={36} />
        <h1 className="mt-4 text-2xl font-semibold text-white">Воронки</h1>
        <p className="mt-2 text-sm text-gray-500">
          Конструктор воронок будет добавлен позже.
        </p>
      </div>
    </section>
  )
}

import { SlidersHorizontal } from 'lucide-react'

type ChatFilterButtonProps = {
  activeCount: number
  isOpen: boolean
  onClick: () => void
}

export default function ChatFilterButton({
  activeCount,
  isOpen,
  onClick,
}: ChatFilterButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative inline-flex h-10 shrink-0 items-center gap-2 rounded-xl border px-3 text-sm font-medium transition ${
        isOpen || activeCount > 0
          ? 'border-accent-300/40 bg-accent-400/10 text-accent-50'
          : 'border-white/10 bg-white/[0.03] text-gray-300 hover:border-accent-300/40'
      }`}
    >
      <SlidersHorizontal size={15} />
      Фильтры
      {activeCount > 0 ? (
        <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent-400 px-1.5 text-xs font-semibold text-background">
          {activeCount}
        </span>
      ) : null}
    </button>
  )
}

import { Search, X } from 'lucide-react'
import type { KeyboardEvent } from 'react'

type ChatSearchBarProps = {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  onClear: () => void
}

export default function ChatSearchBar({
  value,
  onChange,
  onSubmit,
  onClear,
}: ChatSearchBarProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <div className="relative">
      <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Поиск по имени, телефону, username, tg ID, сообщению"
        className="h-10 w-full rounded-xl border border-white/10 bg-background/70 pl-9 pr-9 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-accent-300/50"
      />
      {value ? (
        <button
          type="button"
          onClick={onClear}
          className="absolute right-2 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-gray-400 transition hover:bg-white/[0.06] hover:text-gray-100"
          title="Очистить поиск"
        >
          <X size={14} />
        </button>
      ) : null}
    </div>
  )
}

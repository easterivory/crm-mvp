import { LockKeyhole } from 'lucide-react'

type UnsupportedBlockCardProps = {
  blockType: string
}

export default function UnsupportedBlockCard({ blockType }: UnsupportedBlockCardProps) {
  return (
    <div className="rounded-lg border border-amber-300/25 bg-amber-300/10 p-3 text-sm text-amber-50">
      <div className="flex items-center gap-2 font-medium">
        <LockKeyhole size={15} />
        Неподдерживаемый блок
      </div>
      <p className="mt-1 break-words text-xs leading-5 text-amber-100/80">
        {blockType} сохранён в backend registry, но редактор v1 показывает его только для чтения.
      </p>
    </div>
  )
}

import { ReactNode } from 'react'

type EmptyStateProps = {
  title: string
  description?: string
  icon?: ReactNode
}

export default function EmptyState({ title, description, icon }: EmptyStateProps) {
  return (
    <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-white/10 bg-white/[0.02] p-6 text-center">
      <div>
        {icon ? <div className="mb-3 flex justify-center text-accent-300">{icon}</div> : null}
        <p className="font-medium text-white">{title}</p>
        {description ? <p className="mt-1 text-sm text-gray-500">{description}</p> : null}
      </div>
    </div>
  )
}

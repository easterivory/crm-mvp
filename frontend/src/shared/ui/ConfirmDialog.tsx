import { LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import Modal from './Modal'

type ConfirmDialogProps = {
  title: string
  description: ReactNode
  confirmLabel: string
  cancelLabel?: string
  isLoading?: boolean
  tone?: 'danger' | 'primary'
  onCancel: () => void
  onConfirm: () => void
}

export default function ConfirmDialog({
  title,
  description,
  confirmLabel,
  cancelLabel = 'Отмена',
  isLoading = false,
  tone = 'primary',
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  const confirmClass =
    tone === 'danger'
      ? 'bg-red-500 text-white hover:bg-red-400'
      : 'bg-gradient-to-r from-primary-500 to-accent-500 text-white shadow-glow-primary hover:shadow-glow-accent'

  return (
    <Modal title={title} description={description} onClose={onCancel} maxWidthClassName="max-w-md">
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={isLoading}
          className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {cancelLabel}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isLoading}
          className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${confirmClass}`}
        >
          {isLoading ? <LoaderCircle size={16} className="animate-spin" /> : null}
          {confirmLabel}
        </button>
      </div>
    </Modal>
  )
}

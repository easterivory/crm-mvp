import { ReactNode, useEffect, useId } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

type ModalProps = {
  title: string
  description?: string
  children: ReactNode
  onClose: () => void
  maxWidthClassName?: string
}

export default function Modal({
  title,
  description,
  children,
  onClose,
  maxWidthClassName = 'max-w-md',
}: ModalProps) {
  const titleId = useId()

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex min-h-dvh items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose()
        }
      }}
    >
      <div
        className={`flex max-h-[calc(100dvh-2rem)] w-full ${maxWidthClassName} flex-col overflow-hidden rounded-2xl border border-white/10 bg-[#0B0F19] shadow-card`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-start justify-between gap-4 border-b border-white/10 px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-lg font-semibold text-white">
              {title}
            </h2>
            {description ? (
              <p className="mt-1 text-sm text-gray-500">{description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close modal"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        <div className="min-h-0 overflow-y-auto p-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}

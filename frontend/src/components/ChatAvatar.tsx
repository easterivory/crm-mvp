import { useEffect, useRef, useState } from 'react'
import api from '../api/client'
import { LoaderCircle } from 'lucide-react'
import { Modal } from '../shared/ui'

let active = 0
const waiting: Array<() => void> = []

function enqueue<T>(request: () => Promise<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const run = () => {
      active += 1
      request().then(resolve, reject).finally(() => {
        active -= 1
        waiting.shift()?.()
      })
    }
    if (active < 4) run()
    else waiting.push(run)
  })
}

export default function ChatAvatar({ chatId, projectId, name, onEmptyClick }: {
  chatId: string; projectId: string; name: string; onEmptyClick?: () => void
}) {
  const element = useRef<HTMLButtonElement>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [isPreviewLoading, setIsPreviewLoading] = useState(false)
  useEffect(() => {
    setUrl(null)
    setIsOpen(false)
    const controller = new AbortController()
    let objectUrl: string | null = null
    let started = false
    const load = () => {
      if (started) return
      started = true
      void enqueue(async () => {
        if (controller.signal.aborted) return
        const response = await api.get(`/chats/${chatId}/avatar`, {
          params: { project_id: projectId }, responseType: 'blob',
          signal: controller.signal, timeout: 30000,
        })
        if (controller.signal.aborted || response.status === 204 || !response.data.size) return
        objectUrl = URL.createObjectURL(response.data)
        setUrl(objectUrl)
      }).catch(() => { /* Initials remain when Telegram or the cache is unavailable. */ })
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect()
        load()
      }
    }, { rootMargin: '64px' })
    if (element.current) observer.observe(element.current)
    return () => {
      observer.disconnect()
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [chatId, projectId])
  useEffect(() => {
    if (!isOpen) return
    const controller = new AbortController()
    let objectUrl: string | null = null
    setPreviewUrl(null)
    setIsPreviewLoading(true)
    void enqueue(async () => {
      if (controller.signal.aborted) return
      const response = await api.get(`/chats/${chatId}/avatar`, {
        params: { project_id: projectId, preview: true }, responseType: 'blob',
        signal: controller.signal, timeout: 30000,
      })
      if (!controller.signal.aborted && response.status === 200 && response.data.size) {
        objectUrl = URL.createObjectURL(response.data)
        setPreviewUrl(objectUrl)
      }
    }).catch(() => { /* The existing thumbnail remains visible. */ }).finally(() => {
      if (!controller.signal.aborted) setIsPreviewLoading(false)
    })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [isOpen, chatId, projectId])
  const initials = name.trim().split(/\s+/).slice(0, 2).map((part) => Array.from(part)[0]).join('').toUpperCase()
  return (
    <>
    <button type="button" ref={element} disabled={!url && !onEmptyClick}
      onClick={(event) => { event.stopPropagation(); if (url) { setPreviewUrl(null); setIsPreviewLoading(true); setIsOpen(true) } else onEmptyClick?.() }}
      title={url ? 'Увеличить аватарку' : name}
      className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-white/10 bg-accent-400/10 text-sm font-semibold text-accent-200 outline-none focus-visible:ring-2 focus-visible:ring-accent-300 disabled:cursor-default" aria-label={url ? `Увеличить аватарку: ${name}` : name}>
      {initials || '?'}
      {url ? <img src={url} alt="" className="absolute inset-0 h-full w-full object-cover" onError={() => setUrl(null)} /> : null}
    </button>
    {isOpen && url ? (
      <Modal title={name} onClose={() => setIsOpen(false)} maxWidthClassName="max-w-xl">
        <div className="relative flex aspect-square w-full items-center justify-center overflow-hidden rounded-lg bg-black/30">
          <img src={previewUrl ?? url} alt={name} className="h-full w-full object-contain" onError={() => setPreviewUrl(null)} />
          {isPreviewLoading ? <LoaderCircle size={24} className="absolute bottom-3 right-3 animate-spin text-white" aria-label="Загрузка фото" /> : null}
        </div>
      </Modal>
    ) : null}
    </>
  )
}

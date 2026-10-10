import { useEffect, useRef, useState } from 'react'
import api from '../api/client'

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

export default function ChatAvatar({ chatId, projectId, name }: {
  chatId: string; projectId: string; name: string
}) {
  const element = useRef<HTMLDivElement>(null)
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    setUrl(null)
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
  const initials = name.trim().split(/\s+/).slice(0, 2).map((part) => Array.from(part)[0]).join('').toUpperCase()
  return (
    <div ref={element} className="relative flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-white/10 bg-accent-400/10 text-sm font-semibold text-accent-200" aria-label={name}>
      {initials || '?'}
      {url ? <img src={url} alt="" className="absolute inset-0 h-full w-full object-cover" onError={() => setUrl(null)} /> : null}
    </div>
  )
}

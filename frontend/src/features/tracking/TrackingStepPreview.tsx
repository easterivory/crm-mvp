import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Eye, Image, MessageSquare, Mic, Video, X } from 'lucide-react'
import api from '../../api/client'

export type JourneyStepOption = { id: string; funnel_id: string; funnel_name: string; key: string;
  name: string; title: string; number: number; version_number: number; bot_name?: string | null; bot_username?: string | null; equivalent_step_ids?: string[] }
export const botLabel = (step: Pick<JourneyStepOption, 'bot_name' | 'bot_username'>) =>
  [step.bot_name || 'Без бота', step.bot_username ? `@${step.bot_username.replace(/^@/, '')}` : ''].filter(Boolean).join(' · ')
export const stepLabel = (step: JourneyStepOption) => `${botLabel(step)} · ${step.name}`
type Preview = { step_type: string; block_type: string; messages: { text: string; media_type: string;
  buttons: string[]; wait_for_answer: boolean; delay_seconds: number | null }[] }
const types: Record<string, string> = { message: 'Сообщение', input: 'Ввод ответа', condition: 'Условие',
  crm_action: 'CRM-действие', delay: 'Задержка', finish: 'Завершение', start: 'Старт', ai_response: 'ИИ-ответ', integration: 'Интеграция' }

export default function TrackingStepPreview({ projectId, step }: { projectId: string; step: JourneyStepOption }) {
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const anchor = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const id = useId()
  const cancelTimer = () => { if (timer.current) clearTimeout(timer.current) }
  const close = () => { cancelTimer(); setOpen(false); setPinned(false) }
  const show = () => { cancelTimer(); setOpen(true) }
  const leave = () => { cancelTimer(); if (!pinned) timer.current = setTimeout(() => setOpen(false), 180) }
  useEffect(() => () => cancelTimer(), [])
  useEffect(() => {
    if (!open || preview) return
    const controller = new AbortController(); setError(false)
    void api.get<Preview>('/tracking/metrics/step-preview', { signal: controller.signal,
      params: { project_id: projectId, step_id: step.id } }).then(({ data }) => {
        if (!controller.signal.aborted) setPreview(data)
      }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [open, preview, projectId, step.id, retry])
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const rect = anchor.current?.getBoundingClientRect()
      if (!rect) return
      const width = Math.min(420, window.innerWidth - 24)
      const height = Math.min(460, window.innerHeight - 24)
      setPosition({ left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
        top: Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - height - 12)) })
    }
    const outside = (event: PointerEvent) => {
      if (!panel.current?.contains(event.target as Node) && !anchor.current?.contains(event.target as Node)) close()
    }
    const keydown = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    place(); window.addEventListener('resize', place); window.addEventListener('scroll', place, true)
    document.addEventListener('pointerdown', outside); document.addEventListener('keydown', keydown)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true)
      document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', keydown) }
  }, [open])
  return <>
    <button ref={anchor} type="button" className="journey-step-eye" title="Посмотреть шаг"
      aria-label={`Посмотреть шаг #${step.number}: ${step.title}`} aria-expanded={open} aria-controls={open ? id : undefined}
      onMouseEnter={() => { cancelTimer(); timer.current = setTimeout(show, 250) }} onMouseLeave={leave}
      onFocus={show} onBlur={leave} onClick={() => { if (pinned) close(); else { show(); setPinned(true) } }}><Eye size={17} /></button>
    {open && createPortal(<div ref={panel} id={id} role="dialog" aria-label={`Шаг #${step.number}: ${step.title}`}
      className="journey-step-preview" style={position} onMouseEnter={cancelTimer} onMouseLeave={leave}
      onFocusCapture={cancelTimer} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) leave() }}>
      <header><div><small>{botLabel(step)}</small><span>{step.funnel_name} · v{step.version_number}</span>
        <strong>#{step.number} · {step.title}</strong></div>
        <button type="button" title="Закрыть просмотр" aria-label="Закрыть просмотр" onClick={close}><X size={17} /></button></header>
      {error ? <div role="alert">Не удалось загрузить шаг <button type="button" onClick={() => setRetry(n => n + 1)}>Повторить</button></div>
        : !preview ? <p role="status">Загрузка шага…</p> : <>
          <small>{types[preview.step_type] || preview.block_type}</small>
          {preview.messages.map((message, index) => <div className="journey-step-message" key={index}>
            {preview.messages.length > 1 && <small>Сообщение {index + 1}</small>}
            {message.media_type !== 'text' && <div className="journey-step-media">
              {message.media_type === 'photo' ? <Image size={24} /> : message.media_type === 'voice' ? <Mic size={24} />
                : message.media_type.includes('video') ? <Video size={24} /> : <MessageSquare size={24} />}
              {({ photo: 'Фото', voice: 'Голосовое сообщение', video: 'Видео', video_note: 'Кружок', document: 'Файл' } as Record<string, string>)[message.media_type] || message.media_type}
            </div>}
            {message.text && <p>{message.text}</p>}
            {message.buttons.map((button, i) => <div className="journey-step-button" key={i}>{button}</div>)}
            {message.wait_for_answer && <small>Ожидание ответа</small>}
            {!!message.delay_seconds && <small>Задержка: {message.delay_seconds} сек.</small>}
          </div>)}
        </>}
    </div>, document.body)}
  </>
}

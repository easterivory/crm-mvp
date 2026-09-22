import { Bold, Italic, Underline, Strikethrough, EyeOff, Code, Link, Quote, Eraser, Check } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'

type Props = {
  value: string
  parseMode?: 'HTML' | null
  onChange: (text: string, parseMode: 'HTML' | null) => void
  disabled?: boolean
  rows?: number
  placeholder?: string
  className?: string
}

const escapeText = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const documentFor = (text: string) => new DOMParser().parseFromString(text, 'text/html')
const plainText = (text: string) => documentFor(text).body.textContent ?? ''

function preview(text: string): ReactNode {
  const render = (node: ChildNode, key: number): ReactNode => {
    if (node.nodeType === Node.TEXT_NODE) return node.textContent
    if (!(node instanceof Element)) return null
    const children = Array.from(node.childNodes).map(render)
    switch (node.tagName.toLowerCase()) {
      case 'b': case 'strong': return <strong key={key}>{children}</strong>
      case 'i': case 'em': return <em key={key}>{children}</em>
      case 'u': return <u key={key}>{children}</u>
      case 's': case 'del': return <s key={key}>{children}</s>
      case 'code': case 'pre': return <code key={key} className="rounded bg-white/10 px-1 font-mono">{children}</code>
      case 'tg-spoiler': return <span key={key} className="rounded bg-gray-500/40">{children}</span>
      case 'blockquote': return <blockquote key={key} className="border-l-2 border-accent-400 pl-2">{children}</blockquote>
      case 'a': return <span key={key} className="text-accent-300 underline">{children}</span>
      default: return <span key={key}>{children}</span>
    }
  }
  return Array.from(documentFor(text).body.childNodes).map(render)
}

export default function TelegramTextEditor({ value, parseMode, onChange, disabled, rows = 4, placeholder, className }: Props) {
  const input = useRef<HTMLTextAreaElement>(null)
  const selection = useRef({ start: 0, end: 0 })
  const [link, setLink] = useState<string | null>(null)
  const enabled = parseMode === 'HTML'
  const wrap = (tag: string, attribute = '') => {
    const { start, end } = selection.current
    if (start === end) return
    const opening = `<${tag}${attribute}>`
    const next = value.slice(0, start) + opening + value.slice(start, end) + `</${tag}>` + value.slice(end)
    onChange(next, 'HTML')
    requestAnimationFrame(() => {
      input.current?.focus()
      input.current?.setSelectionRange(start + opening.length, end + opening.length)
    })
  }
  const tools = [
    { tag: 'b', label: 'Жирный', Icon: Bold }, { tag: 'i', label: 'Курсив', Icon: Italic },
    { tag: 'u', label: 'Подчёркнутый', Icon: Underline }, { tag: 's', label: 'Зачёркнутый', Icon: Strikethrough },
    { tag: 'tg-spoiler', label: 'Спойлер', Icon: EyeOff }, { tag: 'code', label: 'Код', Icon: Code },
    { tag: 'blockquote', label: 'Цитата', Icon: Quote },
  ]
  const validLink = link !== null && /^(https?:\/\/|tg:\/\/|mailto:)\S+$/i.test(link)
  return <div className="min-w-0 space-y-2">
    <label className="flex items-center gap-2 text-xs text-gray-400">
      <input type="checkbox" checked={enabled} disabled={disabled}
        onChange={(event) => { setLink(null); onChange(event.target.checked ? escapeText(value) : plainText(value), event.target.checked ? 'HTML' : null) }} />
      Оформление Telegram
    </label>
    {enabled && <div role="toolbar" aria-label="Оформление текста" className="flex flex-wrap gap-1">
      {tools.map(({ tag, label, Icon }) => <button key={tag} type="button" title={label} aria-label={label} disabled={disabled}
        onMouseDown={(event) => event.preventDefault()} onClick={() => wrap(tag)}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-white/10 text-gray-200 hover:bg-white/10 disabled:opacity-40"><Icon size={16} /></button>)}
      <button type="button" title="Ссылка" aria-label="Ссылка" disabled={disabled} onMouseDown={(event) => event.preventDefault()}
        onClick={() => setLink(link === null ? '' : null)} className="flex h-8 w-8 items-center justify-center rounded border border-white/10"><Link size={16} /></button>
      <button type="button" title="Убрать всё оформление" aria-label="Убрать всё оформление" disabled={disabled}
        onClick={() => onChange(escapeText(plainText(value)), 'HTML')} className="flex h-8 w-8 items-center justify-center rounded border border-white/10"><Eraser size={16} /></button>
    </div>}
    {link !== null && <div className="flex min-w-0 gap-2">
      <input aria-label="Адрес ссылки" value={link} onChange={(event) => setLink(event.target.value)} placeholder="https://"
        className="min-w-0 flex-1 rounded border border-white/10 bg-background px-2 py-1 text-sm" />
      <button type="button" title="Добавить ссылку" aria-label="Добавить ссылку" disabled={!validLink || disabled}
        onClick={() => { wrap('a', ` href="${escapeText(link)}"`); setLink(null) }} className="h-8 w-8 shrink-0 disabled:opacity-40"><Check size={16} /></button>
    </div>}
    <textarea ref={input} value={value} rows={rows} disabled={disabled} placeholder={placeholder}
      onSelect={(event) => { selection.current = { start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd } }}
      onChange={(event) => onChange(event.target.value, enabled ? 'HTML' : null)}
      className={className ?? 'w-full resize-y rounded-lg border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none disabled:opacity-60'} />
    {enabled && <div className="min-w-0 whitespace-pre-wrap break-words border-t border-white/10 pt-2 text-sm text-gray-200" aria-label="Предпросмотр сообщения">{preview(value)}</div>}
  </div>
}

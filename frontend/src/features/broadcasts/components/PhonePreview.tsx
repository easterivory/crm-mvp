import { FileText, Mic, PlayCircle, Video } from 'lucide-react'

import type { BroadcastContent, BroadcastMediaType } from '../types'

type PhonePreviewProps = {
  content: BroadcastContent
  mediaPreviewUrls: Record<string, string>
}

function isMediaType(value: string | undefined): value is BroadcastMediaType {
  return value === 'photo' ||
    value === 'video' ||
    value === 'voice' ||
    value === 'video_note' ||
    value === 'document'
}

function previewUrl(message: BroadcastContent['messages'][number], urls: Record<string, string>) {
  return message.media?.upload_id ? urls[message.media.upload_id] : null
}

export default function PhonePreview({ content, mediaPreviewUrls }: PhonePreviewProps) {
  const messages = content.messages.filter((message) => {
    if (isMediaType(message.type)) {
      return Boolean(message.media?.upload_id || message.media?.telegram_file_id)
    }
    return Boolean(message.text?.trim())
  })

  return (
    <div className="sticky top-5 mx-auto w-full max-w-[420px] rounded-[32px] border border-white/10 bg-[#05070d] p-3 shadow-2xl shadow-black/35">
      <div className="rounded-[26px] border border-white/8 bg-[#111827] p-3">
        <div className="mx-auto mb-3 h-1.5 w-16 rounded-full bg-white/15" />
        <div className="overflow-hidden rounded-[22px] border border-white/8 bg-[#0b1220]">
          <header className="flex items-center gap-3 border-b border-white/8 bg-[#172033] px-4 py-3">
            <div className="h-9 w-9 rounded-full bg-gradient-to-br from-sky-400 to-cyan-300" />
            <div>
              <p className="text-sm font-semibold text-white">Telegram</p>
              <p className="text-xs text-emerald-200/70">bot online</p>
            </div>
          </header>
          <div className="min-h-[520px] bg-[radial-gradient(circle_at_20%_20%,rgba(56,189,248,0.08),transparent_28%),linear-gradient(145deg,#101827,#07111f)] p-4">
            <div className="mb-4 text-center text-[11px] text-gray-500">Сегодня</div>
            {messages.length ? (
              <div className="space-y-3">
                {messages.map((message, index) => {
                  const type = isMediaType(message.type) ? message.type : null
                  const url = previewUrl(message, mediaPreviewUrls)
                  return (
                    <div key={index} className="max-w-[88%] rounded-2xl rounded-bl-md bg-[#2b5278] px-2.5 py-2 text-sm leading-5 text-white shadow-lg shadow-black/15">
                      {message.delay_seconds ? (
                        <p className="mb-1 text-[11px] text-sky-100/70">+{message.delay_seconds} сек.</p>
                      ) : null}
                      {type === 'photo' ? (
                        url ? (
                          <img src={url} alt="" className="mb-2 max-h-56 w-full rounded-xl object-cover" />
                        ) : (
                          <div className="mb-2 flex h-40 items-center justify-center rounded-xl bg-black/25 text-xs text-sky-100">
                            Фото из Telegram file_id
                          </div>
                        )
                      ) : null}
                      {type === 'video' ? (
                        url ? (
                          <video src={url} className="mb-2 max-h-56 w-full rounded-xl object-cover" controls />
                        ) : (
                          <div className="mb-2 flex h-40 items-center justify-center gap-2 rounded-xl bg-black/25 text-xs text-sky-100">
                            <Video size={18} />
                            Видео из Telegram file_id
                          </div>
                        )
                      ) : null}
                      {type === 'video_note' ? (
                        <div className="mb-2 flex justify-center">
                          {url ? (
                            <video src={url} className="h-40 w-40 rounded-full object-cover" controls />
                          ) : (
                            <div className="flex h-40 w-40 items-center justify-center rounded-full bg-black/30 text-sky-100">
                              <PlayCircle size={38} />
                            </div>
                          )}
                        </div>
                      ) : null}
                      {type === 'voice' ? (
                        <div className="mb-2 flex items-center gap-2 rounded-xl bg-black/20 px-3 py-2 text-sky-50">
                          <Mic size={17} />
                          <div className="h-1 flex-1 rounded-full bg-sky-100/70" />
                          <span className="text-[11px]">0:12</span>
                        </div>
                      ) : null}
                      {type === 'document' ? (
                        <div className="mb-2 flex items-center gap-3 rounded-xl bg-black/20 px-3 py-2">
                          <FileText size={20} className="text-sky-100" />
                          <div className="min-w-0">
                            <p className="truncate text-xs font-semibold">{message.media?.file_name || 'Документ'}</p>
                            <p className="text-[11px] text-sky-100/70">Telegram document</p>
                          </div>
                        </div>
                      ) : null}
                      {type !== 'video_note' ? (
                        <p className="whitespace-pre-wrap text-[14px]">
                          {type ? message.caption : message.text}
                        </p>
                      ) : null}
                      {message.buttons?.length ? (
                        <div className="mt-2 grid gap-1">
                          {message.buttons.map((button, buttonIndex) => (
                            <span
                              key={buttonIndex}
                              className="rounded-lg bg-white/95 px-2 py-1.5 text-center text-xs font-medium text-[#2b5278]"
                            >
                              {String(button.label ?? button.text ?? 'Кнопка')}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <p className="mt-1 text-right text-[10px] text-sky-100/70">✓✓</p>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="flex h-56 items-center justify-center rounded-xl border border-dashed border-white/10 px-4 text-center text-sm text-gray-500">
                Введите текст или выберите медиа.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

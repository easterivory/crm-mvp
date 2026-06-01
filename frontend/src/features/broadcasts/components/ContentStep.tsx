import {
  FileText,
  Image,
  LoaderCircle,
  Mic,
  Paperclip,
  PlayCircle,
  Search,
  Video,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import type {
  BroadcastContent,
  BroadcastMediaType,
  BroadcastOption,
  BroadcastUpload,
  ProjectSnippet,
} from '../types'
import BroadcastButtonListEditor from './BroadcastButtonListEditor'
import VariablePicker from './VariablePicker'

type ContentStepProps = {
  content: BroadcastContent
  botId: string | null
  funnels: BroadcastOption[]
  snippets: ProjectSnippet[]
  mediaPreviewUrls: Record<string, string>
  onChange: (content: BroadcastContent) => void
  onMediaPreview: (uploadId: string, url: string) => void
  onSnippetSelected: (snippetId: string | null) => void
  onUploadMedia: (file: File, mediaType: BroadcastMediaType) => Promise<BroadcastUpload>
}

const mediaModes: Array<{
  type: BroadcastMediaType
  label: string
  accept: string
}> = [
  { type: 'document', label: 'Документ', accept: '*/*' },
  { type: 'photo', label: 'Фото', accept: 'image/jpeg,image/png,image/webp' },
  { type: 'video', label: 'Видео', accept: 'video/mp4,video/quicktime,video/webm' },
  { type: 'voice', label: 'Голосовое', accept: 'audio/ogg,audio/mpeg,audio/mp4,audio/webm,audio/wav' },
  { type: 'video_note', label: 'Кружок', accept: 'video/mp4,video/quicktime,video/webm' },
]

function primaryMessage(content: BroadcastContent) {
  return content.messages[0] ?? { type: 'text', text: '', delay_seconds: 0, buttons: [] }
}

function isMediaType(value: string | undefined): value is BroadcastMediaType {
  return value === 'photo' ||
    value === 'video' ||
    value === 'voice' ||
    value === 'video_note' ||
    value === 'document'
}

function mediaLabel(type: string | undefined) {
  if (type === 'photo') return 'Фото'
  if (type === 'video') return 'Видео'
  if (type === 'voice') return 'Голосовое'
  if (type === 'video_note') return 'Видео-кружок'
  if (type === 'document') return 'Документ'
  return 'Текст'
}

function mediaIcon(type: string | undefined) {
  if (type === 'photo') return <Image size={17} />
  if (type === 'video') return <Video size={17} />
  if (type === 'voice') return <Mic size={17} />
  if (type === 'video_note') return <PlayCircle size={17} />
  return <FileText size={17} />
}

function formatBytes(value?: number) {
  if (!value) return 'размер не указан'
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} КБ`
  return `${(value / 1024 / 1024).toFixed(1)} МБ`
}

export default function ContentStep({
  content,
  botId,
  funnels,
  snippets,
  mediaPreviewUrls,
  onChange,
  onMediaPreview,
  onSnippetSelected,
  onUploadMedia,
}: ContentStepProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [snippetSearch, setSnippetSearch] = useState('')
  const [uploadMode, setUploadMode] = useState<BroadcastMediaType>('document')
  const [isUploading, setIsUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const message = primaryMessage(content)
  const availableFunnels = funnels.filter((funnel) => !botId || funnel.meta?.botId === botId)
  const snippetNeedle = snippetSearch.trim().toLowerCase()
  const filteredSnippets = useMemo(
    () =>
      snippets.filter((snippet) =>
        [snippet.name, snippet.content ?? '', mediaLabel(snippet.type)]
          .join(' ')
          .toLowerCase()
          .includes(snippetNeedle),
      ),
    [snippetNeedle, snippets],
  )
  const mediaType = isMediaType(message.type) ? message.type : null
  const captionText = mediaType ? message.caption ?? '' : message.text ?? ''
  const previewUrl = message.media?.upload_id
    ? mediaPreviewUrls[message.media.upload_id]
    : null

  const replaceMessage = (patch: Partial<typeof message>) => {
    onChange({
      type: 'message',
      after_send_action: null,
      messages: [{ ...message, ...patch }],
    })
  }

  const applySnippet = (snippet: ProjectSnippet) => {
    onSnippetSelected(snippet.id)
    if (snippet.type === 'text') {
      replaceMessage({
        type: 'text',
        text: snippet.content ?? '',
        caption: undefined,
        media: undefined,
      })
      return
    }
    if (!snippet.file_id) {
      return
    }
    replaceMessage({
      type: snippet.type,
      text: undefined,
      caption: snippet.type === 'video_note' ? undefined : snippet.content ?? '',
      media: {
        source: 'telegram_file_id',
        telegram_file_id: snippet.file_id,
        file_name: snippet.name,
        media_type: snippet.type,
      },
    })
  }

  const uploadFile = async (file: File | null | undefined) => {
    if (!file) return
    setIsUploading(true)
    setUploadError('')
    try {
      const upload = await onUploadMedia(file, uploadMode)
      const previewUrl = URL.createObjectURL(file)
      onMediaPreview(upload.upload_id, previewUrl)
      onSnippetSelected(null)
      replaceMessage({
        type: upload.media_type,
        text: undefined,
        caption: upload.media_type === 'video_note' ? undefined : captionText,
        media: {
          source: 'upload',
          upload_id: upload.upload_id,
          file_name: upload.file_name,
          mime_type: upload.mime_type,
          file_size: upload.file_size,
          media_type: upload.media_type,
        },
      })
    } catch {
      setUploadError('Не удалось загрузить файл выбранным способом.')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-white">Библиотека заготовок</h2>
            <p className="text-xs text-gray-500">Текстовые и медиа-шаблоны проекта.</p>
          </div>
          <div className="relative w-full sm:w-64">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              value={snippetSearch}
              onChange={(event) => setSnippetSearch(event.target.value)}
              placeholder="Найти шаблон"
              className="h-9 w-full rounded-lg border border-white/10 bg-background/70 pl-8 pr-3 text-sm text-gray-100 outline-none"
            />
          </div>
        </div>
        <div className="mt-3 max-h-40 overflow-y-auto rounded-lg border border-white/8 bg-background/35 p-1.5">
          {filteredSnippets.length > 0 ? (
            filteredSnippets.map((snippet) => (
              <button
                key={snippet.id}
                type="button"
                onClick={() => applySnippet(snippet)}
                className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left text-sm text-gray-300 transition hover:bg-white/[0.04] hover:text-white"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{snippet.name}</span>
                  <span className="block truncate text-xs text-gray-500">
                    {mediaLabel(snippet.type)}{snippet.content ? ` · ${snippet.content}` : ''}
                  </span>
                </span>
                <span className="shrink-0 text-accent-100">{mediaIcon(snippet.type)}</span>
              </button>
            ))
          ) : (
            <p className="px-2 py-3 text-sm text-gray-500">Заготовок нет.</p>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-white">Сообщение</h2>
            <p className="text-xs text-gray-500">Текст уйдёт сообщением, для медиа станет caption.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              onSnippetSelected(null)
              replaceMessage({
                type: 'text',
                text: captionText,
                caption: undefined,
                media: undefined,
              })
            }}
            className="h-9 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35"
          >
            Только текст
          </button>
        </div>
        {mediaType ? (
          <div className="mb-3 rounded-xl border border-white/10 bg-background/70 p-3">
            <div className="flex items-center gap-3">
              {previewUrl && mediaType === 'photo' ? (
                <img src={previewUrl} alt="" className="h-14 w-14 shrink-0 rounded-xl object-cover" />
              ) : previewUrl && mediaType === 'video_note' ? (
                <video src={previewUrl} className="h-16 w-16 shrink-0 rounded-full object-cover" muted />
              ) : (
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent-400/15 text-accent-100">
                  {mediaIcon(mediaType)}
                </div>
              )}
              <div className="min-w-0">
                <p className="text-sm font-semibold text-white">{mediaLabel(mediaType)}</p>
                <p className="truncate text-xs text-gray-500">
                  {message.media?.file_name || 'Telegram file_id'}
                  {message.media?.file_size ? ` · ${formatBytes(message.media.file_size)}` : ''}
                </p>
              </div>
            </div>
          </div>
        ) : null}
        <textarea
          rows={7}
          value={captionText}
          disabled={mediaType === 'video_note'}
          onChange={(event) => {
            if (mediaType) {
              replaceMessage({ caption: event.target.value, text: event.target.value })
              return
            }
            onSnippetSelected(null)
            replaceMessage({ type: 'text', text: event.target.value })
          }}
          placeholder={
            mediaType === 'video_note'
              ? 'Telegram не поддерживает caption для video_note.'
              : 'Напишите сообщение для рассылки...'
          }
          className="w-full resize-none rounded-xl border border-white/10 bg-background/70 px-4 py-3 text-sm leading-6 text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div className="mt-3">
        <VariablePicker
            onInsert={(value) => {
              if (mediaType) {
                replaceMessage({ caption: `${captionText}${captionText ? ' ' : ''}${value}` })
                return
              }
              onSnippetSelected(null)
              replaceMessage({ type: 'text', text: `${captionText}${captionText ? ' ' : ''}${value}` })
            }}
          />
        </div>
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <h2 className="text-sm font-semibold text-white">Файл</h2>
        <p className="mt-1 text-xs text-gray-500">Выберите нативный способ отправки в Telegram.</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-[180px_minmax(0,1fr)]">
          <select
            value={uploadMode}
            onChange={(event) => setUploadMode(event.target.value as BroadcastMediaType)}
            className="h-10 rounded-xl border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none"
          >
            {mediaModes.map((mode) => (
              <option key={mode.type} value={mode.type}>{mode.label}</option>
            ))}
          </select>
          <input
            ref={fileInputRef}
            type="file"
            accept={mediaModes.find((mode) => mode.type === uploadMode)?.accept}
            className="hidden"
            onChange={(event) => void uploadFile(event.target.files?.[0])}
          />
          <button
            type="button"
            disabled={isUploading}
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-xl border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:opacity-50"
          >
            {isUploading ? <LoaderCircle size={16} className="animate-spin" /> : <Paperclip size={16} />}
            Загрузить и прикрепить
          </button>
        </div>
        {uploadError ? <p className="mt-2 text-sm text-red-200">{uploadError}</p> : null}
      </section>

      <section className="rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <h2 className="text-sm font-semibold text-white">Кнопки под сообщением</h2>
        <div className="mt-3">
          <BroadcastButtonListEditor
            buttons={message.buttons ?? []}
            funnels={availableFunnels}
            onChange={(buttons) => replaceMessage({ buttons })}
          />
        </div>
      </section>
    </div>
  )
}

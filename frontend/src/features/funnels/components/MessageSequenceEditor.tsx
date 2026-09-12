import {
  ArrowDown,
  ArrowUp,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Mic,
  Paperclip,
  PlayCircle,
  Plus,
  Trash2,
  Video,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { BroadcastMediaType } from '../../broadcasts/types'
import { fetchFunnelMediaBlob, uploadFunnelMedia } from '../api'
import type { FunnelStep } from '../types'
import {
  configId,
  type FunnelMessageMediaType,
  type MessageMediaConfig,
  type MessageConfig,
} from '../funnelConfig'
import ButtonListEditor from './ButtonListEditor'

type MessageSequenceEditorProps = {
  messages: MessageConfig[]
  currentStepId: string
  projectId: string
  steps: FunnelStep[]
  onChange: (messages: MessageConfig[]) => void
}

const MAX_CHAT_ACTION_DURATION_SECONDS = 60

const mediaModes: Array<{
  type: FunnelMessageMediaType
  label: string
  accept: string
}> = [
  { type: 'document', label: 'Документ', accept: '*/*' },
  { type: 'photo', label: 'Фото', accept: 'image/jpeg,image/png,image/webp' },
  { type: 'video', label: 'Видео', accept: 'video/mp4,video/quicktime,video/webm' },
  { type: 'voice', label: 'Голосовое', accept: 'audio/ogg,audio/mpeg,audio/mp4,audio/webm,audio/wav' },
  { type: 'video_note', label: 'Кружок', accept: 'video/mp4,video/quicktime,video/webm' },
]

function isMediaType(value: string): value is FunnelMessageMediaType {
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
  if (type === 'photo') return <ImageIcon size={16} />
  if (type === 'video') return <Video size={16} />
  if (type === 'voice') return <Mic size={16} />
  if (type === 'video_note') return <PlayCircle size={16} />
  return <FileText size={16} />
}

function chatActionLabel(type: string) {
  if (type === 'voice') return 'Показывать «записывает голосовое…»'
  if (type === 'video_note') return 'Показывать «записывает видеосообщение…»'
  if (type === 'photo') return 'Показывать «отправляет фото…»'
  if (type === 'video') return 'Показывать «отправляет видео…»'
  if (type === 'document') return 'Показывать «отправляет файл…»'
  return 'Показывать «печатает…»'
}

function formatBytes(value?: number) {
  if (!value) return null
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} КБ`
  return `${(value / 1024 / 1024).toFixed(1)} МБ`
}

function UploadedPhotoPreview({
  projectId,
  media,
}: {
  projectId: string
  media?: MessageMediaConfig
}) {
  const [previewUrl, setPreviewUrl] = useState('')
  const [hasError, setHasError] = useState(false)
  const uploadId = media?.source === 'upload' ? media.upload_id : undefined
  const isPhoto = media?.media_type === 'photo'

  useEffect(() => {
    if (!uploadId || !isPhoto) {
      setPreviewUrl('')
      setHasError(false)
      return undefined
    }

    let isMounted = true
    let objectUrl = ''
    setPreviewUrl('')
    setHasError(false)

    void fetchFunnelMediaBlob(projectId, uploadId)
      .then((blob) => {
        if (!isMounted) return
        objectUrl = URL.createObjectURL(blob)
        setPreviewUrl(objectUrl)
      })
      .catch(() => {
        if (isMounted) {
          setHasError(true)
        }
      })

    return () => {
      isMounted = false
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [isPhoto, projectId, uploadId])

  if (!uploadId || !isPhoto) {
    return null
  }

  if (hasError) {
    return (
      <div className="mt-3 rounded-lg border border-amber-300/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
        Превью недоступно, но файл сохранён в шаге.
      </div>
    )
  }

  return (
    <button
      type="button"
      disabled={!previewUrl}
      onClick={() => {
        if (previewUrl) {
          window.open(previewUrl, '_blank', 'noopener,noreferrer')
        }
      }}
      className="mt-3 block w-full overflow-hidden rounded-xl border border-white/10 bg-black/20 text-left transition hover:border-accent-300/35 disabled:cursor-wait"
      title="Открыть фото"
    >
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={media.file_name || 'Превью фото'}
          className="max-h-48 w-full object-contain"
        />
      ) : (
        <div className="flex h-28 items-center justify-center text-xs text-gray-500">
          Загружаю превью...
        </div>
      )}
    </button>
  )
}

export default function MessageSequenceEditor({
  messages,
  currentStepId,
  projectId,
  steps,
  onChange,
}: MessageSequenceEditorProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [uploadTarget, setUploadTarget] = useState<{
    index: number
    mediaType: FunnelMessageMediaType
  } | null>(null)
  const [uploadingIndex, setUploadingIndex] = useState<number | null>(null)
  const [uploadError, setUploadError] = useState('')

  const move = (from: number, to: number) => {
    const next = [...messages]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    onChange(next)
  }

  const update = (index: number, patch: Partial<MessageConfig>) => {
    onChange(messages.map((message, idx) => (idx === index ? { ...message, ...patch } : message)))
  }

  const setType = (index: number, type: 'text' | FunnelMessageMediaType) => {
    const message = messages[index]
    if (!message) return
    const caption = message.caption ?? message.text
    if (type === 'text') {
      update(index, {
        type: 'text',
        text: caption,
        caption: undefined,
        media: undefined,
      })
      return
    }
    update(index, {
      type,
      text: caption,
      caption,
      media: message.media?.media_type === type ? message.media : undefined,
    })
  }

  const openUpload = (index: number, mediaType: FunnelMessageMediaType) => {
    setUploadError('')
    setUploadTarget({ index, mediaType })
    if (fileInputRef.current) {
      fileInputRef.current.accept =
        mediaModes.find((mode) => mode.type === mediaType)?.accept ?? '*/*'
      fileInputRef.current.click()
    }
  }

  const uploadFile = async (file: File | null | undefined) => {
    if (!file || !uploadTarget) return
    const target = uploadTarget
    const message = messages[target.index]
    if (!message) return

    setUploadingIndex(target.index)
    setUploadError('')
    try {
      const upload = await uploadFunnelMedia(
        projectId,
        file,
        target.mediaType as BroadcastMediaType,
      )
      const caption = upload.media_type === 'video_note'
        ? ''
        : message.caption ?? message.text
      update(target.index, {
        type: upload.media_type,
        text: caption,
        caption,
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
      setUploadError('Не удалось загрузить файл.')
    } finally {
      setUploadingIndex(null)
      setUploadTarget(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Sequence</p>
          <p className="text-xs text-gray-600">Несколько сообщений внутри одного блока.</p>
        </div>
        <button
          type="button"
          onClick={() =>
            onChange([
              ...messages,
              {
                id: configId('msg'),
                type: 'text',
                text: '',
                delay_seconds: 0,
                chat_action_enabled: false,
                chat_action_duration_seconds: 3,
                wait_for_answer: false,
                continue_after_buttons: false,
                button_mode: 'inline',
                buttons: [],
              },
            ])
          }
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 px-2 text-xs text-gray-100 transition hover:border-accent-300/35"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={(event) => void uploadFile(event.target.files?.[0])}
      />

      {uploadError ? (
        <p className="rounded-lg border border-red-300/20 bg-red-500/10 px-3 py-2 text-sm text-red-100">
          {uploadError}
        </p>
      ) : null}

      {messages.map((message, index) => {
        const mediaType: FunnelMessageMediaType | null = isMediaType(message.type)
          ? message.type
          : null
        const isMedia = mediaType !== null
        const captionText = isMedia ? message.caption ?? message.text : message.text
        const fileSize = formatBytes(message.media?.file_size)
        return (
          <div key={message.id} className="rounded-xl border border-white/8 bg-white/[0.03] p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-gray-300">Сообщение {index + 1}</span>
              <div className="flex gap-1">
                <button
                  type="button"
                  disabled={index === 0}
                  onClick={() => move(index, index - 1)}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                  title="Вверх"
                >
                  <ArrowUp size={13} />
                </button>
                <button
                  type="button"
                  disabled={index === messages.length - 1}
                  onClick={() => move(index, index + 1)}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 text-gray-300 disabled:opacity-40"
                  title="Вниз"
                >
                  <ArrowDown size={13} />
                </button>
                <button
                  type="button"
                  disabled={messages.length === 1}
                  onClick={() => onChange(messages.filter((_, idx) => idx !== index))}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-red-300/15 text-red-200 disabled:opacity-40"
                  title="Удалить"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </div>

            <label className="block">
              <span className="mb-1 block text-xs text-gray-500">Тип сообщения</span>
              <select
                value={isMedia ? message.type : 'text'}
                onChange={(event) =>
                  setType(index, event.target.value as 'text' | FunnelMessageMediaType)
                }
                className="h-10 w-full rounded-lg border border-white/10 bg-background/70 px-2 text-sm text-gray-100 outline-none"
              >
                <option value="text">Текст</option>
                {mediaModes.map((mode) => (
                  <option key={mode.type} value={mode.type}>{mode.label}</option>
                ))}
              </select>
            </label>

            {isMedia ? (
              <div className="mt-3 rounded-xl border border-white/10 bg-background/55 p-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-400/15 text-accent-100">
                    {mediaIcon(message.type)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-white">{mediaLabel(message.type)}</p>
                    <p className="truncate text-xs text-gray-500">
                      {message.media?.file_name || 'Файл не прикреплён'}
                      {fileSize ? ` · ${fileSize}` : ''}
                    </p>
                  </div>
                  {message.media ? (
                    <button
                      type="button"
                      onClick={() => update(index, { media: undefined })}
                      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-red-300/35 hover:text-red-100"
                      title="Убрать файл"
                    >
                      <X size={15} />
                    </button>
                  ) : null}
                </div>
                <UploadedPhotoPreview projectId={projectId} media={message.media} />
                <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <input
                    value={
                      message.media?.source === 'telegram_file_id'
                        ? message.media.telegram_file_id ?? ''
                        : ''
                    }
                    onChange={(event) =>
                      update(index, {
                        media: event.target.value.trim()
                          ? {
                              source: 'telegram_file_id',
                              telegram_file_id: event.target.value.trim(),
                              file_name: message.media?.file_name,
                              media_type: mediaType ?? undefined,
                            }
                          : undefined,
                      })
                    }
                    placeholder="Telegram file_id"
                    className="h-10 min-w-0 rounded-lg border border-white/10 bg-background/70 px-3 text-sm text-gray-100 outline-none placeholder:text-gray-600"
                  />
                  <button
                    type="button"
                    onClick={() => mediaType ? openUpload(index, mediaType) : undefined}
                    disabled={uploadingIndex === index}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-white/10 px-3 text-sm text-gray-100 transition hover:border-accent-300/35 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {uploadingIndex === index ? (
                      <LoaderCircle size={15} className="animate-spin" />
                    ) : (
                      <Paperclip size={15} />
                    )}
                    Прикрепить
                  </button>
                </div>
              </div>
            ) : null}

            <textarea
              rows={isMedia ? 3 : 4}
              value={captionText}
              disabled={message.type === 'video_note'}
              onChange={(event) => {
                if (isMedia) {
                  update(index, {
                    text: event.target.value,
                    caption: event.target.value,
                  })
                  return
                }
                update(index, { text: event.target.value })
              }}
              placeholder={
                message.type === 'video_note'
                  ? 'Telegram не поддерживает caption для video_note.'
                  : isMedia
                    ? 'Caption к вложению'
                    : 'Текст сообщения'
              }
              className="mt-3 w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none disabled:cursor-not-allowed disabled:opacity-60"
            />

            <label className="mt-3 flex items-start gap-3 rounded-lg border border-white/8 bg-background/45 px-3 py-2">
              <input
                type="checkbox"
                checked={message.wait_for_answer === true}
                onChange={(event) => update(index, {
                  wait_for_answer: event.target.checked,
                  ...(event.target.checked ? { continue_after_buttons: false } : {}),
                })}
                className="mt-1 h-4 w-4 rounded border-white/20 bg-background text-accent-300"
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-gray-100">
                  Ждать ответ после этого сообщения
                </span>
                <span className="mt-0.5 block text-xs leading-5 text-gray-500">
                  После ответа лида сценарий продолжится по выходу «Далее».
                </span>
              </span>
            </label>

            <label className="mt-2 block">
              <span className="mb-1 block text-xs text-gray-500">Задержка перед сообщением, сек</span>
              <input
                type="number"
                min={0}
                value={message.delay_seconds}
                onChange={(event) => update(index, { delay_seconds: Number(event.target.value) || 0 })}
                className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
              />
            </label>

            <div className="mt-2 rounded-lg border border-white/8 bg-background/45 px-3 py-2">
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  checked={message.chat_action_enabled}
                  onChange={(event) => update(index, { chat_action_enabled: event.target.checked })}
                  className="h-4 w-4 shrink-0 rounded border-white/20 bg-background text-accent-300"
                />
                <span className="min-w-0 text-sm font-medium text-gray-100">
                  {chatActionLabel(message.type)}
                </span>
              </label>
              {message.chat_action_enabled ? (
                <label className="mt-3 block">
                  <span className="mb-1 block text-xs text-gray-500">Длительность индикатора, сек</span>
                  <input
                    type="number"
                    min={1}
                    max={MAX_CHAT_ACTION_DURATION_SECONDS}
                    value={message.chat_action_duration_seconds}
                    onChange={(event) => update(index, {
                      chat_action_duration_seconds: Math.min(
                        MAX_CHAT_ACTION_DURATION_SECONDS,
                        Math.max(1, Number(event.target.value) || 1),
                      ),
                    })}
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-base text-gray-100 outline-none md:text-sm"
                  />
                </label>
              ) : null}
            </div>

            <div className="mt-3">
              <ButtonListEditor
                buttons={message.buttons}
                buttonMode={message.button_mode}
                onButtonModeChange={(buttonMode) => update(index, { button_mode: buttonMode })}
                currentStepId={currentStepId}
                steps={steps}
                onChange={(buttons) => update(index, {
                  buttons,
                  ...(buttons.some((button) => button.type !== 'url')
                    ? { continue_after_buttons: false }
                    : {}),
                })}
              />
            </div>

            {message.buttons.length > 0 ? (
              <label className="mt-3 flex items-start gap-3 rounded-lg border border-white/8 bg-background/45 px-3 py-2">
                <input
                  type="checkbox"
                  checked={message.continue_after_buttons === true}
                  disabled={message.buttons.some((button) => button.type !== 'url')}
                  onChange={(event) => update(index, {
                    continue_after_buttons: event.target.checked,
                    ...(event.target.checked ? { wait_for_answer: false } : {}),
                  })}
                  className="mt-1 h-4 w-4 rounded border-white/20 bg-background text-accent-300 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-gray-100">
                    Продолжить воронку после отправки
                  </span>
                  <span className="mt-0.5 block text-xs leading-5 text-gray-500">
                    {message.buttons.some((button) => button.type !== 'url')
                      ? 'Доступно только для URL-кнопок. Ветки и запрос контакта должны дождаться действия лида.'
                      : message.continue_after_buttons === true
                        ? 'Ссылка останется в сообщении, а сценарий сразу перейдёт дальше.'
                        : 'Без этого флажка сценарий остановится на сообщении. Нажатие URL-кнопки Telegram не передаёт в воронку.'}
                  </span>
                </span>
              </label>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

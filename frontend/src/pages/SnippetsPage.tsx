import axios from 'axios'
import {
  ArrowLeft,
  AlertTriangle,
  CheckCircle2,
  Copy,
  File as FileIcon,
  FileText,
  Image,
  Library,
  LoaderCircle,
  Mic2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  Video,
} from 'lucide-react'
import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from 'react'

import {
  createMediaSnippet,
  createTextSnippet,
  deleteSnippet,
  fetchProjectSnippets,
  fetchSnippetMedia,
  replaceMediaSnippet,
  TELEGRAM_CAPTION_LIMIT,
  TELEGRAM_TEXT_LIMIT,
  updateSnippet,
  type ProjectSnippet,
  type SnippetMediaType,
  type SnippetType,
} from '../features/snippets'
import { useNotificationStore, useProjectBotSelection } from '../shared/lib'
import { ConfirmDialog, EmptyState, Modal } from '../shared/ui'
import { useAuthStore } from '../store/authStore'

type TypeFilter = 'all' | SnippetType
type EditorMode = 'create' | 'edit'

type SnippetDraft = {
  name: string
  type: SnippetType
  content: string
  file: File | null
}

const mediaTypeOptions: Array<{
  type: SnippetMediaType
  label: string
  accept: string
}> = [
  { type: 'photo', label: 'Фото', accept: 'image/*' },
  { type: 'video', label: 'Видео', accept: 'video/*' },
  { type: 'voice', label: 'Голосовое', accept: 'audio/*' },
  { type: 'video_note', label: 'Кружок', accept: 'video/*' },
  { type: 'document', label: 'Документ', accept: '*/*' },
]

const typeLabels: Record<SnippetType, string> = {
  text: 'Текст',
  photo: 'Фото',
  video: 'Видео',
  voice: 'Голосовое',
  video_note: 'Кружок',
  document: 'Документ',
}

const filterOptions: Array<{ value: TypeFilter; label: string }> = [
  { value: 'all', label: 'Все' },
  { value: 'text', label: 'Текст' },
  ...mediaTypeOptions.map((item) => ({ value: item.type, label: item.label })),
]

const fieldClass =
  'w-full rounded-lg border border-white/10 bg-background/80 px-3 py-2.5 text-base text-gray-100 outline-none ring-cyan-400/50 transition placeholder:text-gray-600 focus:ring-2 md:text-sm'

function emptyDraft(): SnippetDraft {
  return { name: '', type: 'text', content: '', file: null }
}

function getErrorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
        .filter(Boolean)
      if (messages.length > 0) return messages.join(' ')
    }
    if (error.code === 'ERR_NETWORK') return 'API недоступен.'
  }
  return fallback
}

function iconForType(type: SnippetType, size = 18) {
  if (type === 'photo') return <Image size={size} />
  if (type === 'video' || type === 'video_note') return <Video size={size} />
  if (type === 'voice') return <Mic2 size={size} />
  if (type === 'document') return <FileIcon size={size} />
  return <FileText size={size} />
}

function formatFileSize(size: number | null) {
  if (!size || size <= 0) return 'Размер не указан'
  if (size < 1024) return `${size} Б`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} КБ`
  return `${(size / 1024 / 1024).toFixed(1)} МБ`
}

function formatCreatedAt(value: string) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value))
}

function contentLimit(type: SnippetType) {
  return type === 'text' ? TELEGRAM_TEXT_LIMIT : TELEGRAM_CAPTION_LIMIT
}

function summary(snippet: ProjectSnippet) {
  return snippet.content?.trim() || snippet.file_name || 'Без подписи'
}

function MediaPreview({
  snippet,
  mediaUrl,
  isLoading,
  error,
}: {
  snippet: ProjectSnippet
  mediaUrl: string | null
  isLoading: boolean
  error: string | null
}) {
  if (isLoading) {
    return (
      <div className="grid min-h-48 place-items-center text-gray-500">
        <LoaderCircle size={24} className="animate-spin" />
      </div>
    )
  }
  if (error || !mediaUrl) {
    return (
      <div className="grid min-h-40 place-items-center px-5 text-center text-sm text-amber-200">
        {error || 'Для этой заготовки нет локального предпросмотра.'}
      </div>
    )
  }
  if (snippet.type === 'photo') {
    return <img src={mediaUrl} alt="" className="max-h-[420px] w-full object-contain" />
  }
  if (snippet.type === 'video' || snippet.type === 'video_note') {
    return (
      <video
        src={mediaUrl}
        controls
        playsInline
        className={snippet.type === 'video_note'
          ? 'mx-auto aspect-square max-h-[360px] w-full max-w-[360px] rounded-full object-cover'
          : 'max-h-[420px] w-full bg-black object-contain'}
      />
    )
  }
  if (snippet.type === 'voice') {
    return (
      <div className="p-4">
        <audio src={mediaUrl} controls className="w-full" />
      </div>
    )
  }
  return (
    <div className="flex min-h-32 items-center gap-3 p-4">
      <div className="grid h-12 w-12 shrink-0 place-items-center rounded-lg bg-cyan-400/10 text-cyan-200">
        <FileIcon size={22} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-white">{snippet.file_name || 'Документ'}</p>
        <p className="mt-1 text-xs text-gray-500">{formatFileSize(snippet.file_size)}</p>
      </div>
      <a
        href={mediaUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex h-10 shrink-0 items-center justify-center rounded-lg border border-white/10 px-3 text-sm font-medium text-gray-200 transition hover:border-cyan-300/40 hover:text-white"
      >
        Открыть
      </a>
    </div>
  )
}

export default function SnippetsPage() {
  const { selectedProjectId } = useProjectBotSelection()
  const user = useAuthStore((state) => state.user)
  const notify = useNotificationStore((state) => state.notify)
  const canManage = ['manager', 'admin', 'super_admin'].includes(user?.role_name ?? '')
  const canDelete = ['admin', 'super_admin'].includes(user?.role_name ?? '')

  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])
  const [selectedSnippetId, setSelectedSnippetId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [isLoading, setIsLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [isMobileDetailOpen, setIsMobileDetailOpen] = useState(false)

  const [editorMode, setEditorMode] = useState<EditorMode | null>(null)
  const [editingSnippet, setEditingSnippet] = useState<ProjectSnippet | null>(null)
  const [draft, setDraft] = useState<SnippetDraft>(emptyDraft)
  const [isSaving, setIsSaving] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<ProjectSnippet | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const [mediaUrl, setMediaUrl] = useState<string | null>(null)
  const [mediaError, setMediaError] = useState<string | null>(null)
  const [isMediaLoading, setIsMediaLoading] = useState(false)

  useEffect(() => {
    if (!selectedProjectId) {
      setSnippets([])
      setSelectedSnippetId(null)
      setLoadError(null)
      return
    }
    const controller = new AbortController()
    setSnippets([])
    setSelectedSnippetId(null)
    setIsMobileDetailOpen(false)
    setIsLoading(true)
    setLoadError(null)
    void fetchProjectSnippets(selectedProjectId, controller.signal)
      .then((items) => {
        setSnippets(items)
        setSelectedSnippetId((current) =>
          current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null,
        )
      })
      .catch((error) => {
        if (axios.isCancel(error)) return
        setSnippets([])
        setSelectedSnippetId(null)
        setLoadError(getErrorMessage(error, 'Не удалось загрузить заготовки.'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false)
      })
    return () => controller.abort()
  }, [reloadKey, selectedProjectId])

  const selectedSnippet = useMemo(
    () => snippets.find((item) => item.id === selectedSnippetId) ?? null,
    [selectedSnippetId, snippets],
  )

  useEffect(() => {
    setMediaUrl(null)
    setMediaError(null)
    setIsMediaLoading(false)
    if (!selectedProjectId || !selectedSnippet || selectedSnippet.type === 'text') return
    if (!selectedSnippet.preview_available) {
      setMediaError('Заготовка хранится как Telegram file_id и не имеет локального предпросмотра.')
      return
    }
    const controller = new AbortController()
    let objectUrl: string | null = null
    setIsMediaLoading(true)
    void fetchSnippetMedia(selectedProjectId, selectedSnippet.id, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        setMediaUrl(objectUrl)
      })
      .catch((error) => {
        if (axios.isCancel(error)) return
        setMediaError(getErrorMessage(error, 'Не удалось открыть файл заготовки.'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsMediaLoading(false)
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [selectedProjectId, selectedSnippet])

  const typeCounts = useMemo(() => {
    const counts = new Map<TypeFilter, number>([['all', snippets.length]])
    snippets.forEach((snippet) => counts.set(snippet.type, (counts.get(snippet.type) ?? 0) + 1))
    return counts
  }, [snippets])

  const filteredSnippets = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase('ru-RU')
    return snippets.filter((snippet) => {
      if (typeFilter !== 'all' && snippet.type !== typeFilter) return false
      if (!needle) return true
      return [snippet.name, snippet.content, snippet.file_name, typeLabels[snippet.type]]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase('ru-RU').includes(needle))
    })
  }, [search, snippets, typeFilter])

  const selectSnippet = (snippet: ProjectSnippet) => {
    setSelectedSnippetId(snippet.id)
    setIsMobileDetailOpen(true)
  }

  const openCreate = () => {
    setEditingSnippet(null)
    setDraft(emptyDraft())
    setEditorMode('create')
  }

  const openEdit = (snippet: ProjectSnippet) => {
    setEditingSnippet(snippet)
    setDraft({
      name: snippet.name,
      type: snippet.type,
      content: snippet.content ?? '',
      file: null,
    })
    setEditorMode('edit')
  }

  const closeEditor = () => {
    if (isSaving) return
    setEditorMode(null)
    setEditingSnippet(null)
    setDraft(emptyDraft())
  }

  const saveSnippet = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedProjectId || !editorMode || isSaving) return
    const name = draft.name.trim()
    const content = draft.content.trim()
    if (!name) {
      notify({ tone: 'error', message: 'Укажите название заготовки.' })
      return
    }
    if (draft.type === 'text' && !content) {
      notify({ tone: 'error', message: 'Укажите текст заготовки.' })
      return
    }
    const limit = contentLimit(draft.type)
    if (content.length > limit) {
      notify({ tone: 'error', message: `Превышен лимит Telegram: ${limit} символов.` })
      return
    }
    if (editorMode === 'create' && draft.type !== 'text' && !draft.file) {
      notify({ tone: 'error', message: 'Выберите файл заготовки.' })
      return
    }
    if (
      editorMode === 'edit' &&
      editingSnippet &&
      editingSnippet.type !== draft.type &&
      !draft.file
    ) {
      notify({ tone: 'error', message: 'При смене типа медиа нужно выбрать новый файл.' })
      return
    }

    setIsSaving(true)
    try {
      let saved: ProjectSnippet
      if (editorMode === 'create') {
        saved = draft.type === 'text'
          ? await createTextSnippet(selectedProjectId, { name, content })
          : await createMediaSnippet(selectedProjectId, {
              name,
              type: draft.type,
              content: content || null,
              file: draft.file as File,
            })
      } else {
        if (!editingSnippet) return
        if (editingSnippet.type === 'text') {
          saved = await updateSnippet(selectedProjectId, editingSnippet.id, { name, content })
        } else if (draft.file) {
          saved = await replaceMediaSnippet(selectedProjectId, editingSnippet.id, {
            name,
            type: draft.type as SnippetMediaType,
            content: content || null,
            file: draft.file,
          })
        } else {
          saved = await updateSnippet(selectedProjectId, editingSnippet.id, {
            name,
            content: content || null,
          })
        }
      }
      setSnippets((current) => {
        const withoutSaved = current.filter((item) => item.id !== saved.id)
        return editorMode === 'create' ? [saved, ...withoutSaved] : current.map((item) => item.id === saved.id ? saved : item)
      })
      setSelectedSnippetId(saved.id)
      setIsMobileDetailOpen(true)
      notify({ tone: 'success', message: editorMode === 'create' ? 'Заготовка создана.' : 'Заготовка обновлена.' })
      setEditorMode(null)
      setEditingSnippet(null)
      setDraft(emptyDraft())
    } catch (error) {
      notify({ tone: 'error', message: getErrorMessage(error, 'Не удалось сохранить заготовку.') })
    } finally {
      setIsSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!selectedProjectId || !pendingDelete || !canDelete || isDeleting) return
    const snippetId = pendingDelete.id
    setIsDeleting(true)
    try {
      await deleteSnippet(selectedProjectId, snippetId)
      setSnippets((current) => {
        const remaining = current.filter((item) => item.id !== snippetId)
        setSelectedSnippetId((selected) => selected === snippetId ? remaining[0]?.id ?? null : selected)
        return remaining
      })
      setPendingDelete(null)
      setIsMobileDetailOpen(false)
      notify({ tone: 'success', message: 'Заготовка удалена.' })
    } catch (error) {
      notify({ tone: 'error', message: getErrorMessage(error, 'Не удалось удалить заготовку.') })
    } finally {
      setIsDeleting(false)
    }
  }

  const copyContent = async (snippet: ProjectSnippet) => {
    if (!snippet.content) return
    try {
      await navigator.clipboard.writeText(snippet.content)
      notify({ tone: 'success', message: 'Текст скопирован.' })
    } catch {
      notify({ tone: 'error', message: 'Не удалось скопировать текст.' })
    }
  }

  return (
    <section className="flex h-full min-h-[calc(100dvh-7rem)] min-w-0 flex-col overflow-hidden rounded-lg border border-white/10 bg-[#0d1220]/95 md:min-h-0">
      <header className="flex shrink-0 flex-col gap-3 border-b border-white/10 px-4 py-4 md:flex-row md:items-center md:justify-between md:px-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300">
            <Library size={15} />
            Сообщения
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-white">Заготовки</h1>
          <p className="mt-1 text-sm text-gray-500">Быстрые ответы и медиа выбранного проекта</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            disabled={!selectedProjectId || isLoading}
            title="Обновить"
            aria-label="Обновить заготовки"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-cyan-300/40 hover:text-white disabled:opacity-50"
          >
            <RefreshCw size={17} className={isLoading ? 'animate-spin' : ''} />
          </button>
          {canManage ? (
            <button
              type="button"
              onClick={openCreate}
              disabled={!selectedProjectId}
              className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-[#071018] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50 md:flex-none"
            >
              <Plus size={17} />
              Новая заготовка
            </button>
          ) : null}
        </div>
      </header>

      {!selectedProjectId ? (
        <div className="p-4 md:p-6">
          <EmptyState title="Проект не выбран" description="Выберите проект в верхней панели." icon={<Library size={24} />} />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.2fr)]">
          <div className={`${isMobileDetailOpen ? 'hidden md:flex' : 'flex'} min-h-0 min-w-0 flex-col border-r-0 border-white/10 md:border-r`}>
            <div className="shrink-0 space-y-3 border-b border-white/10 p-3 md:p-4">
              <label className="relative block">
                <Search size={17} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Поиск по названию и тексту"
                  className={`${fieldClass} pl-10`}
                />
              </label>
              <div className="touch-scroll flex gap-2 overflow-x-auto pb-1">
                {filterOptions.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setTypeFilter(option.value)}
                    className={`inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition ${
                      typeFilter === option.value
                        ? 'border-cyan-300/50 bg-cyan-400/15 text-cyan-100'
                        : 'border-white/10 bg-white/[0.02] text-gray-400 hover:text-white'
                    }`}
                  >
                    {option.label}
                    <span className="text-xs opacity-70">{typeCounts.get(option.value) ?? 0}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="touch-scroll min-h-0 flex-1 overflow-y-auto p-2 md:p-3">
              {isLoading ? (
                <div className="grid min-h-48 place-items-center text-gray-500"><LoaderCircle className="animate-spin" /></div>
              ) : loadError ? (
                <EmptyState title="Заготовки недоступны" description={loadError} icon={<FileText size={24} />} />
              ) : filteredSnippets.length === 0 ? (
                <EmptyState
                  title={snippets.length === 0 ? 'Заготовок пока нет' : 'Ничего не найдено'}
                  description={snippets.length === 0 ? 'Создайте первую заготовку для проекта.' : 'Измените поиск или фильтр.'}
                  icon={<FileText size={24} />}
                />
              ) : (
                <div className="space-y-2">
                  {filteredSnippets.map((snippet) => (
                    <button
                      key={snippet.id}
                      type="button"
                      onClick={() => selectSnippet(snippet)}
                      className={`flex w-full min-w-0 items-start gap-3 rounded-lg border p-3 text-left transition ${
                        selectedSnippetId === snippet.id
                          ? 'border-cyan-300/45 bg-cyan-400/10'
                          : 'border-white/8 bg-white/[0.025] hover:border-white/15 hover:bg-white/[0.04]'
                      }`}
                    >
                      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-white/[0.05] text-cyan-200">
                        {iconForType(snippet.type)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex min-w-0 items-center justify-between gap-2">
                          <span className="truncate text-sm font-semibold text-white">{snippet.name}</span>
                          <span className="shrink-0 text-[11px] text-gray-600">{formatCreatedAt(snippet.created_at)}</span>
                        </span>
                        <span className="mt-1 block truncate text-sm text-gray-400">{summary(snippet)}</span>
                        <span className="mt-2 inline-flex items-center rounded-md bg-white/[0.05] px-2 py-0.5 text-[11px] font-medium text-gray-400">
                          {typeLabels[snippet.type]}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className={`${isMobileDetailOpen ? 'flex' : 'hidden md:flex'} min-h-0 min-w-0 flex-col`}>
            {selectedSnippet ? (
              <>
                <div className="flex shrink-0 items-center gap-2 border-b border-white/10 px-3 py-3 md:px-5">
                  <button
                    type="button"
                    onClick={() => setIsMobileDetailOpen(false)}
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 md:hidden"
                    aria-label="К списку заготовок"
                  >
                    <ArrowLeft size={18} />
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-base font-semibold text-white">{selectedSnippet.name}</p>
                    <p className="text-xs text-gray-500">{typeLabels[selectedSnippet.type]}</p>
                  </div>
                  {selectedSnippet.content ? (
                    <button
                      type="button"
                      onClick={() => void copyContent(selectedSnippet)}
                      title="Скопировать текст"
                      aria-label="Скопировать текст"
                      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-cyan-300/40 hover:text-white"
                    >
                      <Copy size={16} />
                    </button>
                  ) : null}
                  {canManage ? (
                    <button
                      type="button"
                      onClick={() => openEdit(selectedSnippet)}
                      title="Редактировать"
                      aria-label="Редактировать заготовку"
                      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-white/10 text-gray-300 transition hover:border-cyan-300/40 hover:text-white"
                    >
                      <Pencil size={16} />
                    </button>
                  ) : null}
                  {canDelete ? (
                    <button
                      type="button"
                      onClick={() => setPendingDelete(selectedSnippet)}
                      title="Удалить"
                      aria-label="Удалить заготовку"
                      className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-red-400/20 text-red-300 transition hover:bg-red-500/10"
                    >
                      <Trash2 size={16} />
                    </button>
                  ) : null}
                </div>

                <div className="touch-scroll min-h-0 flex-1 overflow-y-auto">
                  <div className="grid min-h-full grid-rows-[minmax(320px,1fr)_auto]">
                    <div className="grid place-items-center bg-[#090d16] p-4 md:p-7">
                      <div className="w-full max-w-[560px]">
                        <div className="ml-auto max-w-[88%] overflow-hidden rounded-lg border border-cyan-300/25 bg-[#102c39] shadow-card">
                          {selectedSnippet.type !== 'text' ? (
                            <MediaPreview
                              snippet={selectedSnippet}
                              mediaUrl={mediaUrl}
                              isLoading={isMediaLoading}
                              error={mediaError}
                            />
                          ) : null}
                          {selectedSnippet.content ? (
                            <p className="whitespace-pre-wrap break-words px-4 py-3 text-[15px] leading-6 text-gray-100">
                              {selectedSnippet.content}
                            </p>
                          ) : null}
                          <div className="px-4 pb-2 text-right text-[11px] text-cyan-100/45">предпросмотр</div>
                        </div>
                      </div>
                    </div>

                    <div className="border-t border-white/10 px-4 py-4 md:px-5">
                      <div className="grid gap-3 sm:grid-cols-3">
                        <div>
                          <p className="text-xs uppercase tracking-wide text-gray-600">Тип</p>
                          <p className="mt-1 text-sm font-medium text-gray-200">{typeLabels[selectedSnippet.type]}</p>
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs uppercase tracking-wide text-gray-600">Файл</p>
                          <p className="mt-1 truncate text-sm font-medium text-gray-200">
                            {selectedSnippet.file_name || (selectedSnippet.type === 'text' ? 'Не требуется' : 'Telegram file_id')}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs uppercase tracking-wide text-gray-600">Проверка</p>
                          <p className={`mt-1 inline-flex items-center gap-1.5 text-sm font-medium ${
                            selectedSnippet.content && selectedSnippet.content.length > contentLimit(selectedSnippet.type)
                              ? 'text-red-300'
                              : 'text-emerald-300'
                          }`}>
                            {selectedSnippet.content && selectedSnippet.content.length > contentLimit(selectedSnippet.type)
                              ? <AlertTriangle size={15} />
                              : <CheckCircle2 size={15} />}
                            {selectedSnippet.content && selectedSnippet.content.length > contentLimit(selectedSnippet.type) ? 'Превышен лимит' : 'Готово'}
                          </p>
                        </div>
                      </div>
                      <div className="mt-4 flex items-center justify-between border-t border-white/8 pt-3 text-xs text-gray-500">
                        <span>{selectedSnippet.file_size ? formatFileSize(selectedSnippet.file_size) : `${selectedSnippet.content?.length ?? 0} символов`}</span>
                        <span>{formatCreatedAt(selectedSnippet.created_at)}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="grid min-h-64 flex-1 place-items-center p-5">
                <EmptyState title="Выберите заготовку" icon={<Library size={24} />} />
              </div>
            )}
          </div>
        </div>
      )}

      {editorMode ? (
        <Modal
          title={editorMode === 'create' ? 'Новая заготовка' : 'Редактирование заготовки'}
          description={editorMode === 'create' ? 'Telegram · выбранный проект' : editingSnippet?.name}
          onClose={closeEditor}
          maxWidthClassName="max-w-2xl"
        >
          <form className="space-y-4" onSubmit={(event) => void saveSnippet(event)}>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-gray-200">Название</span>
                <input
                  autoFocus
                  value={draft.name}
                  onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                  maxLength={255}
                  placeholder="Например, Приветствие LATAM"
                  className={fieldClass}
                  disabled={isSaving}
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-gray-200">Тип</span>
                <select
                  value={draft.type}
                  onChange={(event) => setDraft((current) => ({
                    ...current,
                    type: event.target.value as SnippetType,
                    file: current.type === event.target.value ? current.file : null,
                  }))}
                  className={fieldClass}
                  disabled={isSaving || (editorMode === 'edit' && editingSnippet?.type === 'text')}
                >
                  {editorMode === 'create' || editingSnippet?.type === 'text' ? (
                    <option value="text">Текст</option>
                  ) : null}
                  {mediaTypeOptions.map((option) => (
                    <option key={option.type} value={option.type}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>

            <label className="block">
              <span className="mb-1.5 flex items-center justify-between gap-3 text-sm font-medium text-gray-200">
                <span>{draft.type === 'text' ? 'Текст' : 'Подпись'}</span>
                <span className={`text-xs ${draft.content.length > contentLimit(draft.type) ? 'text-red-300' : 'text-gray-600'}`}>
                  {draft.content.length}/{contentLimit(draft.type)}
                </span>
              </span>
              <textarea
                value={draft.content}
                onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))}
                rows={7}
                maxLength={contentLimit(draft.type) + 1}
                placeholder={draft.type === 'text' ? 'Текст быстрого ответа' : 'Необязательная подпись к медиа'}
                className={`${fieldClass} resize-y leading-6`}
                disabled={isSaving}
              />
            </label>

            {draft.type !== 'text' ? (
              <label className="block rounded-lg border border-dashed border-white/15 bg-white/[0.02] p-4">
                <span className="flex items-center gap-2 text-sm font-medium text-gray-200">
                  <Upload size={17} className="text-cyan-300" />
                  {editorMode === 'edit' ? 'Заменить файл' : 'Файл заготовки'}
                </span>
                <input
                  type="file"
                  accept={mediaTypeOptions.find((option) => option.type === draft.type)?.accept ?? '*/*'}
                  onChange={(event) => setDraft((current) => ({ ...current, file: event.target.files?.[0] ?? null }))}
                  className="mt-3 block w-full text-sm text-gray-400 file:mr-3 file:rounded-lg file:border-0 file:bg-cyan-400/15 file:px-3 file:py-2 file:font-medium file:text-cyan-100"
                  disabled={isSaving}
                />
                <span className="mt-2 block truncate text-xs text-gray-500">
                  {draft.file?.name || editingSnippet?.file_name || 'Файл не выбран'}
                </span>
              </label>
            ) : null}

            <div className="rounded-lg border border-white/10 bg-[#090d16] p-4">
              <p className="mb-3 text-xs font-semibold uppercase tracking-[0.15em] text-gray-600">Предпросмотр текста</p>
              <div className="ml-auto max-w-[88%] rounded-lg border border-cyan-300/20 bg-[#102c39] px-4 py-3">
                <p className="whitespace-pre-wrap break-words text-[15px] leading-6 text-gray-100">
                  {draft.content || (draft.type === 'text' ? 'Текст заготовки' : draft.file?.name || editingSnippet?.file_name || 'Медиа')}
                </p>
              </div>
            </div>

            <div className="flex flex-col-reverse gap-2 border-t border-white/10 pt-4 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={closeEditor}
                disabled={isSaving}
                className="h-11 rounded-lg border border-white/10 px-4 text-sm font-medium text-gray-300 transition hover:text-white disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isSaving || !draft.name.trim() || (draft.type === 'text' && !draft.content.trim())}
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-4 text-sm font-semibold text-[#071018] transition hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSaving ? <LoaderCircle size={17} className="animate-spin" /> : editorMode === 'create' ? <Plus size={17} /> : <Pencil size={17} />}
                {editorMode === 'create' ? 'Создать' : 'Сохранить'}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {pendingDelete ? (
        <ConfirmDialog
          title="Удалить заготовку?"
          description={`«${pendingDelete.name}» исчезнет у всех сотрудников проекта.`}
          confirmLabel="Удалить"
          tone="danger"
          isLoading={isDeleting}
          onCancel={() => {
            if (!isDeleting) setPendingDelete(null)
          }}
          onConfirm={() => void confirmDelete()}
        />
      ) : null}
    </section>
  )
}

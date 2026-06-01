import { LoaderCircle, Megaphone, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import api from '../api/client'
import { fetchBots, type Bot as BotRecord } from '../features/bots'
import {
  cancelBroadcast,
  createBroadcastTemplate,
  createBroadcast,
  fetchBroadcastReport,
  fetchBroadcasts,
  fetchBroadcastTemplates,
  fetchProjectSnippets,
  pauseBroadcast,
  resumeBroadcast,
  uploadBroadcastMedia,
} from '../features/broadcasts/api'
import BroadcastList from '../features/broadcasts/components/BroadcastList'
import BroadcastWizard from '../features/broadcasts/components/BroadcastWizard'
import type {
  Broadcast,
  BroadcastContent,
  BroadcastOption,
  BroadcastReport,
  BroadcastTemplate,
  BroadcastUpload,
  BroadcastMediaType,
  ProjectSnippet,
} from '../features/broadcasts/types'
import { fetchChatFilterPresets } from '../features/chats/api'
import type { ChatFilterPreset } from '../features/chats/types'
import { fetchFunnels } from '../features/funnels/api'
import { fetchLeadStatuses } from '../features/leads/api'
import { fetchTrackingLinks } from '../features/tracking/api'
import { useNotificationStore, useProjectBotSelection } from '../shared/lib'
import type { PaginatedResponse } from '../shared/types'

type ProjectTag = {
  id: string
  name: string
}

type UserOptionRecord = {
  id: string
  name: string | null
  email: string | null
}

function getErrorMessage(err: unknown, fallback = 'Не удалось выполнить запрос.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
        .filter(Boolean)
        .join(', ') || fallback
    }
  }
  return fallback
}

function botLabel(bot: BotRecord) {
  const username = bot.bot_username ? `@${bot.bot_username}` : null
  return [bot.name, username].filter(Boolean).join(' · ')
}

function duplicateName(name: string) {
  return name.trim() ? `${name.trim()} · копия` : 'Копия рассылки'
}

function contentHasMedia(content: BroadcastContent) {
  return content.messages.some((message) =>
    message.type === 'photo' ||
    message.type === 'video' ||
    message.type === 'voice' ||
    message.type === 'video_note' ||
    message.type === 'document',
  )
}

export default function BroadcastsPage() {
  const { selectedProjectId, selectedBotIds } = useProjectBotSelection()
  const notify = useNotificationStore((state) => state.notify)
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([])
  const [bots, setBots] = useState<BotRecord[]>([])
  const [tags, setTags] = useState<BroadcastOption[]>([])
  const [statuses, setStatuses] = useState<BroadcastOption[]>([])
  const [trackingLinks, setTrackingLinks] = useState<BroadcastOption[]>([])
  const [users, setUsers] = useState<BroadcastOption[]>([])
  const [funnels, setFunnels] = useState<BroadcastOption[]>([])
  const [templates, setTemplates] = useState<BroadcastTemplate[]>([])
  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])
  const [chatFilterPresets, setChatFilterPresets] = useState<ChatFilterPreset[]>([])
  const [reports, setReports] = useState<Record<string, BroadcastReport>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [isOptionsLoading, setIsOptionsLoading] = useState(false)
  const [editingBroadcast, setEditingBroadcast] = useState<Broadcast | null>(null)
  const [isWizardOpen, setIsWizardOpen] = useState(false)

  const botOptions = useMemo(
    () => bots.map((bot) => ({ id: bot.id, label: botLabel(bot) })),
    [bots],
  )
  const botLabelById = useMemo(
    () => new Map(botOptions.map((option) => [option.id, option.label])),
    [botOptions],
  )
  const defaultBotId = useMemo(() => {
    if (selectedBotIds.length === 1) return selectedBotIds[0]
    return botOptions[0]?.id ?? null
  }, [botOptions, selectedBotIds])

  const loadBroadcasts = useCallback(async () => {
    if (!selectedProjectId) {
      setBroadcasts([])
      return
    }
    setIsLoading(true)
    try {
      const items = await fetchBroadcasts(selectedProjectId)
      setBroadcasts(items)
      const reportEntries = await Promise.all(
        items.map(async (broadcast) => {
          try {
            return [broadcast.id, await fetchBroadcastReport(broadcast.id, selectedProjectId)] as const
          } catch {
            return [broadcast.id, null] as const
          }
        }),
      )
      setReports(
        Object.fromEntries(
          reportEntries.filter((entry): entry is readonly [string, BroadcastReport] => Boolean(entry[1])),
        ),
      )
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsLoading(false)
    }
  }, [notify, selectedProjectId])

  const loadOptions = useCallback(async () => {
    if (!selectedProjectId) {
      setBots([])
      setTags([])
      setStatuses([])
      setTrackingLinks([])
      setUsers([])
      setFunnels([])
      setTemplates([])
      setSnippets([])
      setChatFilterPresets([])
      return
    }
    setIsOptionsLoading(true)
    try {
      const [
        botItems,
        tagResponse,
        statusItems,
        trackingResponse,
        userResponse,
        funnelResponse,
        templateItems,
        snippetItems,
        presetItems,
      ] =
        await Promise.all([
          fetchBots(selectedProjectId),
          api.get<PaginatedResponse<ProjectTag>>('/tags', {
            params: { project_id: selectedProjectId, limit: 100, offset: 0 },
          }),
          fetchLeadStatuses(),
          fetchTrackingLinks({
            project_id: selectedProjectId,
            limit: 100,
            offset: 0,
            ...(selectedBotIds.length === 1 ? { bot_id: selectedBotIds[0] } : {}),
          }),
          api.get<PaginatedResponse<UserOptionRecord>>('/users', {
            params: { project_id: selectedProjectId, limit: 100, offset: 0 },
          }),
          fetchFunnels({
            projectId: selectedProjectId,
            status: 'active',
          }),
          fetchBroadcastTemplates(selectedProjectId),
          fetchProjectSnippets(selectedProjectId),
          fetchChatFilterPresets(selectedProjectId),
        ])
      setBots(botItems)
      setTags(tagResponse.data.items.map((tag) => ({ id: tag.id, label: tag.name })))
      setStatuses(statusItems.map((status) => ({ id: status.code, label: status.name })))
      setTrackingLinks(
        trackingResponse.items.map((link) => ({
          id: link.id,
          label: [link.title, link.code, link.buyer_name].filter(Boolean).join(' · '),
        })),
      )
      setUsers(
        userResponse.data.items.map((user) => ({
          id: user.id,
          label: user.name || user.email || 'Пользователь',
        })),
      )
      setFunnels(
        funnelResponse.items
          .filter((funnel) => funnel.published_version_id)
          .map((funnel) => ({
            id: funnel.id,
            label: funnel.name,
            meta: { versionId: funnel.published_version_id, botId: funnel.bot_id },
          })),
      )
      setTemplates(templateItems)
      setSnippets(snippetItems)
      setChatFilterPresets(presetItems)
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err, 'Не удалось загрузить справочники.') })
    } finally {
      setIsOptionsLoading(false)
    }
  }, [notify, selectedBotIds, selectedProjectId])

  useEffect(() => {
    void loadBroadcasts()
    void loadOptions()
  }, [loadBroadcasts, loadOptions])

  const handleSaved = (broadcast: Broadcast) => {
    setBroadcasts((items) => {
      const exists = items.some((item) => item.id === broadcast.id)
      if (exists) {
        return items.map((item) => (item.id === broadcast.id ? broadcast : item))
      }
      return [broadcast, ...items]
    })
  }

  const handleSaveTemplate = async (templateName: string, content: BroadcastContent) => {
    if (!selectedProjectId) return
    if (contentHasMedia(content)) {
      notify({ tone: 'error', message: 'Шаблоны с медиа будут добавлены позже.' })
      return
    }
    try {
      const template = await createBroadcastTemplate({
        project_id: selectedProjectId,
        name: templateName,
        content_json: content,
      })
      setTemplates((items) => [template, ...items.filter((item) => item.id !== template.id)])
      notify({ tone: 'success', message: 'Шаблон сохранён.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err, 'Не удалось сохранить шаблон.') })
    }
  }

  const handleUploadMedia = async (
    file: File,
    mediaType: BroadcastMediaType,
  ): Promise<BroadcastUpload> => {
    if (!selectedProjectId) {
      throw new Error('project required')
    }
    try {
      const upload = await uploadBroadcastMedia(selectedProjectId, file, mediaType)
      notify({ tone: 'success', message: 'Файл загружен.' })
      return upload
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err, 'Не удалось загрузить файл.') })
      throw err
    }
  }

  const handleDuplicate = async (broadcast: Broadcast) => {
    if (!selectedProjectId) return
    try {
      const copy = await createBroadcast({
        project_id: selectedProjectId,
        bot_id: broadcast.bot_id,
        name: duplicateName(broadcast.name),
        content_json: broadcast.content_json,
        audience_filter_json: broadcast.audience_filter_json,
        schedule_type: 'now',
        scheduled_at: null,
        timezone_mode: broadcast.timezone_mode,
      })
      handleSaved(copy)
      setEditingBroadcast(copy)
      setIsWizardOpen(true)
      notify({ tone: 'success', message: 'Черновик рассылки скопирован.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleCancel = async (broadcast: Broadcast) => {
    if (!selectedProjectId) return
    try {
      const cancelled = await cancelBroadcast(broadcast.id, selectedProjectId)
      handleSaved(cancelled)
      notify({ tone: 'success', message: 'Рассылка отменена.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handlePause = async (broadcast: Broadcast) => {
    if (!selectedProjectId) return
    try {
      const paused = await pauseBroadcast(broadcast.id, selectedProjectId)
      handleSaved(paused)
      notify({ tone: 'success', message: 'Рассылка поставлена на паузу.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleResume = async (broadcast: Broadcast) => {
    if (!selectedProjectId) return
    try {
      const resumed = await resumeBroadcast(broadcast.id, selectedProjectId)
      handleSaved(resumed)
      notify({ tone: 'success', message: 'Рассылка продолжена.' })
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  if (!selectedProjectId) {
    return (
      <section className="flex h-full min-h-0 items-center justify-center overflow-y-auto rounded-xl border border-white/5 bg-surface p-6 text-center shadow-card">
        <div>
          <Megaphone className="mx-auto text-accent-300" size={36} />
          <h1 className="mt-4 text-2xl font-semibold text-white">Рассылки</h1>
          <p className="mt-2 text-sm text-gray-500">Выберите проект, чтобы работать с рассылками.</p>
        </div>
      </section>
    )
  }

  if (isWizardOpen) {
    return (
      <BroadcastWizard
        broadcast={editingBroadcast}
        projectId={selectedProjectId}
        defaultBotId={defaultBotId}
        bots={botOptions}
        tags={tags}
        statuses={statuses}
        trackingLinks={trackingLinks}
        users={users}
        funnels={funnels}
        templates={templates}
        snippets={snippets}
        chatFilterPresets={chatFilterPresets}
        onSaveTemplate={handleSaveTemplate}
        onUploadMedia={handleUploadMedia}
        onBack={() => {
          setIsWizardOpen(false)
          setEditingBroadcast(null)
        }}
        onSaved={handleSaved}
      />
    )
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-white/5 bg-[#0d1324]/95 shadow-card">
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/8 px-5 py-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.24em] text-accent-200/70">
            <Megaphone size={15} />
            Broadcasts
          </div>
          <h1 className="mt-2 text-2xl font-semibold text-white">Рассылки</h1>
          <p className="mt-1 text-sm text-gray-500">
            Линейный мастер массовых сообщений: контент, аудитория, расписание и проверка.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            setEditingBroadcast(null)
            setIsWizardOpen(true)
          }}
          disabled={isOptionsLoading || botOptions.length === 0}
          className="inline-flex h-10 items-center gap-2 rounded-xl bg-accent-500 px-4 text-sm font-semibold text-white transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus size={16} />
          Новая рассылка
        </button>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto p-5">
        {isLoading ? (
          <div className="flex h-full min-h-[220px] items-center justify-center text-gray-500">
            <LoaderCircle className="mr-2 animate-spin" size={18} />
            Загружаем рассылки...
          </div>
        ) : (
          <BroadcastList
            broadcasts={broadcasts}
            botLabelById={botLabelById}
            reports={reports}
            onOpen={(broadcast) => {
              setEditingBroadcast(broadcast)
              setIsWizardOpen(true)
            }}
            onDuplicate={(broadcast) => void handleDuplicate(broadcast)}
            onCancel={(broadcast) => void handleCancel(broadcast)}
            onPause={(broadcast) => void handlePause(broadcast)}
            onResume={(broadcast) => void handleResume(broadcast)}
            onRefreshReport={(broadcast) => {
              void fetchBroadcastReport(broadcast.id, selectedProjectId).then((report) =>
                setReports((items) => ({ ...items, [broadcast.id]: report })),
              )
            }}
          />
        )}
      </main>
    </section>
  )
}

import axios from 'axios'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { fetchBots, type Bot as BotRecord } from '../features/bots'
import {
  archiveFunnel,
  createFunnel,
  fetchFunnels,
  setFunnelCurrentVersion,
  setBotActiveFunnel,
  type Funnel,
} from '../features/funnels'
import CopyFunnelModal from '../features/funnels/components/CopyFunnelModal'
import FunnelBuilder from '../features/funnels/components/FunnelBuilder'
import FunnelList, { type ActiveFunnelSelection } from '../features/funnels/components/FunnelList'
import { fetchProjects, type Project } from '../features/projects'
import { useNotificationStore, useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

function getErrorMessage(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (err.response?.status === 403) {
      return 'Недостаточно прав для действия с этой воронкой.'
    }
    if (err.response?.status === 409) {
      return 'Действие конфликтует с текущим состоянием воронки.'
    }
    if (err.response?.status === 422 || Array.isArray(detail)) {
      return 'Проверьте данные формы.'
    }
    if (typeof detail === 'string' && detail) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }
  return 'Запрос не выполнен.'
}

export default function FunnelsPage() {
  const navigate = useNavigate()
  const params = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const {
    selectedProjectId,
    selectedBotIds,
    setSelectedBotIds,
    setSelectedProjectId,
  } = useProjectBotSelection()
  const notify = useNotificationStore((state) => state.notify)
  const roleName = useAuthStore((state) => state.user?.role_name)
  const canEdit = roleName === 'super_admin' || roleName === 'admin'
  const canActivate = roleName === 'super_admin' || roleName === 'admin' || roleName === 'manager'

  const [funnels, setFunnels] = useState<Funnel[]>([])
  const [bots, setBots] = useState<BotRecord[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isCreating, setIsCreating] = useState(false)
  const [copyTarget, setCopyTarget] = useState<Funnel | null>(null)

  const funnelId = params.funnelId ?? null
  const versionId = searchParams.get('versionId')

  const visibleFunnels = useMemo(() => {
    if (selectedBotIds.length <= 1) {
      return funnels
    }
    const selected = new Set(selectedBotIds)
    return funnels.filter((funnel) => selected.has(funnel.bot_id))
  }, [funnels, selectedBotIds])

  const loadData = useCallback(async () => {
    setIsLoading(true)
    try {
      const [projectItems, botItems] = await Promise.all([
        fetchProjects().catch(() => []),
        fetchBots().catch(() => []),
      ])
      setProjects(projectItems)
      setBots(botItems)

      if (!selectedProjectId) {
        setFunnels([])
        return
      }

      const botId = selectedBotIds.length === 1 ? selectedBotIds[0] : null
      const data = await fetchFunnels({
        projectId: selectedProjectId,
        botId,
        status: 'active',
      })
      setFunnels(data.items)
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsLoading(false)
    }
  }, [notify, selectedBotIds, selectedProjectId])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleCreate = async (payload: {
    name: string
    description: string
    botId: string
  }) => {
    if (!selectedProjectId || isCreating) {
      return
    }
    setIsCreating(true)
    try {
      const created = await createFunnel({
        project_id: selectedProjectId,
        bot_id: payload.botId,
        name: payload.name,
        description: payload.description || null,
      })
      notify({ tone: 'success', message: 'Черновик воронки создан.' })
      await loadData()
      navigate(`/funnels/${created.id}/builder?versionId=${created.draft_version_id ?? ''}`)
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    } finally {
      setIsCreating(false)
    }
  }

  const handleArchive = async (funnel: Funnel) => {
    try {
      await archiveFunnel(funnel)
      notify({ tone: 'success', message: 'Воронка отправлена в архив.' })
      await loadData()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleMakeActive = async ({ funnel, version }: ActiveFunnelSelection) => {
    if (!selectedProjectId) {
      return
    }
    const confirmed = window.confirm(
      `Сделать «${funnel.name}» версии v${version.version_number} активной? Новые и сброшенные диалоги начнутся в этой версии. Уже начатые диалоги продолжат свою текущую версию, чтобы не потерять сценарий.`,
    )
    if (!confirmed) {
      return
    }
    try {
      await setBotActiveFunnel(funnel.bot_id, selectedProjectId, {
        funnel_id: funnel.id,
        version_id: version.id,
      })
      notify({
        tone: 'success',
        message: 'Воронка активирована. Текущие диалоги продолжают прежнюю версию.',
      })
      await loadData()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleSetCurrentVersion = async (funnel: Funnel, versionId: string) => {
    if (!selectedProjectId) {
      return
    }
    const version = funnel.published_versions.find((item) => item.id === versionId)
    if (!version) {
      return
    }
    const confirmed = window.confirm(
      funnel.is_active_for_bot
        ? `Сделать v${version.version_number} актуальной для «${funnel.name}»? Так как эта воронка активна на боте, новые и сброшенные диалоги начнутся в этой версии.`
        : `Сделать v${version.version_number} актуальной для «${funnel.name}»? В селекторе активной воронки будет использоваться именно она.`,
    )
    if (!confirmed) {
      return
    }
    try {
      await setFunnelCurrentVersion(funnel.id, version.id, selectedProjectId)
      notify({
        tone: 'success',
        message: funnel.is_active_for_bot
          ? 'Актуальная версия обновлена, активный бот переключён на неё.'
          : 'Актуальная версия воронки обновлена.',
      })
      await loadData()
    } catch (err) {
      notify({ tone: 'error', message: getErrorMessage(err) })
    }
  }

  const handleVersionReady = useCallback(
    (resolvedVersionId: string) => {
      if (versionId === resolvedVersionId) {
        return
      }
      setSearchParams({ versionId: resolvedVersionId }, { replace: true })
    },
    [setSearchParams, versionId],
  )

  if (funnelId && selectedProjectId) {
    if (!canEdit) {
      return <Navigate to="/funnels" replace />
    }
    return (
      <section className="min-h-full text-gray-200 md:h-full md:min-h-0 md:overflow-hidden">
        <FunnelBuilder
          funnelId={funnelId}
          versionId={versionId}
          projectId={selectedProjectId}
          onBack={() => navigate('/funnels')}
          onVersionReady={handleVersionReady}
        />
      </section>
    )
  }

  return (
    <section className="min-h-full text-gray-200 md:h-full md:min-h-0 md:overflow-hidden">
      <FunnelList
        funnels={visibleFunnels}
        bots={bots.filter((bot) => !selectedProjectId || bot.project_id === selectedProjectId)}
        selectedProjectId={selectedProjectId}
        selectedBotIds={selectedBotIds}
        isLoading={isLoading}
        isCreating={isCreating}
        canEdit={canEdit}
        canActivate={canActivate}
        onCreate={handleCreate}
        onOpen={(funnel) =>
          navigate(
            `/funnels/${funnel.id}/builder?versionId=${
              funnel.draft_version_id ?? funnel.published_version_id ?? ''
            }`,
          )
        }
        onCopy={setCopyTarget}
        onArchive={(funnel) => void handleArchive(funnel)}
        onMakeActive={(selection) => void handleMakeActive(selection)}
        onSetCurrentVersion={(funnel, versionId) =>
          void handleSetCurrentVersion(funnel, versionId)
        }
      />

      {copyTarget ? (
        <CopyFunnelModal
          funnel={copyTarget}
          projects={projects}
          bots={bots}
          onClose={() => setCopyTarget(null)}
          onCopied={(newFunnelId, newVersionId, targetProjectId, targetBotId) => {
            setCopyTarget(null)
            if (targetProjectId !== selectedProjectId) {
              setSelectedProjectId(targetProjectId)
            }
            setSelectedBotIds([targetBotId])
            notify({
              tone: 'success',
              message: 'Воронка скопирована. Проверьте настройки перед публикацией.',
            })
            navigate(`/funnels/${newFunnelId}/builder?versionId=${newVersionId}`)
          }}
        />
      ) : null}
    </section>
  )
}

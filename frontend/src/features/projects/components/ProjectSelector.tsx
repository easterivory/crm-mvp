import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { ChevronDown, LoaderCircle, Plus } from 'lucide-react'

import { isSuperAdminRole, useProjectBotSelection } from '../../../shared/lib'
import { Modal } from '../../../shared/ui'
import { useAuthStore } from '../../../store/authStore'
import { createProject, fetchProjects } from '../api'
import type { Project } from '../types'

type ProjectSelectorProps = {
  compact?: boolean
}

function getProjectError(err: unknown) {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const messages = detail
        .map((item) => {
          if (typeof item?.msg === 'string') {
            return item.msg
          }

          return null
        })
        .filter(Boolean)

      if (messages.length > 0) {
        return messages.join(' ')
      }
    }
    if (err.response?.status === 409) {
      return 'Такой slug проекта уже есть.'
    }
    if (err.response?.status === 422) {
      return 'Проверьте поля проекта и попробуйте снова.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Ошибка сети. Проверьте backend и попробуйте снова.'
    }
  }

  return 'Не удалось создать проект.'
}

export default function ProjectSelector({ compact = false }: ProjectSelectorProps) {
  const { resetBotSelection, selectedProjectId, setSelectedProjectId } =
    useProjectBotSelection()
  const currentUser = useAuthStore((state) => state.user)
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [projectSlug, setProjectSlug] = useState('')
  const [projectDescription, setProjectDescription] = useState('')
  const [createError, setCreateError] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  const canCreateProject = isSuperAdminRole(currentUser?.role_name)

  const activeProjects = useMemo(
    () => projects.filter((project) => project.status === 'active'),
    [projects],
  )

  const loadProjects = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const items = await fetchProjects()
      setProjects(items)
    } catch {
      setError('Проекты недоступны')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadProjects().catch(() => undefined)
  }, [loadProjects])

  useEffect(() => {
    if (isLoading || error) {
      return
    }

    if (activeProjects.length === 0) {
      if (selectedProjectId) {
        setSelectedProjectId(null)
      }
      return
    }

    const selectedProjectExists = activeProjects.some(
      (project) => project.id === selectedProjectId,
    )

    if (!selectedProjectId || !selectedProjectExists) {
      setSelectedProjectId(activeProjects[0].id)
    }
  }, [activeProjects, error, isLoading, selectedProjectId, setSelectedProjectId])

  const selectedProjectName =
    activeProjects.find((project) => project.id === selectedProjectId)?.name ??
    (isLoading ? 'Загрузка проектов' : 'Нет проекта')

  const closeCreate = () => {
    if (isCreating) {
      return
    }
    setIsCreateOpen(false)
    setProjectName('')
    setProjectSlug('')
    setProjectDescription('')
    setCreateError('')
  }

  const handleCreateProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()

    const name = projectName.trim()
    if (!name || isCreating) {
      return
    }

    setIsCreating(true)
    setCreateError('')

    try {
      const created = await createProject({
        name,
        slug: projectSlug.trim() || undefined,
        description: projectDescription.trim() || null,
      })
      setProjects((current) => [created, ...current.filter((item) => item.id !== created.id)])
      resetBotSelection()
      setSelectedProjectId(created.id)
      setIsCreateOpen(false)
      setProjectName('')
      setProjectSlug('')
      setProjectDescription('')
      await loadProjects()
    } catch (err) {
      setCreateError(getProjectError(err))
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="relative flex min-w-0 items-end gap-2">
      <label className="group relative flex min-w-0 flex-col gap-1">
        <span className={`${compact ? 'sr-only' : 'text-[10px] font-semibold uppercase tracking-[0.2em] text-gray-500'}`}>
          Проект
        </span>
        <div className="relative">
          <select
            aria-label="Проект"
            value={selectedProjectId ?? ''}
            disabled={isLoading || Boolean(error) || activeProjects.length === 0}
            onChange={(event) => setSelectedProjectId(event.target.value || null)}
            className={`h-10 w-full appearance-none rounded-xl border border-white/10 bg-white/[0.04] px-3 pr-9 text-sm font-medium text-gray-100 outline-none transition hover:border-accent-300/40 focus:border-accent-300/60 focus:shadow-glow-accent disabled:cursor-not-allowed disabled:text-gray-500 ${
              compact ? 'min-w-0' : 'min-w-[190px]'
            }`}
            title={error ?? selectedProjectName}
          >
            {isLoading ? <option value="">Загрузка проектов</option> : null}
            {error ? <option value="">{error}</option> : null}
            {!isLoading && !error && activeProjects.length === 0 ? (
              <option value="">Нет проектов</option>
            ) : null}
            {activeProjects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>

          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 transition group-focus-within:text-accent-300">
            {isLoading ? (
              <LoaderCircle size={16} className="animate-spin" />
            ) : (
              <ChevronDown size={16} />
            )}
          </span>
        </div>
      </label>

      {canCreateProject ? (
        <button
          type="button"
          title="Создать проект"
          aria-label="Создать проект"
          onClick={() => setIsCreateOpen(true)}
          className={`${compact ? 'w-10 px-0' : 'px-3'} inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] text-gray-200 transition hover:border-accent-300/50 hover:text-white hover:shadow-glow-accent`}
        >
          <Plus size={17} />
          <span className="hidden text-sm font-medium xl:inline">Новый</span>
        </button>
      ) : null}

      {isCreateOpen ? (
        <Modal
          title="Создать проект"
          description="Добавьте новый проектный контур."
          onClose={closeCreate}
        >
          <form
            onSubmit={handleCreateProject}
            className="w-full"
          >
            {createError ? (
              <div className="mb-4 rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {createError}
              </div>
            ) : null}

            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Название
                </span>
                <input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  maxLength={255}
                  required
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                  placeholder="Название проекта"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Slug
                </span>
                <input
                  value={projectSlug}
                  onChange={(event) => setProjectSlug(event.target.value)}
                  maxLength={255}
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                  placeholder="optional-slug"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Описание
                </span>
                <textarea
                  value={projectDescription}
                  onChange={(event) => setProjectDescription(event.target.value)}
                  rows={3}
                  className="max-h-32 w-full resize-none overflow-y-auto rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                  placeholder="Описание необязательно"
                />
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeCreate}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={!projectName.trim() || isCreating}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreating ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Создать
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </div>
  )
}

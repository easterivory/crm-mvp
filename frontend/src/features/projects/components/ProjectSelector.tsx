import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import { ChevronDown, LoaderCircle, Plus, X } from 'lucide-react'

import { isSuperAdminRole, useProjectBotSelection } from '../../../shared/lib'
import { useAuthStore } from '../../../store/authStore'
import { createProject, fetchProjects } from '../api'
import type { Project } from '../types'

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
      return 'Project slug already exists.'
    }
    if (err.response?.status === 422) {
      return 'Check project fields and try again.'
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Network error. Check backend connection and try again.'
    }
  }

  return 'Could not create project.'
}

export default function ProjectSelector() {
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
      setError('Projects unavailable')
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
    (isLoading ? 'Loading projects' : 'No project')

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
        <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-gray-500">
          Project
        </span>
        <div className="relative">
          <select
            aria-label="Project"
            value={selectedProjectId ?? ''}
            disabled={isLoading || Boolean(error) || activeProjects.length === 0}
            onChange={(event) => setSelectedProjectId(event.target.value || null)}
            className="h-10 w-full min-w-[190px] appearance-none rounded-xl border border-white/10 bg-white/[0.04] px-3 pr-9 text-sm font-medium text-gray-100 outline-none transition hover:border-accent-300/40 focus:border-accent-300/60 focus:shadow-glow-accent disabled:cursor-not-allowed disabled:text-gray-500"
            title={error ?? selectedProjectName}
          >
            {isLoading ? <option value="">Loading projects</option> : null}
            {error ? <option value="">{error}</option> : null}
            {!isLoading && !error && activeProjects.length === 0 ? (
              <option value="">No projects</option>
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
          title="Create project"
          aria-label="Create project"
          onClick={() => setIsCreateOpen(true)}
          className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 text-gray-200 transition hover:border-accent-300/50 hover:text-white hover:shadow-glow-accent"
        >
          <Plus size={17} />
          <span className="hidden text-sm font-medium xl:inline">New</span>
        </button>
      ) : null}

      {isCreateOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <form
            onSubmit={handleCreateProject}
            className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0B0F19] p-5 shadow-card"
          >
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-white">Create project</h2>
                <p className="text-sm text-gray-500">Add a new project scope.</p>
              </div>
              <button
                type="button"
                onClick={closeCreate}
                className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/[0.03] text-gray-300 transition hover:border-accent-300/50 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            {createError ? (
              <div className="mb-4 rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-200">
                {createError}
              </div>
            ) : null}

            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
                  Name
                </span>
                <input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  maxLength={255}
                  required
                  className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                  placeholder="Project name"
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
                  Description
                </span>
                <textarea
                  value={projectDescription}
                  onChange={(event) => setProjectDescription(event.target.value)}
                  rows={3}
                  className="max-h-32 w-full resize-none overflow-y-auto rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition placeholder:text-gray-600 focus:ring-2"
                  placeholder="Optional description"
                />
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={closeCreate}
                className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-white/20 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!projectName.trim() || isCreating}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isCreating ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Create
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  )
}

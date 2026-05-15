import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, LoaderCircle } from 'lucide-react'

import { useProjectBotSelection } from '../../../shared/lib'
import { fetchProjects } from '../api'
import type { Project } from '../types'

export default function ProjectSelector() {
  const { selectedProjectId, setSelectedProjectId } = useProjectBotSelection()
  const [projects, setProjects] = useState<Project[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  return (
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
  )
}

import {
  LoaderCircle,
  Plus,
  Save,
  Settings,
  Tag,
  Trash2,
  UserPlus,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import api from '../api/client'
import { useAuthStore } from '../store/authStore'

type TabKey = 'project' | 'team' | 'statuses' | 'tags'

type PaginatedResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type Project = {
  id: string
  name: string
  sla_threshold_minutes: number
  created_at: string
  is_deleted: boolean
}

type User = {
  id: string
  email: string
  name: string
  project_id: string | null
  role_id: string
  created_at: string
  is_deleted: boolean
}

type Role = {
  id: string
  name: 'super_admin' | 'admin' | 'manager'
}

type LeadStatus = {
  id: string
  code: string
  name: string
  sort_order: number
  is_final: boolean
  created_at: string
}

type ProjectTag = {
  id: string
  project_id: string
  name: string
  created_at: string
}

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'project', label: 'Project' },
  { key: 'team', label: 'Team' },
  { key: 'statuses', label: 'Statuses' },
  { key: 'tags', label: 'Tags' },
]

function getErrorMessage(err: unknown, fallback = 'Request failed.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'Cannot reach API.'
    }
  }

  return fallback
}

function roleLabel(roleName: string) {
  return roleName
    .split('_')
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(' ')
}

export default function SettingsPage() {
  const currentUser = useAuthStore((state) => state.user)

  const [activeTab, setActiveTab] = useState<TabKey>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [statuses, setStatuses] = useState<LeadStatus[]>([])
  const [tags, setTags] = useState<ProjectTag[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSavingProject, setIsSavingProject] = useState(false)
  const [isAddingUser, setIsAddingUser] = useState(false)
  const [isAddingStatus, setIsAddingStatus] = useState(false)
  const [isAddingTag, setIsAddingTag] = useState(false)
  const [deletingTagId, setDeletingTagId] = useState<string | null>(null)

  const [projectName, setProjectName] = useState('')
  const [slaMinutes, setSlaMinutes] = useState('30')
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserName, setNewUserName] = useState('')
  const [newUserPassword, setNewUserPassword] = useState('')
  const [newUserRoleId, setNewUserRoleId] = useState('')
  const [newStatusCode, setNewStatusCode] = useState('')
  const [newStatusName, setNewStatusName] = useState('')
  const [newStatusFinal, setNewStatusFinal] = useState(false)
  const [newTagName, setNewTagName] = useState('')

  const selectedRole = useMemo(
    () => roles.find((role) => role.id === newUserRoleId) ?? null,
    [newUserRoleId, roles],
  )

  const loadProject = useCallback(async () => {
    if (!currentUser?.project_id) {
      setProject(null)
      return
    }

    const { data } = await api.get<Project>(`/projects/${currentUser.project_id}`)
    setProject(data)
    setProjectName(data.name)
    setSlaMinutes(String(data.sla_threshold_minutes))
  }, [currentUser?.project_id])

  const loadUsers = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<User>>('/users', {
      params: { limit: 100, offset: 0 },
    })
    setUsers(data.items)
  }, [])

  const loadRoles = useCallback(async () => {
    const { data } = await api.get<Role[]>('/users/roles')
    setRoles(data)
    setNewUserRoleId((current) => {
      if (current && data.some((role) => role.id === current)) {
        return current
      }
      return data.find((role) => role.name === 'manager')?.id ?? data[0]?.id ?? ''
    })
  }, [])

  const loadStatuses = useCallback(async () => {
    const { data } = await api.get<LeadStatus[]>('/leads/statuses')
    setStatuses(data)
  }, [])

  const loadTags = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<ProjectTag>>('/tags', {
      params: { limit: 100, offset: 0 },
    })
    setTags(data.items)
  }, [])

  const loadAll = useCallback(async () => {
    setIsLoading(true)
    setError('')

    try {
      await Promise.all([
        loadProject(),
        loadUsers(),
        loadRoles(),
        loadStatuses(),
        loadTags(),
      ])
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load settings.'))
    } finally {
      setIsLoading(false)
    }
  }, [loadProject, loadRoles, loadStatuses, loadTags, loadUsers])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const handleProjectSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!project || isSavingProject) {
      return
    }

    setIsSavingProject(true)
    setError('')
    setNotice('')

    try {
      const { data } = await api.patch<Project>(`/projects/${project.id}`, {
        name: projectName.trim(),
        sla_threshold_minutes: Number(slaMinutes),
      })
      setProject(data)
      setProjectName(data.name)
      setSlaMinutes(String(data.sla_threshold_minutes))
      setNotice('Project settings saved.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not save project.'))
    } finally {
      setIsSavingProject(false)
    }
  }

  const handleAddUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!newUserRoleId || isAddingUser) {
      return
    }

    setIsAddingUser(true)
    setError('')
    setNotice('')

    try {
      await api.post<User>('/users', {
        email: newUserEmail.trim(),
        name: newUserName.trim(),
        password: newUserPassword,
        role_id: newUserRoleId,
        project_id:
          selectedRole?.name === 'super_admin' ? null : currentUser?.project_id ?? null,
      })
      setNewUserEmail('')
      setNewUserName('')
      setNewUserPassword('')
      await loadUsers()
      setNotice('User added.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add user.'))
    } finally {
      setIsAddingUser(false)
    }
  }

  const handleAddStatus = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isAddingStatus) {
      return
    }

    setIsAddingStatus(true)
    setError('')
    setNotice('')

    try {
      await api.post<LeadStatus>('/leads/statuses', {
        code: newStatusCode.trim(),
        name: newStatusName.trim(),
        is_final: newStatusFinal,
      })
      setNewStatusCode('')
      setNewStatusName('')
      setNewStatusFinal(false)
      await loadStatuses()
      setNotice('Lead status added.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add status.'))
    } finally {
      setIsAddingStatus(false)
    }
  }

  const handleAddTag = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isAddingTag) {
      return
    }

    setIsAddingTag(true)
    setError('')
    setNotice('')

    try {
      await api.post<ProjectTag>('/tags', { name: newTagName.trim() })
      setNewTagName('')
      await loadTags()
      setNotice('Tag added.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add tag.'))
    } finally {
      setIsAddingTag(false)
    }
  }

  const handleDeleteTag = async (tagId: string) => {
    setDeletingTagId(tagId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/tags/${tagId}`)
      await loadTags()
      setNotice('Tag deleted.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete tag.'))
    } finally {
      setDeletingTagId(null)
    }
  }

  return (
    <section className="flex h-[calc(100vh-112px)] min-h-[560px] overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl">
      <aside className="w-60 border-r border-zinc-800 p-4">
        <div className="mb-5 flex items-center gap-3 px-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-300">
            <Settings size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Settings</h1>
            <p className="text-xs text-zinc-500">Workspace controls</p>
          </div>
        </div>
        <nav className="space-y-2">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`w-full rounded-lg px-3 py-2 text-left text-sm font-medium transition ${
                activeTab === tab.key
                  ? 'bg-zinc-900 text-emerald-300'
                  : 'text-zinc-300 hover:bg-zinc-900'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1 overflow-y-auto p-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-red-900/70 bg-red-950/40 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        ) : null}
        {notice ? (
          <div className="mb-4 rounded-lg border border-emerald-900/70 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-200">
            {notice}
          </div>
        ) : null}

        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-zinc-500">
            <LoaderCircle size={18} className="mr-2 animate-spin" />
            Loading settings
          </div>
        ) : null}

        {!isLoading && activeTab === 'project' ? (
          <form className="max-w-xl space-y-4" onSubmit={handleProjectSave}>
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Project</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Basic CRM project settings.
              </p>
            </div>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Название проекта
              </span>
              <input
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                maxLength={255}
                required
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                SLA для красных чатов (в минутах)
              </span>
              <input
                type="number"
                min={1}
                value={slaMinutes}
                onChange={(event) => setSlaMinutes(event.target.value)}
                required
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
              />
            </label>
            <button
              type="submit"
              disabled={!project || isSavingProject}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSavingProject ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
              Save project
            </button>
          </form>
        ) : null}

        {!isLoading && activeTab === 'team' ? (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Team</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Users in the current project.
              </p>
            </div>

            <div className="overflow-hidden rounded-lg border border-zinc-800">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Email</th>
                    <th className="px-4 py-3">Role</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {users.map((user) => {
                    const role = roles.find((item) => item.id === user.role_id)
                    return (
                      <tr key={user.id} className="bg-zinc-950">
                        <td className="px-4 py-3 text-zinc-100">{user.name}</td>
                        <td className="px-4 py-3 text-zinc-400">{user.email}</td>
                        <td className="px-4 py-3 text-zinc-400">
                          {role ? roleLabel(role.name) : user.role_id.slice(0, 8)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <form
              className="grid gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 md:grid-cols-5"
              onSubmit={handleAddUser}
            >
              <input
                type="email"
                value={newUserEmail}
                onChange={(event) => setNewUserEmail(event.target.value)}
                placeholder="Email"
                required
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <input
                value={newUserName}
                onChange={(event) => setNewUserName(event.target.value)}
                placeholder="Name"
                required
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <input
                type="password"
                value={newUserPassword}
                onChange={(event) => setNewUserPassword(event.target.value)}
                placeholder="Password"
                required
                minLength={8}
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <select
                value={newUserRoleId}
                onChange={(event) => setNewUserRoleId(event.target.value)}
                required
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
              >
                {roles.map((role) => (
                  <option key={role.id} value={role.id}>
                    {roleLabel(role.name)}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={isAddingUser}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isAddingUser ? <LoaderCircle size={16} className="animate-spin" /> : <UserPlus size={16} />}
                Add User
              </button>
            </form>
          </div>
        ) : null}

        {!isLoading && activeTab === 'statuses' ? (
          <div className="max-w-3xl space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Statuses</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Lead pipeline statuses.
              </p>
            </div>
            <div className="space-y-2">
              {statuses.map((status) => (
                <div
                  key={status.id}
                  className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3"
                >
                  <div>
                    <p className="text-sm font-medium text-zinc-100">{status.name}</p>
                    <p className="text-xs text-zinc-500">{status.code}</p>
                  </div>
                  {status.is_final ? (
                    <span className="rounded bg-amber-500/15 px-2 py-1 text-xs font-semibold text-amber-300">
                      Final
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
            <form
              className="grid gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 md:grid-cols-[1fr_1fr_auto_auto]"
              onSubmit={handleAddStatus}
            >
              <input
                value={newStatusName}
                onChange={(event) => setNewStatusName(event.target.value)}
                placeholder="Status name"
                required
                maxLength={100}
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <input
                value={newStatusCode}
                onChange={(event) => setNewStatusCode(event.target.value)}
                placeholder="status_code"
                required
                maxLength={50}
                className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <label className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={newStatusFinal}
                  onChange={(event) => setNewStatusFinal(event.target.checked)}
                  className="h-4 w-4 accent-emerald-500"
                />
                Final
              </label>
              <button
                type="submit"
                disabled={isAddingStatus}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isAddingStatus ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Add
              </button>
            </form>
          </div>
        ) : null}

        {!isLoading && activeTab === 'tags' ? (
          <div className="max-w-3xl space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Tags</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Project labels for leads.
              </p>
            </div>
            <div className="space-y-2">
              {tags.map((tag) => (
                <div
                  key={tag.id}
                  className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3"
                >
                  <div className="flex items-center gap-2 text-sm font-medium text-zinc-100">
                    <Tag size={16} className="text-zinc-500" />
                    {tag.name}
                  </div>
                  <button
                    type="button"
                    title="Delete tag"
                    onClick={() => void handleDeleteTag(tag.id)}
                    disabled={deletingTagId === tag.id}
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {deletingTagId === tag.id ? (
                      <LoaderCircle size={16} className="animate-spin" />
                    ) : (
                      <Trash2 size={16} />
                    )}
                  </button>
                </div>
              ))}
            </div>
            <form
              className="flex gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"
              onSubmit={handleAddTag}
            >
              <input
                value={newTagName}
                onChange={(event) => setNewTagName(event.target.value)}
                placeholder="New tag"
                required
                maxLength={100}
                className="min-w-0 flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
              />
              <button
                type="submit"
                disabled={isAddingTag}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isAddingTag ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Add Tag
              </button>
            </form>
          </div>
        ) : null}
      </div>
    </section>
  )
}

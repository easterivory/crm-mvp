import {
  Check,
  LoaderCircle,
  Pencil,
  Plus,
  Save,
  Settings,
  Tag,
  Trash2,
  UserPlus,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'

import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
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
  role_name?: string | null
  created_at: string
  is_deleted: boolean
}

type Role = {
  id: string
  name: 'super_admin' | 'admin' | 'manager' | 'operator'
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
  const { selectedProjectId } = useProjectBotSelection()

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
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null)
  const [deletingStatusId, setDeletingStatusId] = useState<string | null>(null)
  const [deletingTagId, setDeletingTagId] = useState<string | null>(null)
  const [editingStatusId, setEditingStatusId] = useState<string | null>(null)
  const [editingStatusName, setEditingStatusName] = useState('')
  const [savingStatusId, setSavingStatusId] = useState<string | null>(null)
  const [editingTagId, setEditingTagId] = useState<string | null>(null)
  const [editingTagName, setEditingTagName] = useState('')
  const [savingTagId, setSavingTagId] = useState<string | null>(null)

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

  const activeProjectId = selectedProjectId ?? currentUser?.project_id ?? null
  const currentRoleName = currentUser?.role_name
  const canManageStaff =
    currentRoleName === 'super_admin' || currentRoleName === 'admin'
  const canManageProject =
    currentRoleName === 'super_admin' || currentRoleName === 'admin'
  const visibleTabs = useMemo(
    () =>
      tabs.filter((tab) => {
        if (tab.key === 'team') {
          return canManageStaff
        }
        if (tab.key === 'project') {
          return canManageProject
        }
        return true
      }),
    [canManageProject, canManageStaff],
  )

  const selectedRole = useMemo(
    () => roles.find((role) => role.id === newUserRoleId) ?? null,
    [newUserRoleId, roles],
  )

  const staffRoles = useMemo(
    () =>
      roles.filter((role) => {
        if (currentRoleName === 'super_admin') {
          return role.name !== 'super_admin'
        }
        if (currentRoleName === 'admin') {
          return role.name === 'manager' || role.name === 'operator'
        }
        return false
      }),
    [currentRoleName, roles],
  )

  const getUserRoleName = useCallback(
    (user: User) =>
      roles.find((role) => role.id === user.role_id)?.name ??
      user.role_name ??
      null,
    [roles],
  )

  const canDeleteUser = useCallback(
    (user: User) => {
      if (!canManageStaff || user.id === currentUser?.id) {
        return false
      }

      const targetRoleName = getUserRoleName(user)
      if (targetRoleName === 'super_admin') {
        return false
      }

      if (currentRoleName === 'super_admin') {
        return true
      }

      return (
        currentRoleName === 'admin' &&
        (targetRoleName === 'manager' || targetRoleName === 'operator') &&
        user.project_id === activeProjectId
      )
    },
    [
      activeProjectId,
      canManageStaff,
      currentRoleName,
      currentUser?.id,
      getUserRoleName,
    ],
  )

  useEffect(() => {
    if (!visibleTabs.some((tab) => tab.key === activeTab)) {
      setActiveTab(visibleTabs[0]?.key ?? 'tags')
    }
  }, [activeTab, visibleTabs])

  useEffect(() => {
    if (!canManageStaff || staffRoles.length === 0) {
      setNewUserRoleId('')
      return
    }

    setNewUserRoleId((current) => {
      if (staffRoles.some((role) => role.id === current)) {
        return current
      }
      return staffRoles[0].id
    })
  }, [canManageStaff, staffRoles])

  const loadProject = useCallback(async () => {
    if (!activeProjectId) {
      setProject(null)
      return
    }

    const { data } = await api.get<Project>(`/projects/${activeProjectId}`)
    setProject(data)
    setProjectName(data.name)
    setSlaMinutes(String(data.sla_threshold_minutes))
  }, [activeProjectId])

  const loadUsers = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<User>>('/users', {
      params: {
        limit: 100,
        offset: 0,
        ...(activeProjectId ? { project_id: activeProjectId } : {}),
      },
    })
    setUsers(data.items)
  }, [activeProjectId])

  const loadRoles = useCallback(async () => {
    const { data } = await api.get<Role[]>('/users/roles')
    setRoles(data)
  }, [])

  const loadStatuses = useCallback(async () => {
    const { data } = await api.get<LeadStatus[]>('/leads/statuses')
    setStatuses(data)
  }, [])

  const loadTags = useCallback(async () => {
    if (!activeProjectId) {
      setTags([])
      return
    }

    const { data } = await api.get<PaginatedResponse<ProjectTag>>('/tags', {
      params: {
        limit: 100,
        offset: 0,
        project_id: activeProjectId,
      },
    })
    setTags(data.items)
  }, [activeProjectId])

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
    if (
      !newUserRoleId ||
      !activeProjectId ||
      !canManageStaff ||
      !staffRoles.some((role) => role.id === newUserRoleId) ||
      isAddingUser
    ) {
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
        project_id: selectedRole?.name === 'super_admin' ? null : activeProjectId,
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

  const handleDeleteUser = async (userId: string) => {
    const targetUser = users.find((user) => user.id === userId)
    if (!targetUser || !canDeleteUser(targetUser)) {
      setError('You do not have permission to delete this user.')
      return
    }

    if (!window.confirm('Delete this user?')) {
      return
    }

    setDeletingUserId(userId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/users/${userId}`)
      await loadUsers()
      setNotice('User deleted.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete user.'))
    } finally {
      setDeletingUserId(null)
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

  const startEditStatus = (status: LeadStatus) => {
    setEditingStatusId(status.id)
    setEditingStatusName(status.name)
  }

  const cancelEditStatus = () => {
    setEditingStatusId(null)
    setEditingStatusName('')
  }

  const handleSaveStatus = async (statusId: string) => {
    const name = editingStatusName.trim()
    if (!name || savingStatusId) {
      return
    }

    setSavingStatusId(statusId)
    setError('')
    setNotice('')

    try {
      await api.patch<LeadStatus>(`/leads/statuses/${statusId}`, { name })
      cancelEditStatus()
      await loadStatuses()
      setNotice('Lead status updated.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not update status.'))
    } finally {
      setSavingStatusId(null)
    }
  }

  const handleDeleteStatus = async (statusItem: LeadStatus) => {
    if (statusItem.code === 'new' || statusItem.code === 'lost') {
      setError(`Base status '${statusItem.code}' cannot be deleted.`)
      return
    }
    if (!window.confirm(`Delete status "${statusItem.name}"?`)) {
      return
    }

    setDeletingStatusId(statusItem.id)
    setError('')
    setNotice('')

    try {
      await api.delete(`/leads/statuses/${statusItem.id}`)
      await loadStatuses()
      setNotice('Lead status deleted.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete status.'))
    } finally {
      setDeletingStatusId(null)
    }
  }

  const handleAddTag = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!activeProjectId) {
      setError('Select a project before editing tags.')
      return
    }
    if (isAddingTag) {
      return
    }

    setIsAddingTag(true)
    setError('')
    setNotice('')

    try {
      await api.post<ProjectTag>(
        '/tags',
        { name: newTagName.trim() },
        { params: activeProjectId ? { project_id: activeProjectId } : undefined },
      )
      setNewTagName('')
      await loadTags()
      setNotice('Tag added.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add tag.'))
    } finally {
      setIsAddingTag(false)
    }
  }

  const startEditTag = (tag: ProjectTag) => {
    setEditingTagId(tag.id)
    setEditingTagName(tag.name)
  }

  const cancelEditTag = () => {
    setEditingTagId(null)
    setEditingTagName('')
  }

  const handleSaveTag = async (tagId: string) => {
    const name = editingTagName.trim()
    if (!activeProjectId) {
      setError('Select a project before editing tags.')
      return
    }
    if (!name || savingTagId) {
      return
    }

    setSavingTagId(tagId)
    setError('')
    setNotice('')

    try {
      await api.patch<ProjectTag>(
        `/tags/${tagId}`,
        { name },
        { params: activeProjectId ? { project_id: activeProjectId } : undefined },
      )
      cancelEditTag()
      await loadTags()
      setNotice('Tag updated.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not update tag.'))
    } finally {
      setSavingTagId(null)
    }
  }

  const handleDeleteTag = async (tagId: string) => {
    if (!activeProjectId) {
      setError('Select a project before editing tags.')
      return
    }
    if (!window.confirm('Delete this tag?')) {
      return
    }

    setDeletingTagId(tagId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/tags/${tagId}`, {
        params: activeProjectId ? { project_id: activeProjectId } : undefined,
      })
      await loadTags()
      setNotice('Tag deleted.')
    } catch (err) {
      setError(getErrorMessage(err, 'Could not delete tag.'))
    } finally {
      setDeletingTagId(null)
    }
  }

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-2xl md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-zinc-800 p-4 md:w-60 md:border-b-0 md:border-r">
        <div className="mb-5 flex items-center gap-3 px-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-300">
            <Settings size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-zinc-100">Settings</h1>
            <p className="text-xs text-zinc-500">Workspace controls</p>
          </div>
        </div>
        <nav className="flex min-h-0 gap-2 overflow-x-auto md:flex-1 md:flex-col md:space-y-2 md:overflow-x-visible md:overflow-y-auto">
          {visibleTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`shrink-0 rounded-lg px-3 py-2 text-left text-sm font-medium transition md:w-full ${
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

            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-[680px] w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Email</th>
                    <th className="px-4 py-3">Role</th>
                    <th className="w-[88px] px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {users.map((user) => {
                    const role = roles.find((item) => item.id === user.role_id)
                    const canRemove = canDeleteUser(user)
                    return (
                      <tr key={user.id} className="bg-zinc-950">
                        <td className="px-4 py-3 text-zinc-100">{user.name}</td>
                        <td className="px-4 py-3 text-zinc-400">{user.email}</td>
                        <td className="px-4 py-3 text-zinc-400">
                          {role ? roleLabel(role.name) : user.role_id.slice(0, 8)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end">
                            {canRemove ? (
                              <button
                                type="button"
                                title="Delete user"
                                onClick={() => void handleDeleteUser(user.id)}
                                disabled={deletingUserId === user.id}
                                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                              >
                                {deletingUserId === user.id ? (
                                  <LoaderCircle size={15} className="animate-spin" />
                                ) : (
                                  <Trash2 size={15} />
                                )}
                              </button>
                            ) : (
                              <span className="text-xs text-zinc-600">Locked</span>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {canManageStaff ? (
              <form
                className="grid gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_180px_140px]"
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
                  {staffRoles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {roleLabel(role.name)}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  disabled={isAddingUser || staffRoles.length === 0}
                  className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isAddingUser ? <LoaderCircle size={16} className="animate-spin" /> : <UserPlus size={16} />}
                  Add User
                </button>
              </form>
            ) : null}
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
            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-[640px] w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="px-4 py-3">Code</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="w-[112px] px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {statuses.map((statusItem) => {
                    const isEditing = editingStatusId === statusItem.id
                    const isBase = statusItem.code === 'new' || statusItem.code === 'lost'

                    return (
                      <tr key={statusItem.id} className="bg-zinc-950">
                        <td className="px-4 py-3">
                          {isEditing ? (
                            <input
                              value={editingStatusName}
                              onChange={(event) => setEditingStatusName(event.target.value)}
                              maxLength={100}
                              autoFocus
                              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                            />
                          ) : (
                            <span className="font-medium text-zinc-100">
                              {statusItem.name}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-zinc-500">
                          {statusItem.code}
                        </td>
                        <td className="px-4 py-3">
                          {statusItem.is_final ? (
                            <span className="rounded bg-amber-500/15 px-2 py-1 text-xs font-semibold text-amber-300">
                              Final
                            </span>
                          ) : (
                            <span className="rounded bg-zinc-800 px-2 py-1 text-xs font-semibold text-zinc-400">
                              Active
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-2">
                            {isEditing ? (
                              <>
                                <button
                                  type="button"
                                  title="Save status"
                                  onClick={() => void handleSaveStatus(statusItem.id)}
                                  disabled={savingStatusId === statusItem.id}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-emerald-300 transition hover:border-emerald-500/60 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {savingStatusId === statusItem.id ? (
                                    <LoaderCircle size={15} className="animate-spin" />
                                  ) : (
                                    <Check size={15} />
                                  )}
                                </button>
                                <button
                                  type="button"
                                  title="Cancel"
                                  onClick={cancelEditStatus}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-zinc-600 hover:text-zinc-200"
                                >
                                  <X size={15} />
                                </button>
                              </>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  title="Edit status"
                                  onClick={() => startEditStatus(statusItem)}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-emerald-500/60 hover:text-emerald-300"
                                >
                                  <Pencil size={15} />
                                </button>
                                <button
                                  type="button"
                                  title={isBase ? 'Base statuses cannot be deleted' : 'Delete status'}
                                  onClick={() => void handleDeleteStatus(statusItem)}
                                  disabled={isBase || deletingStatusId === statusItem.id}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {deletingStatusId === statusItem.id ? (
                                    <LoaderCircle size={15} className="animate-spin" />
                                  ) : (
                                    <Trash2 size={15} />
                                  )}
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <form
              className="grid gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto]"
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
                className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
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
            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-[520px] w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3">Name</th>
                    <th className="w-[112px] px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-800">
                  {tags.map((tagItem) => {
                    const isEditing = editingTagId === tagItem.id

                    return (
                      <tr key={tagItem.id} className="bg-zinc-950">
                        <td className="px-4 py-3">
                          {isEditing ? (
                            <input
                              value={editingTagName}
                              onChange={(event) => setEditingTagName(event.target.value)}
                              maxLength={100}
                              autoFocus
                              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                            />
                          ) : (
                            <div className="flex items-center gap-2 font-medium text-zinc-100">
                              <Tag size={16} className="text-zinc-500" />
                              {tagItem.name}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-2">
                            {isEditing ? (
                              <>
                                <button
                                  type="button"
                                  title="Save tag"
                                  onClick={() => void handleSaveTag(tagItem.id)}
                                  disabled={savingTagId === tagItem.id}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-emerald-300 transition hover:border-emerald-500/60 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {savingTagId === tagItem.id ? (
                                    <LoaderCircle size={15} className="animate-spin" />
                                  ) : (
                                    <Check size={15} />
                                  )}
                                </button>
                                <button
                                  type="button"
                                  title="Cancel"
                                  onClick={cancelEditTag}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-zinc-600 hover:text-zinc-200"
                                >
                                  <X size={15} />
                                </button>
                              </>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  title="Edit tag"
                                  onClick={() => startEditTag(tagItem)}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-emerald-500/60 hover:text-emerald-300"
                                >
                                  <Pencil size={15} />
                                </button>
                                <button
                                  type="button"
                                  title="Delete tag"
                                  onClick={() => void handleDeleteTag(tagItem.id)}
                                  disabled={deletingTagId === tagItem.id}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-red-500/60 hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {deletingTagId === tagItem.id ? (
                                    <LoaderCircle size={15} className="animate-spin" />
                                  ) : (
                                    <Trash2 size={15} />
                                  )}
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <form
              className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 sm:flex-row"
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
                className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
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

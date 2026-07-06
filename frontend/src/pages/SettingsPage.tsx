import {
  Check,
  ChevronDown,
  FileText,
  KeyRound,
  Languages,
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
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'

import api from '../api/client'
import BuyersSettings from '../features/buyers/components/BuyersSettings'
import GoogleSheetsSettings from '../features/googleSheets/components/GoogleSheetsSettings'
import LandersSettings from '../features/landers/components/LandersSettings'
import PartnersSettings from '../features/partners/components/PartnersSettings'
import { useProjectBotSelection } from '../shared/lib'
import { Modal } from '../shared/ui'
import { useAuthStore } from '../store/authStore'

type TabKey =
  | 'system'
  | 'project'
  | 'team'
  | 'buyers'
  | 'statuses'
  | 'tags'
  | 'partners'
  | 'googleSheets'
  | 'landers'

type PaginatedResponse<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

type Project = {
  id: string
  name: string
  status: 'active' | 'archived'
  sla_threshold_minutes: number
  operator_lang: string
  default_client_lang: string
  is_translation_enabled: boolean
  tracking_lead_status_codes: string[]
  created_at: string
  is_deleted: boolean
}

type User = {
  id: string
  email: string
  name: string
  project_id: string | null
  project_ids?: string[]
  role_id: string
  role_name?: string | null
  is_root?: boolean
  handler_code?: string | null
  telegram_id?: number | null
  created_at: string
  is_deleted: boolean
}

type Role = {
  id: string
  name: 'super_admin' | 'admin' | 'manager' | 'buyer' | 'operator'
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

type TranslationProvider = 'deepl' | 'google' | 'libretranslate'

type TranslationProviderSettings = {
  provider: TranslationProvider | null
  api_key: string | null
  base_url: string | null
}

type SystemGlobalSettings = {
  tg_backup_bot_token: string | null
  tg_backup_channel_id: string | null
  is_tg_backup_enabled: boolean
  admin_bot_token: string | null
}

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'system', label: 'Система' },
  { key: 'project', label: 'Проект' },
  { key: 'team', label: 'Команда' },
  { key: 'buyers', label: 'Баеры' },
  { key: 'statuses', label: 'Статусы' },
  { key: 'tags', label: 'Теги' },
  { key: 'partners', label: 'Партнёры' },
  { key: 'googleSheets', label: 'Google Таблицы' },
  { key: 'landers', label: 'Лендинги и Домены' },
]

const languageOptions = [
  { value: 'ru', label: 'Русский (RU)' },
  { value: 'en', label: 'Английский (EN)' },
  { value: 'es', label: 'Испанский (ES)' },
  { value: 'pt', label: 'Португальский (PT)' },
  { value: 'ar', label: 'Арабский (AR)' },
  { value: 'fr', label: 'Французский (FR)' },
  { value: 'de', label: 'Немецкий (DE)' },
  { value: 'it', label: 'Итальянский (IT)' },
  { value: 'tr', label: 'Турецкий (TR)' },
  { value: 'hi', label: 'Хинди (HI)' },
] as const

const translationProviderOptions: Array<{ value: TranslationProvider; label: string }> = [
  { value: 'deepl', label: 'DeepL' },
  { value: 'google', label: 'Google Translate' },
  { value: 'libretranslate', label: 'LibreTranslate' },
]

const defaultTrackingLeadStatusCodes = ['submitted', 'qualified']

function getErrorMessage(err: unknown, fallback = 'Request failed.') {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
    if (err.code === 'ERR_NETWORK') {
      return 'API недоступен.'
    }
  }

  return fallback
}

function roleLabel(roleName: string) {
  const labels: Record<string, string> = {
    super_admin: 'Суперадмин',
    admin: 'Админ',
    manager: 'Менеджер',
    buyer: 'Баер',
    operator: 'Оператор',
  }
  return labels[roleName] ?? roleName
}

type ProjectAccessDropdownProps = {
  projects: Project[]
  selectedProjectIds: string[]
  disabled?: boolean
  requireOne?: boolean
  onChange: (projectIds: string[]) => void
}

function ProjectAccessDropdown({
  projects,
  selectedProjectIds,
  disabled = false,
  requireOne = false,
  onChange,
}: ProjectAccessDropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const selectedSet = useMemo(() => new Set(selectedProjectIds), [selectedProjectIds])
  const selectedNames = projects
    .filter((project) => selectedSet.has(project.id))
    .map((project) => project.name)
  const label = selectedNames.length === 0
    ? 'Выберите проекты'
    : selectedNames.length === 1
      ? selectedNames[0]
      : `${selectedNames[0]} +${selectedNames.length - 1}`

  useEffect(() => {
    if (!isOpen) {
      return
    }
    const handleOutsidePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('pointerdown', handleOutsidePointerDown)
    return () => document.removeEventListener('pointerdown', handleOutsidePointerDown)
  }, [isOpen])

  const toggleProject = (projectId: string) => {
    const isSelected = selectedSet.has(projectId)
    if (isSelected && requireOne && selectedProjectIds.length <= 1) {
      return
    }
    onChange(
      isSelected
        ? selectedProjectIds.filter((currentId) => currentId !== projectId)
        : [...selectedProjectIds, projectId],
    )
  }

  return (
    <div ref={rootRef} className="relative min-w-[220px]">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        disabled={disabled}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 text-left text-sm text-zinc-100 outline-none ring-emerald-500 transition hover:border-emerald-500/60 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50"
        aria-expanded={isOpen}
      >
        <span className="truncate" title={selectedNames.join(', ')}>{label}</span>
        <ChevronDown size={16} className={`shrink-0 text-zinc-500 transition ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      {isOpen ? (
        <div className="absolute left-0 z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950 shadow-xl">
          <div className="border-b border-zinc-800 px-3 py-2 text-xs text-zinc-500">
            Выбрано: {selectedNames.length}
          </div>
          <div className="max-h-64 overflow-y-auto p-1.5">
            {projects.map((project) => {
              const isSelected = selectedSet.has(project.id)
              const cannotRemoveLast = requireOne && isSelected && selectedProjectIds.length <= 1
              return (
                <label
                  key={project.id}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm text-zinc-200 transition hover:bg-zinc-900"
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={disabled || cannotRemoveLast}
                    onChange={() => toggleProject(project.id)}
                    className="h-4 w-4 rounded border-zinc-700 bg-zinc-950 text-emerald-500 focus:ring-emerald-500"
                  />
                  <span className="min-w-0 flex-1 truncate" title={project.name}>{project.name}</span>
                  {isSelected ? <Check size={15} className="shrink-0 text-emerald-300" /> : null}
                </label>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function SettingsPage() {
  const currentUser = useAuthStore((state) => state.user)
  const { resetBotSelection, selectedProjectId, setSelectedProjectId } = useProjectBotSelection()

  const [activeTab, setActiveTab] = useState<TabKey>('project')
  const [project, setProject] = useState<Project | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [statuses, setStatuses] = useState<LeadStatus[]>([])
  const [tags, setTags] = useState<ProjectTag[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSavingProject, setIsSavingProject] = useState(false)
  const [isSavingTranslation, setIsSavingTranslation] = useState(false)
  const [isSavingTranslationProvider, setIsSavingTranslationProvider] = useState(false)
  const [isSavingGlobalSettings, setIsSavingGlobalSettings] = useState(false)
  const [isRunningBackup, setIsRunningBackup] = useState(false)
  const [isExportingLogs, setIsExportingLogs] = useState(false)
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
  const [passwordUser, setPasswordUser] = useState<User | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [isChangingPassword, setIsChangingPassword] = useState(false)
  const [updatingUserId, setUpdatingUserId] = useState<string | null>(null)
  const [isArchiveProjectOpen, setIsArchiveProjectOpen] = useState(false)
  const [archiveProjectName, setArchiveProjectName] = useState('')
  const [isArchivingProject, setIsArchivingProject] = useState(false)

  const [projectName, setProjectName] = useState('')
  const [slaMinutes, setSlaMinutes] = useState('30')
  const [trackingLeadStatusCodes, setTrackingLeadStatusCodes] = useState<string[]>(
    defaultTrackingLeadStatusCodes,
  )
  const [translationEnabled, setTranslationEnabled] = useState(false)
  const [operatorLang, setOperatorLang] = useState('ru')
  const [defaultClientLang, setDefaultClientLang] = useState('en')
  const [translationProvider, setTranslationProvider] = useState<TranslationProvider>('libretranslate')
  const [translationApiKey, setTranslationApiKey] = useState('')
  const [translationBaseUrl, setTranslationBaseUrl] = useState('')
  const [tgBackupBotToken, setTgBackupBotToken] = useState('')
  const [tgBackupChannelId, setTgBackupChannelId] = useState('')
  const [isTgBackupEnabled, setIsTgBackupEnabled] = useState(false)
  const [adminBotToken, setAdminBotToken] = useState('')
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserName, setNewUserName] = useState('')
  const [newUserPassword, setNewUserPassword] = useState('')
  const [newUserHandlerCode, setNewUserHandlerCode] = useState('')
  const [newUserTelegramId, setNewUserTelegramId] = useState('')
  const [newUserRoleId, setNewUserRoleId] = useState('')
  const [newUserProjectIds, setNewUserProjectIds] = useState<string[]>([])
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
  const canArchiveProject = currentRoleName === 'super_admin'
  const activeProjects = useMemo(
    () => projects.filter((item) => item.status === 'active' && !item.is_deleted),
    [projects],
  )
  const visibleTabs = useMemo(
    () =>
      tabs.filter((tab) => {
        if (tab.key === 'system') {
          return currentRoleName === 'super_admin'
        }
        if (tab.key === 'team') {
          return canManageStaff
        }
        if (tab.key === 'buyers') {
          return canManageStaff
        }
        if (tab.key === 'project') {
          return canManageProject
        }
        if (tab.key === 'partners') {
          return canManageProject
        }
        if (tab.key === 'googleSheets') {
          return canManageProject
        }
        if (tab.key === 'landers') {
          return canManageProject
        }
        return true
      }),
    [canManageProject, canManageStaff, currentRoleName],
  )
  const knownStatusCodes = useMemo(
    () => new Set(statuses.map((statusItem) => statusItem.code)),
    [statuses],
  )
  const unknownTrackingLeadStatusCodes = useMemo(
    () => trackingLeadStatusCodes.filter((code) => !knownStatusCodes.has(code)),
    [knownStatusCodes, trackingLeadStatusCodes],
  )

  const selectedRole = useMemo(
    () => roles.find((role) => role.id === newUserRoleId) ?? null,
    [newUserRoleId, roles],
  )

  const staffRoles = useMemo(
    () =>
      roles.filter((role) => {
        if (currentRoleName === 'super_admin') {
          return true
        }
        if (currentRoleName === 'admin') {
          return role.name === 'manager' || role.name === 'buyer' || role.name === 'operator'
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

  const getUserProjectIds = useCallback((user: User) => {
    const accessIds = user.project_ids ?? []
    const rawIds = accessIds.length > 0 ? accessIds : user.project_id ? [user.project_id] : []
    return rawIds.filter((projectId, index) => rawIds.indexOf(projectId) === index)
  }, [])

  const getProjectName = useCallback(
    (projectId: string) => projects.find((item) => item.id === projectId)?.name ?? projectId.slice(0, 8),
    [projects],
  )

  const canDeleteUser = useCallback(
    (user: User) => {
      if (!canManageStaff || user.id === currentUser?.id) {
        return false
      }

      const targetRoleName = getUserRoleName(user)
      if (currentRoleName === 'super_admin') {
        if (user.is_root && !currentUser?.is_root) {
          return false
        }
        return true
      }

      return (
        currentRoleName === 'admin' &&
        (targetRoleName === 'manager' || targetRoleName === 'buyer' || targetRoleName === 'operator') &&
        Boolean(activeProjectId && getUserProjectIds(user).includes(activeProjectId))
      )
    },
    [
      activeProjectId,
      canManageStaff,
      currentRoleName,
      currentUser?.id,
      currentUser?.is_root,
      getUserRoleName,
      getUserProjectIds,
    ],
  )

  const editableRolesForUser = useCallback(
    (user: User) => {
      if (!canDeleteUser(user)) {
        return []
      }
      if (currentRoleName === 'super_admin') {
        return roles
      }
      if (currentRoleName === 'admin') {
        return roles.filter((role) =>
          role.name === 'manager' || role.name === 'buyer' || role.name === 'operator'
        )
      }
      return []
    },
    [canDeleteUser, currentRoleName, roles],
  )

  const toggleTrackingLeadStatus = useCallback((statusCode: string) => {
    setTrackingLeadStatusCodes((currentCodes) => {
      if (currentCodes.includes(statusCode)) {
        if (currentCodes.length <= 1) {
          return currentCodes
        }
        return currentCodes.filter((code) => code !== statusCode)
      }
      return [...currentCodes, statusCode]
    })
  }, [])

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

  useEffect(() => {
    if (selectedRole?.name === 'super_admin') {
      setNewUserProjectIds([])
      return
    }

    setNewUserProjectIds((currentIds) => {
      const allowedIds = activeProjects.map((item) => item.id)
      const filteredIds = currentIds.filter((projectId) => allowedIds.includes(projectId))
      if (filteredIds.length > 0) {
        return filteredIds
      }
      if (activeProjectId && allowedIds.includes(activeProjectId)) {
        return [activeProjectId]
      }
      return allowedIds[0] ? [allowedIds[0]] : []
    })
  }, [activeProjectId, activeProjects, selectedRole?.name])

  const loadProject = useCallback(async () => {
    if (!activeProjectId) {
      setProject(null)
      return
    }

    const { data } = await api.get<Project>(`/projects/${activeProjectId}`)
    setProject(data)
    setProjectName(data.name)
    setSlaMinutes(String(data.sla_threshold_minutes))
    setTrackingLeadStatusCodes(
      data.tracking_lead_status_codes?.length
        ? data.tracking_lead_status_codes
        : defaultTrackingLeadStatusCodes,
    )
    setTranslationEnabled(data.is_translation_enabled)
    setOperatorLang(data.operator_lang || 'ru')
    setDefaultClientLang(data.default_client_lang || 'en')
  }, [activeProjectId])

  const loadProjects = useCallback(async () => {
    const { data } = await api.get<PaginatedResponse<Project>>('/projects', {
      params: { limit: 100, offset: 0 },
    })
    setProjects(data.items)
  }, [])

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

  const loadTranslationProviderSettings = useCallback(async () => {
    if (!canManageProject) {
      return
    }
    const { data } = await api.get<TranslationProviderSettings>('/settings/translation')
    setTranslationProvider(data.provider ?? 'libretranslate')
    setTranslationApiKey(data.api_key ?? '')
    setTranslationBaseUrl(data.base_url ?? '')
  }, [canManageProject])

  const loadGlobalSettings = useCallback(async () => {
    if (currentRoleName !== 'super_admin') {
      return
    }
    const { data } = await api.get<SystemGlobalSettings>('/settings/global')
    setTgBackupBotToken(data.tg_backup_bot_token ?? '')
    setTgBackupChannelId(data.tg_backup_channel_id ?? '')
    setIsTgBackupEnabled(data.is_tg_backup_enabled)
    setAdminBotToken(data.admin_bot_token ?? '')
  }, [currentRoleName])

  const loadAll = useCallback(async () => {
    setIsLoading(true)
    setError('')

    try {
      await Promise.all([
        loadProject(),
        loadProjects(),
        loadUsers(),
        loadRoles(),
        loadStatuses(),
        loadTags(),
        loadTranslationProviderSettings(),
        loadGlobalSettings(),
      ])
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось загрузить настройки.'))
    } finally {
      setIsLoading(false)
    }
  }, [
    loadProject,
    loadProjects,
    loadRoles,
    loadStatuses,
    loadTags,
    loadTranslationProviderSettings,
    loadGlobalSettings,
    loadUsers,
  ])

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
        tracking_lead_status_codes: trackingLeadStatusCodes,
      })
      setProject(data)
      setProjectName(data.name)
      setSlaMinutes(String(data.sla_threshold_minutes))
      setTrackingLeadStatusCodes(
        data.tracking_lead_status_codes?.length
          ? data.tracking_lead_status_codes
          : defaultTrackingLeadStatusCodes,
      )
      setNotice('Настройки проекта сохранены.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось сохранить проект.'))
    } finally {
      setIsSavingProject(false)
    }
  }

  const handleTranslationSave = async () => {
    if (!project || isSavingTranslation) {
      return
    }

    setIsSavingTranslation(true)
    setError('')
    setNotice('')

    try {
      const { data } = await api.patch<Project>(
        `/projects/${project.id}/translation-settings`,
        {
          operator_lang: operatorLang,
          default_client_lang: defaultClientLang,
          is_translation_enabled: translationEnabled,
        },
      )
      setProject(data)
      setTranslationEnabled(data.is_translation_enabled)
      setOperatorLang(data.operator_lang)
      setDefaultClientLang(data.default_client_lang)
      setNotice('Настройки перевода сохранены.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось сохранить настройки перевода.'))
    } finally {
      setIsSavingTranslation(false)
    }
  }

  const handleTranslationProviderSave = async () => {
    if (isSavingTranslationProvider) {
      return
    }

    setIsSavingTranslationProvider(true)
    setError('')
    setNotice('')

    try {
      const { data } = await api.patch<TranslationProviderSettings>('/settings/translation', {
        provider: translationProvider,
        api_key: translationApiKey.trim() || null,
        base_url: translationBaseUrl.trim() || null,
      })
      setTranslationProvider(data.provider ?? 'libretranslate')
      setTranslationApiKey(data.api_key ?? '')
      setTranslationBaseUrl(data.base_url ?? '')
      setNotice('Провайдер перевода сохранён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось сохранить провайдера перевода.'))
    } finally {
      setIsSavingTranslationProvider(false)
    }
  }

  const handleGlobalSettingsSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (isSavingGlobalSettings) {
      return
    }
    setIsSavingGlobalSettings(true)
    setError('')
    setNotice('')
    try {
      const { data } = await api.patch<SystemGlobalSettings>('/settings/global', {
        tg_backup_bot_token: tgBackupBotToken.trim() || null,
        tg_backup_channel_id: tgBackupChannelId.trim() || null,
        is_tg_backup_enabled: isTgBackupEnabled,
        admin_bot_token: adminBotToken.trim() || null,
      })
      setTgBackupBotToken(data.tg_backup_bot_token ?? '')
      setTgBackupChannelId(data.tg_backup_channel_id ?? '')
      setIsTgBackupEnabled(data.is_tg_backup_enabled)
      setAdminBotToken(data.admin_bot_token ?? '')
      setNotice('Глобальные настройки сохранены.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось сохранить глобальные настройки.'))
    } finally {
      setIsSavingGlobalSettings(false)
    }
  }

  const handleRunBackup = async () => {
    if (!currentUser?.is_root || isRunningBackup) {
      return
    }
    setIsRunningBackup(true)
    setError('')
    setNotice('')
    try {
      const { data } = await api.post<{ job_id: string }>('/settings/global/backup/run')
      setNotice(`Бэкап поставлен в очередь: ${data.job_id}`)
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось запустить резервное копирование.'))
    } finally {
      setIsRunningBackup(false)
    }
  }

  const handleExportServerLogs = async () => {
    if (currentRoleName !== 'super_admin' || isExportingLogs) {
      return
    }
    setIsExportingLogs(true)
    setError('')
    setNotice('')
    try {
      const { data } = await api.post<{ file_name: string; size_bytes: number }>(
        '/settings/global/logs/export',
      )
      setNotice(
        `Логи за последние 30 минут отправлены: ${data.file_name} (${Math.ceil(data.size_bytes / 1024)} КБ).`,
      )
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось отправить серверные логи.'))
    } finally {
      setIsExportingLogs(false)
    }
  }

  const handleArchiveProject = async () => {
    if (!project || archiveProjectName !== project.name || isArchivingProject) {
      return
    }

    setIsArchivingProject(true)
    setError('')
    setNotice('')

    try {
      await api.delete(`/projects/${project.id}`)
      setIsArchiveProjectOpen(false)
      setArchiveProjectName('')
      setProject(null)
      setProjectName('')
      resetBotSelection()
      setSelectedProjectId(null)
      setNotice('Проект архивирован. Данные скрыты из рабочего интерфейса, но не удалены физически.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось архивировать проект.'))
    } finally {
      setIsArchivingProject(false)
    }
  }

  const handleAddUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (
      !newUserRoleId ||
      !canManageStaff ||
      !staffRoles.some((role) => role.id === newUserRoleId) ||
      (selectedRole?.name !== 'super_admin' && newUserProjectIds.length === 0) ||
      isAddingUser
    ) {
      return
    }
    const handlerCode = newUserHandlerCode.trim()
    if (handlerCode && !/^\d{4}$/.test(handlerCode)) {
      setError('Код обработчика должен состоять из четырёх цифр.')
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
        project_id: selectedRole?.name === 'super_admin' ? null : newUserProjectIds[0],
        project_ids: selectedRole?.name === 'super_admin' ? [] : newUserProjectIds,
        handler_code: handlerCode || null,
        telegram_id: newUserTelegramId.trim() ? Number(newUserTelegramId) : null,
      })
      setNewUserEmail('')
      setNewUserName('')
      setNewUserPassword('')
      setNewUserHandlerCode('')
      setNewUserTelegramId('')
      setNewUserProjectIds(activeProjectId ? [activeProjectId] : [])
      await loadUsers()
      setNotice('Пользователь добавлен.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось добавить пользователя.'))
    } finally {
      setIsAddingUser(false)
    }
  }

  const handleDeleteUser = async (userId: string) => {
    const targetUser = users.find((user) => user.id === userId)
    if (!targetUser || !canDeleteUser(targetUser)) {
      setError('Недостаточно прав для архивирования пользователя.')
      return
    }

    if (!window.confirm('Архивировать этого пользователя?')) {
      return
    }

    setDeletingUserId(userId)
    setError('')
    setNotice('')

    try {
      await api.delete(`/users/${userId}`)
      await loadUsers()
      setNotice('Пользователь архивирован.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось архивировать пользователя.'))
    } finally {
      setDeletingUserId(null)
    }
  }

  const handleUserRoleChange = async (user: User, roleId: string) => {
    const role = roles.find((item) => item.id === roleId)
    if (!role || !canDeleteUser(user)) {
      setError('Недостаточно прав для изменения роли.')
      return
    }
    const projectIds =
      role.name === 'super_admin'
        ? []
        : getUserProjectIds(user).length > 0
          ? getUserProjectIds(user)
          : activeProjectId
            ? [activeProjectId]
            : []
    if (role.name !== 'super_admin' && projectIds.length === 0) {
      setError('Выберите хотя бы один проект перед назначением проектной роли.')
      return
    }

    setUpdatingUserId(user.id)
    setError('')
    setNotice('')

    try {
      await api.patch<User>(`/users/${user.id}`, {
        role_id: roleId,
        project_id: role.name === 'super_admin' ? null : projectIds[0],
        project_ids: projectIds,
      })
      await loadUsers()
      setNotice('Роль пользователя обновлена.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось изменить роль.'))
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleUserHandlerCodeChange = async (user: User, rawValue: string) => {
    if (!canDeleteUser(user)) {
      setError('Недостаточно прав для изменения кода обработчика.')
      return
    }
    const handlerCode = rawValue.replace(/\D/g, '').slice(0, 4)
    if (handlerCode === (user.handler_code ?? '')) {
      return
    }
    if (handlerCode && !/^\d{4}$/.test(handlerCode)) {
      setError('Код обработчика должен состоять из четырёх цифр.')
      return
    }

    setUpdatingUserId(user.id)
    setError('')
    setNotice('')
    try {
      await api.patch<User>(`/users/${user.id}`, {
        handler_code: handlerCode || null,
      })
      await loadUsers()
      setNotice('Код обработчика обновлён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось обновить код обработчика.'))
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleUserTelegramIdChange = async (user: User, rawValue: string) => {
    if (!canDeleteUser(user)) {
      setError('Недостаточно прав для изменения Telegram ID.')
      return
    }
    const normalized = rawValue.replace(/\D/g, '')
    const telegramId = normalized ? Number(normalized) : null
    if (telegramId === (user.telegram_id ?? null)) {
      return
    }
    setUpdatingUserId(user.id)
    setError('')
    setNotice('')
    try {
      await api.patch<User>(`/users/${user.id}`, { telegram_id: telegramId })
      await loadUsers()
      setNotice('Telegram ID обновлён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось обновить Telegram ID.'))
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleUserProjectAccessChange = async (
    user: User,
    nextProjectIds: string[],
  ) => {
    const roleName = getUserRoleName(user)
    if (roleName === 'super_admin') {
      setError('Суперадмин имеет доступ ко всем проектам.')
      return
    }
    if (!canDeleteUser(user)) {
      setError('Недостаточно прав для изменения доступов.')
      return
    }

    const uniqueProjectIds = nextProjectIds.filter(
      (projectId, index, projectIds) => projectIds.indexOf(projectId) === index,
    )

    if (uniqueProjectIds.length === 0) {
      setError('У пользователя должен остаться хотя бы один проект.')
      return
    }

    setUpdatingUserId(user.id)
    setError('')
    setNotice('')

    try {
      await api.patch<User>(`/users/${user.id}`, {
        project_id: uniqueProjectIds[0],
        project_ids: uniqueProjectIds,
      })
      await loadUsers()
      setNotice('Доступы пользователя обновлены.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось изменить доступы.'))
    } finally {
      setUpdatingUserId(null)
    }
  }

  const handleChangePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!passwordUser || isChangingPassword) {
      return
    }

    setIsChangingPassword(true)
    setError('')
    setNotice('')

    try {
      await api.post(`/users/${passwordUser.id}/change-password`, {
        new_password: newPassword,
      })
      setPasswordUser(null)
      setNewPassword('')
      setNotice('Пароль пользователя изменён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось изменить пароль.'))
    } finally {
      setIsChangingPassword(false)
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
      setNotice('Статус лида добавлен.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось добавить статус.'))
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
      setNotice('Статус лида обновлён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось обновить статус.'))
    } finally {
      setSavingStatusId(null)
    }
  }

  const handleDeleteStatus = async (statusItem: LeadStatus) => {
    if (statusItem.code === 'new' || statusItem.code === 'lost') {
      setError(`Базовый статус "${statusItem.code}" нельзя удалить.`)
      return
    }
    if (!window.confirm(`Удалить статус "${statusItem.name}"?`)) {
      return
    }

    setDeletingStatusId(statusItem.id)
    setError('')
    setNotice('')

    try {
      await api.delete(`/leads/statuses/${statusItem.id}`)
      await loadStatuses()
      setNotice('Статус лида удалён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось удалить статус.'))
    } finally {
      setDeletingStatusId(null)
    }
  }

  const handleAddTag = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!activeProjectId) {
      setError('Выберите проект перед редактированием тегов.')
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
      setNotice('Тег добавлен.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось добавить тег.'))
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
      setError('Выберите проект перед редактированием тегов.')
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
      setNotice('Тег обновлён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось обновить тег.'))
    } finally {
      setSavingTagId(null)
    }
  }

  const handleDeleteTag = async (tagId: string) => {
    if (!activeProjectId) {
      setError('Выберите проект перед редактированием тегов.')
      return
    }
    if (!window.confirm('Удалить этот тег?')) {
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
      setNotice('Тег удалён.')
    } catch (err) {
      setError(getErrorMessage(err, 'Не удалось удалить тег.'))
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
            <h1 className="text-lg font-semibold text-zinc-100">Настройки</h1>
            <p className="text-xs text-zinc-500">Управление рабочей областью</p>
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

      <div className="min-w-0 flex-1 overscroll-contain overflow-y-auto p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] md:p-6">
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
            Загрузка настроек
          </div>
        ) : null}

        {!isLoading && activeTab === 'system' ? (
          <form className="max-w-xl space-y-6" onSubmit={handleGlobalSettingsSave}>
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Глобальные настройки</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Системные Telegram-боты и ежедневные резервные копии.
              </p>
            </div>

            <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/45 p-4">
              <div>
                <h3 className="text-sm font-semibold text-zinc-100">Резервные копии в Telegram</h3>
                <p className="mt-1 text-sm leading-6 text-zinc-500">
                  ARQ создаёт сжатый PostgreSQL dump ежедневно в 03:00 UTC и отправляет его в канал.
                </p>
              </div>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Токен backup-бота</span>
                <input
                  type="password"
                  value={tgBackupBotToken}
                  onChange={(event) => setTgBackupBotToken(event.target.value)}
                  autoComplete="off"
                  placeholder="1234567890:AA..."
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
              </label>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">ID канала</span>
                <input
                  value={tgBackupChannelId}
                  onChange={(event) => setTgBackupChannelId(event.target.value)}
                  placeholder="-1001234567890"
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
              </label>
              <label className="flex items-center justify-between gap-4 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-3">
                <span>
                  <span className="block text-sm font-medium text-zinc-200">Ежедневный backup включён</span>
                  <span className="mt-1 block text-xs text-zinc-500">Cron запускается в 03:00 UTC.</span>
                </span>
                <input
                  type="checkbox"
                  checked={isTgBackupEnabled}
                  onChange={(event) => setIsTgBackupEnabled(event.target.checked)}
                  className="h-5 w-5 shrink-0 accent-emerald-500"
                />
              </label>
            </div>

            <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/45 p-4">
              <div>
                <h3 className="text-sm font-semibold text-zinc-100">Admin Telegram Bot</h3>
                <p className="mt-1 text-sm leading-6 text-zinc-500">
                  Команда /stats и автоматические алерты при переходе ссылки в low_cr.
                </p>
              </div>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-zinc-300">Токен admin-бота</span>
                <input
                  type="password"
                  value={adminBotToken}
                  onChange={(event) => setAdminBotToken(event.target.value)}
                  autoComplete="off"
                  placeholder="1234567890:AA..."
                  className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
              </label>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="submit"
                disabled={isSavingGlobalSettings}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:opacity-50"
              >
                {isSavingGlobalSettings ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                Сохранить
              </button>
              {currentUser?.is_root ? (
                <button
                  type="button"
                  onClick={() => void handleRunBackup()}
                  disabled={isRunningBackup}
                  className="inline-flex items-center gap-2 rounded-lg border border-cyan-400/35 px-4 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-500/10 disabled:opacity-50"
                >
                  {isRunningBackup ? <LoaderCircle size={16} className="animate-spin" /> : <Settings size={16} />}
                  Запустить backup сейчас
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => void handleExportServerLogs()}
                disabled={isExportingLogs || !tgBackupBotToken.trim() || !tgBackupChannelId.trim()}
                className="inline-flex items-center gap-2 rounded-lg border border-amber-300/30 px-4 py-2 text-sm font-semibold text-amber-100 transition hover:bg-amber-400/10 disabled:cursor-not-allowed disabled:opacity-50"
                title="Отправить в backup-канал логи приложения за последние 30 минут"
              >
                {isExportingLogs ? <LoaderCircle size={16} className="animate-spin" /> : <FileText size={16} />}
                Отправить логи за 30 минут
              </button>
            </div>
          </form>
        ) : null}

        {!isLoading && activeTab === 'project' ? (
          <form className="max-w-xl space-y-4" onSubmit={handleProjectSave}>
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Проект</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Базовые настройки CRM-проекта.
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
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/45 p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-zinc-100">
                    Лид в трекинге
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-zinc-500">
                    Старты считаются отдельно. Метрика “Лиды”, CPL и CR до лида
                    считаются только по выбранным статусам.
                  </p>
                </div>
                <span className="rounded-full border border-cyan-400/25 bg-cyan-500/10 px-2.5 py-1 text-xs font-medium text-cyan-100">
                  {trackingLeadStatusCodes.length}
                </span>
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {statuses.map((statusItem) => {
                  const isSelected = trackingLeadStatusCodes.includes(statusItem.code)
                  const isLastSelected = isSelected && trackingLeadStatusCodes.length <= 1
                  return (
                    <label
                      key={statusItem.id}
                      className="flex cursor-pointer items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-2.5 text-sm text-zinc-200 transition hover:border-emerald-500/40"
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={isLastSelected}
                        onChange={() => toggleTrackingLeadStatus(statusItem.code)}
                        className="h-5 w-5 rounded border-zinc-700 bg-zinc-950 text-emerald-500 focus:ring-emerald-500 disabled:cursor-not-allowed"
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{statusItem.name}</span>
                        <span className="block truncate text-xs text-zinc-500">
                          {statusItem.code}
                        </span>
                      </span>
                    </label>
                  )
                })}
                {unknownTrackingLeadStatusCodes.map((statusCode) => {
                  const isLastSelected = trackingLeadStatusCodes.length <= 1
                  return (
                    <label
                      key={`unknown-${statusCode}`}
                      className="flex cursor-pointer items-center gap-3 rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2.5 text-sm text-amber-100 transition hover:border-amber-400/60"
                    >
                      <input
                        type="checkbox"
                        checked
                        disabled={isLastSelected}
                        onChange={() => toggleTrackingLeadStatus(statusCode)}
                        className="h-5 w-5 rounded border-amber-500/60 bg-zinc-950 text-amber-400 focus:ring-amber-400 disabled:cursor-not-allowed"
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">Статус не найден</span>
                        <span className="block truncate text-xs text-amber-100/65">
                          {statusCode}
                        </span>
                      </span>
                    </label>
                  )
                })}
              </div>
              {unknownTrackingLeadStatusCodes.length > 0 ? (
                <p className="mt-3 text-sm leading-5 text-amber-100/80">
                  В проекте сохранены коды статусов, которых нет в справочнике. Снимите их или создайте соответствующие статусы.
                </p>
              ) : null}
              {statuses.length === 0 ? (
                <p className="mt-3 text-sm text-zinc-500">
                  Статусы пока не загружены. Повторите после обновления страницы.
                </p>
              ) : null}
            </div>
            <button
              type="submit"
              disabled={!project || isSavingProject}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSavingProject ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
              Сохранить проект
            </button>
            <div className="mt-8 space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/45 p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-500/15 text-sky-200">
                  <Languages size={18} />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">
                    Двусторонний перевод сообщений
                  </h3>
                  <p className="mt-1 text-sm leading-6 text-zinc-500">
                    Настройки языков для автоматического перевода входящих и исходящих сообщений.
                  </p>
                </div>
              </div>
              <label className="flex items-center justify-between gap-4 rounded-lg border border-zinc-800 bg-zinc-950/70 px-3 py-3">
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-zinc-200">
                    Включить автоматический перевод
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-zinc-500">
                    Входящие сообщения переводятся оператору, исходящие — клиенту.
                  </span>
                </span>
                <input
                  type="checkbox"
                  checked={translationEnabled}
                  onChange={(event) => setTranslationEnabled(event.target.checked)}
                  className="h-5 w-5 shrink-0 accent-emerald-500"
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-zinc-300">
                    Язык операторов
                  </span>
                  <select
                    value={operatorLang}
                    onChange={(event) => setOperatorLang(event.target.value)}
                    className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                  >
                    {languageOptions.map((language) => (
                      <option key={language.value} value={language.value}>
                        {language.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm font-medium text-zinc-300">
                    Язык клиентов по умолчанию
                  </span>
                  <select
                    value={defaultClientLang}
                    onChange={(event) => setDefaultClientLang(event.target.value)}
                    className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                  >
                    {languageOptions.map((language) => (
                      <option key={language.value} value={language.value}>
                        {language.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <button
                type="button"
                onClick={() => void handleTranslationSave()}
                disabled={!project || isSavingTranslation}
                className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/35 px-4 py-2 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSavingTranslation ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                Сохранить настройки перевода
              </button>
              <div className="border-t border-zinc-800 pt-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-violet-200">
                    <KeyRound size={18} />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-zinc-100">
                      Провайдер перевода
                    </h4>
                    <p className="mt-1 text-sm leading-6 text-zinc-500">
                      API, через который выполняется реальный перевод сообщений.
                    </p>
                  </div>
                </div>
                <div className="mt-4 grid gap-4">
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-zinc-300">
                      Провайдер
                    </span>
                    <select
                      value={translationProvider}
                      onChange={(event) =>
                        setTranslationProvider(event.target.value as TranslationProvider)
                      }
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
                    >
                      {translationProviderOptions.map((provider) => (
                        <option key={provider.value} value={provider.value}>
                          {provider.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-zinc-300">
                      API ключ
                    </span>
                    <input
                      type="password"
                      value={translationApiKey}
                      onChange={(event) => setTranslationApiKey(event.target.value)}
                      autoComplete="off"
                      placeholder={
                        translationProvider === 'libretranslate'
                          ? 'Необязательно для self-hosted без ключа'
                          : 'Ключ API переводчика'
                      }
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1 block text-sm font-medium text-zinc-300">
                      Base URL
                    </span>
                    <input
                      value={translationBaseUrl}
                      onChange={(event) => setTranslationBaseUrl(event.target.value)}
                      placeholder={
                        translationProvider === 'libretranslate'
                          ? 'https://libretranslate.example.com'
                          : 'Оставьте пустым для стандартного API'
                      }
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                    />
                  </label>
                </div>
                <button
                  type="button"
                  onClick={() => void handleTranslationProviderSave()}
                  disabled={isSavingTranslationProvider}
                  className="mt-4 inline-flex items-center gap-2 rounded-lg border border-violet-400/35 px-4 py-2 text-sm font-semibold text-violet-100 transition hover:bg-violet-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isSavingTranslationProvider ? (
                    <LoaderCircle size={16} className="animate-spin" />
                  ) : (
                    <Save size={16} />
                  )}
                  Сохранить провайдера
                </button>
              </div>
            </div>
            {canArchiveProject && project ? (
              <div className="mt-8 rounded-xl border border-red-500/25 bg-red-950/20 p-4">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-red-100">Danger zone</h3>
                    <p className="mt-1 text-sm leading-6 text-red-100/70">
                      Архивирование скрывает проект, ботов, чаты, лидов, ссылки и воронки из
                      рабочего интерфейса. Физически данные не удаляются.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setArchiveProjectName('')
                      setIsArchiveProjectOpen(true)
                    }}
                    className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-red-400/40 px-3 py-2 text-sm font-semibold text-red-100 transition hover:bg-red-500/10"
                  >
                    <Trash2 size={15} />
                    Удалить проект
                  </button>
                </div>
              </div>
            ) : null}
          </form>
        ) : null}

        {!isLoading && activeTab === 'team' ? (
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-semibold text-zinc-100">Команда</h2>
                <p className="mt-1 text-sm text-zinc-500">
                  Пользователи и доступы к проектам.
                </p>
              </div>

              <div className="overflow-x-auto rounded-lg border border-zinc-800">
                <table className="min-w-[1280px] w-full text-left text-sm">
                  <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                    <tr>
                      <th className="px-4 py-3">Имя</th>
                      <th className="px-4 py-3">Email</th>
                      <th className="px-4 py-3">Код</th>
                      <th className="px-4 py-3">Telegram ID</th>
                      <th className="px-4 py-3">Роль</th>
                      <th className="px-4 py-3">Доступы</th>
                      <th className="w-[132px] px-4 py-3 text-right">Действия</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800">
                    {users.map((user) => {
                      const role = roles.find((item) => item.id === user.role_id)
                      const canRemove = canDeleteUser(user)
                      const editableRoles = editableRolesForUser(user)
                      const userProjectIds = getUserProjectIds(user)
                      const roleName = getUserRoleName(user)
                      const canEditProjectAccess =
                        canRemove && roleName !== 'super_admin' && activeProjects.length > 0
                      return (
                        <tr key={user.id} className="bg-zinc-950">
                          <td className="px-4 py-3 text-zinc-100">{user.name}</td>
                          <td className="px-4 py-3 text-zinc-400">{user.email}</td>
                          <td className="px-4 py-3">
                            <input
                              key={`${user.id}-${user.handler_code ?? 'empty'}`}
                              defaultValue={user.handler_code ?? ''}
                              inputMode="numeric"
                              maxLength={4}
                              placeholder="0001"
                              disabled={!canRemove || updatingUserId === user.id}
                              onChange={(event) => {
                                event.currentTarget.value = event.currentTarget.value.replace(/\D/g, '').slice(0, 4)
                              }}
                              onBlur={(event) => void handleUserHandlerCodeChange(user, event.currentTarget.value)}
                              className="w-20 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-center font-mono text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 disabled:cursor-not-allowed disabled:opacity-50"
                            />
                          </td>
                          <td className="px-4 py-3">
                            <input
                              key={`${user.id}-${user.telegram_id ?? 'empty'}-telegram`}
                              defaultValue={user.telegram_id ?? ''}
                              inputMode="numeric"
                              placeholder="123456789"
                              disabled={!canRemove || updatingUserId === user.id}
                              onChange={(event) => {
                                event.currentTarget.value = event.currentTarget.value.replace(/\D/g, '')
                              }}
                              onBlur={(event) => void handleUserTelegramIdChange(user, event.currentTarget.value)}
                              className="w-32 rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 font-mono text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 disabled:opacity-50"
                            />
                          </td>
                          <td className="px-4 py-3 text-zinc-400">
                            {editableRoles.length > 0 ? (
                              <select
                                value={user.role_id}
                                onChange={(event) =>
                                  void handleUserRoleChange(user, event.target.value)
                                }
                                disabled={updatingUserId === user.id}
                                className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2 disabled:opacity-50"
                              >
                                {editableRoles.map((item) => (
                                  <option key={item.id} value={item.id}>
                                    {roleLabel(item.name)}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              role ? roleLabel(role.name) : user.role_id.slice(0, 8)
                            )}
                          </td>
                          <td className="min-w-[340px] px-4 py-3">
                            {roleName === 'super_admin' ? (
                              <span className="inline-flex rounded-full border border-cyan-400/25 bg-cyan-500/10 px-2.5 py-1 text-xs font-semibold text-cyan-200">
                                Все проекты
                              </span>
                            ) : canEditProjectAccess ? (
                              <ProjectAccessDropdown
                                projects={activeProjects}
                                selectedProjectIds={userProjectIds}
                                disabled={updatingUserId === user.id}
                                requireOne
                                onChange={(nextProjectIds) =>
                                  void handleUserProjectAccessChange(user, nextProjectIds)
                                }
                              />
                            ) : userProjectIds.length > 0 ? (
                              <div className="flex flex-wrap gap-1.5">
                                {userProjectIds.map((projectId) => (
                                  <span
                                    key={projectId}
                                    className="rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-xs text-zinc-300"
                                  >
                                    {getProjectName(projectId)}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <span className="text-xs text-zinc-600">Нет доступа</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex justify-end gap-2">
                              {canRemove ? (
                                <>
                                  <button
                                    type="button"
                                    title="Изменить пароль"
                                    onClick={() => setPasswordUser(user)}
                                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-emerald-500/60 hover:text-emerald-300"
                                  >
                                    <KeyRound size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    title="Архивировать пользователя"
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
                                </>
                              ) : (
                                <span className="text-xs text-zinc-600">Недоступно</span>
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
                className="grid gap-3 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 md:grid-cols-2 xl:grid-cols-4"
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
                  value={newUserHandlerCode}
                  onChange={(event) => setNewUserHandlerCode(event.target.value.replace(/\D/g, '').slice(0, 4))}
                  inputMode="numeric"
                  maxLength={4}
                  placeholder="Код 0001"
                  className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-base font-mono text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
                />
                <input
                  value={newUserTelegramId}
                  onChange={(event) => setNewUserTelegramId(event.target.value.replace(/\D/g, ''))}
                  inputMode="numeric"
                  placeholder="Telegram ID админа"
                  className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
                <input
                  value={newUserName}
                  onChange={(event) => setNewUserName(event.target.value)}
                  placeholder="Имя"
                  required
                  className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition placeholder:text-zinc-600 focus:ring-2"
                />
                <input
                  type="password"
                  value={newUserPassword}
                  onChange={(event) => setNewUserPassword(event.target.value)}
                  placeholder="Пароль"
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
                  disabled={
                    isAddingUser ||
                    staffRoles.length === 0 ||
                    (selectedRole?.name !== 'super_admin' && newUserProjectIds.length === 0)
                  }
                  className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isAddingUser ? <LoaderCircle size={16} className="animate-spin" /> : <UserPlus size={16} />}
                  Добавить
                </button>
                {selectedRole?.name === 'super_admin' ? (
                  <div className="rounded-lg border border-cyan-400/20 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100 md:col-span-2 xl:col-span-4">
                    Суперадмин получает доступ ко всем проектам автоматически.
                  </div>
                ) : (
                  <div className="md:col-span-2 xl:col-span-4">
                    <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-zinc-500">
                      Доступы к проектам
                    </span>
                    {activeProjects.length > 0 ? (
                      <ProjectAccessDropdown
                        projects={activeProjects}
                        selectedProjectIds={newUserProjectIds}
                        onChange={setNewUserProjectIds}
                      />
                    ) : (
                      <p className="text-sm text-zinc-500">Активных проектов нет.</p>
                    )}
                  </div>
                )}
                </form>
              ) : null}
          </div>
        ) : null}

        {!isLoading && activeTab === 'buyers' ? (
          <BuyersSettings projectId={activeProjectId} />
        ) : null}

        {!isLoading && activeTab === 'statuses' ? (
          <div className="max-w-3xl space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Статусы</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Статусы, по которым движутся лиды.
              </p>
            </div>
            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-[640px] w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3">Название</th>
                    <th className="px-4 py-3">Код</th>
                    <th className="px-4 py-3">Тип</th>
                    <th className="w-[112px] px-4 py-3 text-right">Действия</th>
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
                              Финальный
                            </span>
                          ) : (
                            <span className="rounded bg-zinc-800 px-2 py-1 text-xs font-semibold text-zinc-400">
                              Активный
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-2">
                            {isEditing ? (
                              <>
                                <button
                                  type="button"
                                  title="Сохранить статус"
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
                                  title="Отмена"
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
                                  title="Редактировать статус"
                                  onClick={() => startEditStatus(statusItem)}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-emerald-500/60 hover:text-emerald-300"
                                >
                                  <Pencil size={15} />
                                </button>
                                <button
                                  type="button"
                                  title={isBase ? 'Базовые статусы нельзя удалить' : 'Удалить статус'}
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
                placeholder="Название статуса"
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
                Финальный
              </label>
              <button
                type="submit"
                disabled={isAddingStatus}
                className="inline-flex min-h-10 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isAddingStatus ? <LoaderCircle size={16} className="animate-spin" /> : <Plus size={16} />}
                Добавить
              </button>
            </form>
          </div>
        ) : null}

        {!isLoading && activeTab === 'tags' ? (
          <div className="max-w-3xl space-y-6">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">Теги</h2>
              <p className="mt-1 text-sm text-zinc-500">
                Метки проекта для лидов и чатов.
              </p>
            </div>
            <div className="overflow-x-auto rounded-lg border border-zinc-800">
              <table className="min-w-[520px] w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase tracking-wide text-zinc-500">
                  <tr>
                    <th className="px-4 py-3">Название</th>
                    <th className="w-[112px] px-4 py-3 text-right">Действия</th>
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
                                  title="Сохранить тег"
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
                                  title="Отмена"
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
                                  title="Редактировать тег"
                                  onClick={() => startEditTag(tagItem)}
                                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 transition hover:border-emerald-500/60 hover:text-emerald-300"
                                >
                                  <Pencil size={15} />
                                </button>
                                <button
                                  type="button"
                                  title="Удалить тег"
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
                placeholder="Новый тег"
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
                Добавить тег
              </button>
            </form>
          </div>
        ) : null}

        {!isLoading && activeTab === 'partners' ? (
          <PartnersSettings projectId={activeProjectId} />
        ) : null}

        {!isLoading && activeTab === 'googleSheets' ? (
          <GoogleSheetsSettings projectId={activeProjectId} />
        ) : null}

        {!isLoading && activeTab === 'landers' ? (
          <LandersSettings projectId={activeProjectId} />
        ) : null}
      </div>

      {isArchiveProjectOpen && project ? (
        <Modal title="Архивировать проект" onClose={() => setIsArchiveProjectOpen(false)}>
          <div className="space-y-4 text-sm text-zinc-300">
            <p>
              Проект будет архивирован. Боты, чаты, лиды, ссылки и воронки будут скрыты
              из рабочего интерфейса, но не удалены физически.
            </p>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Введите точное название проекта
              </span>
              <input
                value={archiveProjectName}
                onChange={(event) => setArchiveProjectName(event.target.value)}
                placeholder={project.name}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-red-500 transition focus:ring-2"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsArchiveProjectOpen(false)}
                disabled={isArchivingProject}
                className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => void handleArchiveProject()}
                disabled={archiveProjectName !== project.name || isArchivingProject}
                className="inline-flex items-center gap-2 rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isArchivingProject ? <LoaderCircle size={16} className="animate-spin" /> : <Trash2 size={16} />}
                Архивировать
              </button>
            </div>
          </div>
        </Modal>
      ) : null}

      {passwordUser ? (
        <Modal
          title="Изменить пароль"
          description={`${passwordUser.name} · ${passwordUser.email}`}
          onClose={() => {
            if (!isChangingPassword) {
              setPasswordUser(null)
              setNewPassword('')
            }
          }}
        >
          <form className="space-y-4" onSubmit={handleChangePassword}>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-zinc-300">
                Новый пароль
              </span>
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                minLength={8}
                required
                className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 outline-none ring-emerald-500 transition focus:ring-2"
              />
            </label>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setPasswordUser(null)
                  setNewPassword('')
                }}
                disabled={isChangingPassword}
                className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition hover:border-zinc-500 disabled:opacity-50"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isChangingPassword || newPassword.length < 8}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isChangingPassword ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                Сохранить
              </button>
            </div>
          </form>
        </Modal>
      ) : null}
    </section>
  )
}

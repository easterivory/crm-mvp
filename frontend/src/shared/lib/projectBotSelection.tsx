import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

type ProjectBotSelectionValue = {
  selectedProjectId: string | null
  selectedBotIds: string[]
  setSelectedProjectId: (projectId: string | null) => void
  setSelectedBotIds: (botIds: string[]) => void
  resetBotSelection: () => void
}

const PROJECT_KEY = 'crm:selectedProjectId'
const BOTS_KEY = 'crm:selectedBotIds'

const ProjectBotSelectionContext = createContext<ProjectBotSelectionValue | null>(null)

function readProjectId(): string | null {
  return localStorage.getItem(PROJECT_KEY)
}

function readBotIds(): string[] {
  const raw = localStorage.getItem(BOTS_KEY)

  if (!raw) {
    return []
  }

  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : []
  } catch {
    localStorage.removeItem(BOTS_KEY)
    return []
  }
}

function persistProjectId(projectId: string | null) {
  if (projectId) {
    localStorage.setItem(PROJECT_KEY, projectId)
  } else {
    localStorage.removeItem(PROJECT_KEY)
  }
}

function persistBotIds(botIds: string[]) {
  localStorage.setItem(BOTS_KEY, JSON.stringify(botIds))
}

function uniqueBotIds(botIds: string[]) {
  return Array.from(new Set(botIds.filter(Boolean)))
}

export function ProjectBotSelectionProvider({ children }: { children: ReactNode }) {
  const [selectedProjectId, setSelectedProjectIdState] = useState<string | null>(
    readProjectId,
  )
  const [selectedBotIds, setSelectedBotIdsState] = useState<string[]>(readBotIds)

  const resetBotSelection = useCallback(() => {
    setSelectedBotIdsState([])
    persistBotIds([])
  }, [])

  const setSelectedProjectId = useCallback(
    (projectId: string | null) => {
      setSelectedProjectIdState((currentProjectId) => {
        if (currentProjectId !== projectId) {
          resetBotSelection()
        }

        persistProjectId(projectId)
        return projectId
      })
    },
    [resetBotSelection],
  )

  const setSelectedBotIds = useCallback((botIds: string[]) => {
    const nextBotIds = uniqueBotIds(botIds)
    setSelectedBotIdsState(nextBotIds)
    persistBotIds(nextBotIds)
  }, [])

  const value = useMemo(
    () => ({
      selectedProjectId,
      selectedBotIds,
      setSelectedProjectId,
      setSelectedBotIds,
      resetBotSelection,
    }),
    [
      resetBotSelection,
      selectedBotIds,
      selectedProjectId,
      setSelectedBotIds,
      setSelectedProjectId,
    ],
  )

  return (
    <ProjectBotSelectionContext.Provider value={value}>
      {children}
    </ProjectBotSelectionContext.Provider>
  )
}

export function useProjectBotSelection() {
  const context = useContext(ProjectBotSelectionContext)

  if (!context) {
    throw new Error(
      'useProjectBotSelection must be used inside ProjectBotSelectionProvider',
    )
  }

  return context
}

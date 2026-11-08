import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import ChatsPage from '../src/pages/ChatsPage'
import { ProjectBotSelectionProvider, useProjectBotSelection } from '../src/shared/lib/projectBotSelection'
import NotificationViewport from '../src/shared/ui/NotificationViewport'
import '../src/index.css'

function Fixture() {
  const selection = useProjectBotSelection()
  return <>
    <nav className="flex gap-3 p-2 text-white">
      <button onClick={() => selection.setSelectedProjectId('qa-other')}>QA project</button>
      <button onClick={() => selection.setSelectedBotIds(['qa-bot'])}>QA bot</button>
    </nav>
    <ChatsPage />
    <NotificationViewport />
  </>
}

createRoot(document.getElementById('root')!).render(
  <MemoryRouter><ProjectBotSelectionProvider><Fixture /></ProjectBotSelectionProvider></MemoryRouter>,
)

import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import CloudAssistantSettings from '../src/features/settings/CloudAssistantSettings'
import '../src/index.css'

createRoot(document.getElementById('root')!).render(<MemoryRouter initialEntries={['/settings' + window.location.search]}>
  <main className="mx-auto min-h-screen max-w-5xl p-4 text-zinc-100"><CloudAssistantSettings projectId="qa-project" /></main>
</MemoryRouter>)

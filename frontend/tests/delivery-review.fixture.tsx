import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import RuntimeDeliveryReview from '../src/features/settings/RuntimeDeliveryReview'
import BackupTransportStatus from '../src/features/settings/BackupTransportStatus'
import '../src/index.css'

createRoot(document.getElementById('root')!).render(<MemoryRouter><main className="mx-auto max-w-4xl space-y-6 p-4 text-zinc-100">
  <RuntimeDeliveryReview projectId="qa-project" />
  <BackupTransportStatus />
</main></MemoryRouter>)

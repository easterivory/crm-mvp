import { createRoot } from 'react-dom/client'
import GamblingOffersSettings from '../src/features/partners/components/GamblingOffersSettings'
import FunnelOfferSettings from '../src/features/funnels/components/FunnelOfferSettings'
import LeadDepositHistory from '../src/components/LeadDepositHistory'
import TrackingOverview from '../src/features/tracking/TrackingOverview'
import type { TrackingMetricSummary } from '../src/features/tracking/types'
import '../src/index.css'

const summary = { starts: 10, leads: 2, registrations: 0, first_deposits: 0, redeposits: 0, spend: 30 } as TrackingMetricSummary
createRoot(document.getElementById('root')!).render(<main className="mx-auto grid max-w-6xl gap-6 p-4 text-gray-100">
  <GamblingOffersSettings projectId="qa-project" />
  <section className="max-w-sm"><FunnelOfferSettings projectId="qa-project" versionId="qa-version" readOnly={false} /></section>
  <section aria-label="Карточка менеджера" className="max-w-sm"><LeadDepositHistory leadId="qa-lead" projectId="qa-project" refreshKey={0} /></section>
  <TrackingOverview projectId="qa-project" userId="qa-manager" dateFrom="2026-11-01" dateTo="2026-11-06" gambling={true} channel={false} summary={summary} daily={[]} />
</main>)

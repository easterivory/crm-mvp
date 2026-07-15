import { ArrowLeft } from 'lucide-react'
import { Navigate, useNavigate } from 'react-router-dom'

import LandersSettings from '../features/landers/components/LandersSettings'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

const FACEBOOK_CAMPAIGN_ROLES = new Set(['super_admin', 'admin', 'buyer'])

export default function FacebookCampaignsPage() {
  const navigate = useNavigate()
  const { selectedProjectId } = useProjectBotSelection()
  const roleName = useAuthStore((state) => state.user?.role_name ?? '')

  if (!FACEBOOK_CAMPAIGN_ROLES.has(roleName)) {
    return <Navigate to="/tracking" replace />
  }

  return (
    <section className="touch-scroll h-full min-h-0 overflow-y-auto rounded-xl border border-white/5 bg-[#0B0F19]/80 p-4 text-gray-200 shadow-card md:p-6">
      <button
        type="button"
        onClick={() => navigate('/tracking')}
        className="mb-5 inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 text-sm font-medium text-gray-200 transition hover:border-accent-300/50 hover:text-white"
      >
        <ArrowLeft size={16} />
        Вернуться в трекинг
      </button>

      <LandersSettings
        projectId={selectedProjectId}
        campaignOnly
        canManageDomains={roleName !== 'buyer'}
      />
    </section>
  )
}

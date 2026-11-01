import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarChart3 } from 'lucide-react'
import api from '../api/client'
import { useProjectBotSelection } from '../shared/lib'
import { useAuthStore } from '../store/authStore'

export default function AdvertisingTrackingLink() {
  const { selectedProjectId } = useProjectBotSelection()
  const role = useAuthStore((s) => s.user?.role_name)
  const [enabled, setEnabled] = useState(false)
  useEffect(() => {
    let active = true
    setEnabled(false)
    if (selectedProjectId && ['admin', 'super_admin'].includes(role || '')) {
      void api
        .get('/advertising/settings', {
          params: { project_id: selectedProjectId },
        })
        .then((r) => {
          if (active) setEnabled(r.data.enabled)
        })
        .catch(() => {})
    }
    return () => {
      active = false
    }
  }, [selectedProjectId, role])
  return enabled ? (
    <Link
      to="/tracking/advertising"
      className="inline-flex items-center gap-2 rounded-lg border border-white/15 px-3 py-2 text-sm"
    >
      <BarChart3 size={16} />
      Рекламный сценарий
    </Link>
  ) : null
}

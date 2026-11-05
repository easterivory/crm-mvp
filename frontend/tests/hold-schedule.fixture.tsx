import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import HoldScheduleSettings from '../src/features/settings/HoldScheduleSettings'
import HoldModeToggle from '../src/features/funnels/components/HoldModeToggle'
import '../src/index.css'

function Fixture() {
  const [version, setVersion] = useState({ hold_mode: 'manual' as 'manual' | 'project_schedule', is_hold_active: false })
  const load = () => { void fetch('/__qa-version').then(response => response.json()).then(setVersion) }
  useEffect(load, [])
  return <main className="mx-auto max-w-xl space-y-6 px-4 py-6">
    <HoldScheduleSettings projectId="qa" />
    <HoldModeToggle funnelId="funnel" versionId="version" projectId="qa" holdMode={version.hold_mode}
      isHoldActive={version.is_hold_active} onToggle={load} />
  </main>
}
createRoot(document.getElementById('root')!).render(<Fixture />)

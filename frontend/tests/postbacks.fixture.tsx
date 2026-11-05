import React from 'react'
import { createRoot } from 'react-dom/client'
import PartnersSettings from '../src/features/partners/components/PartnersSettings'
import '../src/index.css'

createRoot(document.getElementById('root')!).render(
  <main className="mx-auto max-w-6xl p-4"><PartnersSettings projectId="qa" /></main>,
)

import { defaultAnalysisConfig } from '../funnelConfig'
import type { FunnelStep } from '../types'
import AIResponseBlockSettings from './AIResponseBlockSettings'

export default function AIQuestionAnalysisSettings({ step, steps, projectId, onChange }: {
  step: FunnelStep
  steps: FunnelStep[]
  projectId: string
  onChange: (analysis: Record<string, unknown>) => void
}) {
  const raw = step.config_json.ai_analysis
  const config = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
  const enabled = config.enabled === true
  return <section className="space-y-4 border-t border-white/10 pt-4">
    <label className="flex items-center justify-between gap-3 text-sm text-gray-200">
      ИИ-анализ ответа
      <input type="checkbox" checked={enabled} onChange={(event) => onChange({
        ...defaultAnalysisConfig, ...config, enabled: event.target.checked,
      })} />
    </label>
    {enabled && <AIResponseBlockSettings analysis projectId={projectId} steps={steps}
      step={{ ...step, config_json: config }} onConfigChange={(patch) => onChange({ ...config, ...patch })} />}
  </section>
}

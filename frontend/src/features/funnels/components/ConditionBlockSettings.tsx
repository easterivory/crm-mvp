import type { FunnelStep } from '../types'
import {
  normalizeConditions,
  normalizeOutcomes,
  textValue,
} from '../funnelConfig'
import OutcomeEditor from './OutcomeEditor'
import VisualRuleBuilder from './VisualRuleBuilder'

type ConditionBlockSettingsProps = {
  step: FunnelStep
  steps: FunnelStep[]
  onConfigChange: (config: Record<string, unknown>) => void
}

export default function ConditionBlockSettings({
  step,
  steps,
  onConfigChange,
}: ConditionBlockSettingsProps) {
  const mode = textValue(step.config_json, 'mode') || 'all'
  const conditions = normalizeConditions(step.config_json.conditions)
  const outcomes = normalizeOutcomes(step.config_json.outcomes)

  const patchConfig = (patch: Record<string, unknown>) => {
    onConfigChange({ ...step.config_json, ...patch })
  }

  return (
    <div className="space-y-4">
      <label className="block">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
          Режим
        </span>
        <select
          value={mode}
          onChange={(event) => patchConfig({ mode: event.target.value })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
        >
          <option value="all">Все условия / AND</option>
          <option value="any">Любое условие / OR</option>
          <option value="simple_yes_no">Да / Нет</option>
        </select>
      </label>

      <VisualRuleBuilder
        rules={conditions}
        onChange={(nextConditions) => patchConfig({ conditions: nextConditions })}
      />

      <OutcomeEditor
        outcomes={outcomes}
        currentStepId={step.id}
        steps={steps}
        onChange={(nextOutcomes) => {
          const fallback = nextOutcomes.find((outcome) => outcome.id === 'fallback')
          patchConfig({
            outcomes: nextOutcomes,
            fallback_target_step_id: fallback?.target_step_id ?? '',
          })
        }}
      />
    </div>
  )
}

import type { FunnelStep } from '../types'
import {
  answerTypes,
  boolValue,
  leadFields,
  normalizeButtons,
  numberValue,
  textValue,
} from '../funnelConfig'
import ButtonListEditor, { TargetSelect } from './ButtonListEditor'

type InputBlockSettingsProps = {
  step: FunnelStep
  steps: FunnelStep[]
  onConfigChange: (config: Record<string, unknown>) => void
}

export default function InputBlockSettings({
  step,
  steps,
  onConfigChange,
}: InputBlockSettingsProps) {
  const patchConfig = (patch: Record<string, unknown>) => {
    onConfigChange({ ...step.config_json, ...patch })
  }

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 rounded-lg border border-white/8 bg-white/[0.03] px-3 py-2 text-sm text-gray-200">
        <input
          type="checkbox"
          checked={boolValue(step.config_json, 'wait_for_answer', true)}
          onChange={(event) => patchConfig({ wait_for_answer: event.target.checked })}
        />
        Ждать ответ пользователя
      </label>

      <label className="block">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
          Prompt
        </span>
        <textarea
          rows={3}
          value={
            textValue(step.config_json, 'prompt') ||
            textValue(step.config_json, 'question_text') ||
            textValue(step.config_json, 'text')
          }
          onChange={(event) => patchConfig({ prompt: event.target.value })}
          className="w-full resize-none rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
        />
      </label>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Тип ответа</span>
          <select
            value={textValue(step.config_json, 'answer_type') || 'text'}
            onChange={(event) =>
              patchConfig({
                answer_type: event.target.value,
                validation: { type: event.target.value },
              })
            }
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          >
            {answerTypes.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Сохранить в поле</span>
          <select
            value={textValue(step.config_json, 'save_to')}
            onChange={(event) => patchConfig({ save_to: event.target.value })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          >
            {leadFields.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Max retries</span>
          <input
            type="number"
            min={0}
            value={numberValue(step.config_json, 'max_retries', 2)}
            onChange={(event) => patchConfig({ max_retries: Number(event.target.value) || 0 })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Timeout, сек</span>
          <input
            type="number"
            min={0}
            value={numberValue(step.config_json, 'timeout_seconds', 0)}
            onChange={(event) => patchConfig({ timeout_seconds: Number(event.target.value) || 0 })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>
      </div>

      <label className="block">
        <span className="mb-1 block text-xs text-gray-500">Сообщение при ошибке</span>
        <input
          value={textValue(step.config_json, 'retry_message')}
          onChange={(event) => patchConfig({ retry_message: event.target.value })}
          className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
        />
      </label>

      <label className="block">
        <span className="mb-1 block text-xs text-gray-500">Ветка по таймауту</span>
        <TargetSelect
          value={textValue(step.config_json, 'timeout_target_step_id')}
          currentStepId={step.id}
          steps={steps}
          onChange={(value) => patchConfig({ timeout_target_step_id: value })}
        />
      </label>

      <ButtonListEditor
        title="Choices"
        buttons={normalizeButtons(step.config_json.choices)}
        currentStepId={step.id}
        steps={steps}
        onChange={(choices) => patchConfig({ choices })}
      />
    </div>
  )
}

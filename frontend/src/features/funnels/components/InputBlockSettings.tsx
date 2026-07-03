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
  const customFieldKey = textValue(step.config_json, 'custom_field_key')
  const selectedField =
    textValue(step.config_json, 'field_mode') === 'custom' || customFieldKey
      ? '__custom__'
      : textValue(step.config_json, 'save_to')

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
            value={selectedField}
            onChange={(event) => {
              const value = event.target.value
              patchConfig(
                value === '__custom__'
                  ? { save_to: '', custom_field_key: customFieldKey, field_mode: 'custom' }
                  : { save_to: value, custom_field_key: '', field_mode: 'standard' },
              )
            }}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          >
            {leadFields.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
            <option value="__custom__">Произвольное поле</option>
          </select>
        </label>
      </div>

      {selectedField === '__custom__' ? (
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">
            Ключ произвольного поля
          </span>
          <input
            value={customFieldKey}
            onChange={(event) =>
              patchConfig({
                save_to: '',
                custom_field_key: event.target.value
                  .toLowerCase()
                  .replace(/[^a-z0-9_]/g, '_')
                  .replace(/^[^a-z]+/, '')
                  .slice(0, 100),
              })
            }
            maxLength={100}
            required
            placeholder="например: city или monthly_income"
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
          <span className="mt-1 block text-xs leading-5 text-gray-500">
            Значение появится в карточке лида и будет доступно в условиях и интеграциях.
          </span>
        </label>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Задержка перед вопросом, сек</span>
          <input
            type="number"
            min={0}
            value={numberValue(step.config_json, 'delay_before_seconds', 0)}
            onChange={(event) =>
              patchConfig({ delay_before_seconds: Number(event.target.value) || 0 })
            }
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-500">Таймаут ответа, сек</span>
          <input
            type="number"
            min={0}
            value={numberValue(step.config_json, 'timeout_seconds', 0)}
            onChange={(event) => patchConfig({ timeout_seconds: Number(event.target.value) || 0 })}
            className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
          />
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
        buttonMode={step.config_json.button_mode === 'reply' ? 'reply' : 'inline'}
        onButtonModeChange={(buttonMode) => patchConfig({ button_mode: buttonMode })}
        currentStepId={step.id}
        steps={steps}
        onChange={(choices) => patchConfig({ choices })}
      />
    </div>
  )
}

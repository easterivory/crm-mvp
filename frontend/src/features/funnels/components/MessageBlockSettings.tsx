import type { FunnelStep } from '../types'
import {
  normalizeMessages,
  numberValue,
  textValue,
  type MessageConfig,
} from '../funnelConfig'
import MessageSequenceEditor from './MessageSequenceEditor'
import { TargetSelect } from './ButtonListEditor'

type MessageBlockSettingsProps = {
  step: FunnelStep
  projectId: string
  steps: FunnelStep[]
  onConfigChange: (config: Record<string, unknown>) => void
}

export default function MessageBlockSettings({
  step,
  projectId,
  steps,
  onConfigChange,
}: MessageBlockSettingsProps) {
  const messages = normalizeMessages(step.config_json)

  const updateMessages = (nextMessages: MessageConfig[]) => {
    const firstMessage = nextMessages[0]
    onConfigChange({
      ...step.config_json,
      messages: nextMessages,
      text: firstMessage?.text ?? '',
      message_type: firstMessage?.type ?? 'text',
      media: firstMessage?.media,
      chat_action_enabled: firstMessage?.chat_action_enabled ?? false,
      chat_action_duration_seconds: firstMessage?.chat_action_duration_seconds ?? 3,
      wait_for_answer: firstMessage?.wait_for_answer ?? false,
      continue_after_buttons: firstMessage?.continue_after_buttons ?? false,
      button_mode: firstMessage?.button_mode ?? 'inline',
      buttons: firstMessage?.buttons ?? [],
    })
  }

  return (
    <div className="space-y-4">
      <MessageSequenceEditor
        messages={messages}
        currentStepId={step.id}
        projectId={projectId}
        steps={steps}
        onChange={updateMessages}
      />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={step.config_json.auto_advance_enabled === true}
          className="h-4 w-4 shrink-0 rounded border-white/20 bg-background text-accent-300"
          onChange={(event) => onConfigChange({ ...step.config_json, auto_advance_enabled: event.target.checked })} />
        Перейти по таймеру
      </label>
      {step.config_json.auto_advance_enabled === true && (
        <div className="space-y-3">
          <label className="block text-sm">
            Время ожидания, сек
            <input type="number" min={1} max={604800} step={1}
              value={numberValue(step.config_json, 'auto_advance_seconds', 60)}
              onChange={(event) => onConfigChange({ ...step.config_json, auto_advance_seconds: Number(event.target.value) })}
              className="mt-1 w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5" />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block">Шаг по таймеру</span>
            <TargetSelect value={textValue(step.config_json, 'timeout_target_step_id')}
              steps={steps} currentStepId={step.id}
              onChange={(value) => onConfigChange({ ...step.config_json, timeout_target_step_id: value })} />
          </label>
        </div>
      )}
    </div>
  )
}

import type { FunnelStep } from '../types'
import {
  normalizeMessages,
  type MessageConfig,
} from '../funnelConfig'
import MessageSequenceEditor from './MessageSequenceEditor'

type MessageBlockSettingsProps = {
  step: FunnelStep
  steps: FunnelStep[]
  onConfigChange: (config: Record<string, unknown>) => void
}

export default function MessageBlockSettings({
  step,
  steps,
  onConfigChange,
}: MessageBlockSettingsProps) {
  const messages = normalizeMessages(step.config_json)

  const updateMessages = (nextMessages: MessageConfig[]) => {
    onConfigChange({
      ...step.config_json,
      messages: nextMessages,
      text: nextMessages[0]?.text ?? '',
      buttons: nextMessages[0]?.buttons ?? [],
    })
  }

  return (
    <MessageSequenceEditor
      messages={messages}
      currentStepId={step.id}
      steps={steps}
      onChange={updateMessages}
    />
  )
}

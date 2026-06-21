import type { FunnelStep } from '../types'
import {
  normalizeMessages,
  type MessageConfig,
} from '../funnelConfig'
import MessageSequenceEditor from './MessageSequenceEditor'

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
      wait_for_answer: firstMessage?.wait_for_answer ?? false,
      buttons: firstMessage?.buttons ?? [],
    })
  }

  return (
    <MessageSequenceEditor
      messages={messages}
      currentStepId={step.id}
      projectId={projectId}
      steps={steps}
      onChange={updateMessages}
    />
  )
}

import type { BroadcastContent } from '../types'

type PhonePreviewProps = {
  content: BroadcastContent
}

export default function PhonePreview({ content }: PhonePreviewProps) {
  const messages = content.messages.filter((message) => message.text?.trim())

  return (
    <div className="rounded-[28px] border border-white/10 bg-[#070b13] p-3 shadow-card">
      <div className="rounded-[22px] border border-white/8 bg-[#101827] p-4">
        <div className="mx-auto mb-4 h-1.5 w-16 rounded-full bg-white/15" />
        <div className="min-h-[360px] rounded-2xl bg-[#0b1220] p-4">
          <div className="mb-4 text-center text-xs text-gray-500">Telegram preview</div>
          {messages.length ? (
            <div className="space-y-3">
              {messages.map((message, index) => (
                <div key={index} className="max-w-[88%] rounded-2xl rounded-bl-md bg-accent-500/20 px-3 py-2 text-sm leading-5 text-gray-100">
                  {message.delay_seconds ? (
                    <p className="mb-1 text-[11px] text-accent-100/70">+{message.delay_seconds} сек.</p>
                  ) : null}
                  <p className="whitespace-pre-wrap">{message.text}</p>
                  {message.buttons?.length ? (
                    <div className="mt-2 grid gap-1">
                      {message.buttons.map((button, buttonIndex) => (
                        <span
                          key={buttonIndex}
                          className="rounded-lg border border-accent-200/20 bg-accent-200/10 px-2 py-1 text-center text-xs text-accent-50"
                        >
                          {String(button.label ?? button.text ?? 'Кнопка')}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-white/10 px-4 text-center text-sm text-gray-500">
              Введите текст, чтобы увидеть preview.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

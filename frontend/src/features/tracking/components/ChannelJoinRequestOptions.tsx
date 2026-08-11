type ChannelJoinRequestOptionsProps = {
  joinRequest: boolean
  onJoinRequestChange: (value: boolean) => void
  autoApprove: boolean
  onAutoApproveChange: (value: boolean) => void
  messageEnabled: boolean
  onMessageEnabledChange: (value: boolean) => void
  message: string
  onMessageChange: (value: string) => void
}

export default function ChannelJoinRequestOptions({
  joinRequest,
  onJoinRequestChange,
  autoApprove,
  onAutoApproveChange,
  messageEnabled,
  onMessageEnabledChange,
  message,
  onMessageChange,
}: ChannelJoinRequestOptionsProps) {
  const setJoinRequest = (value: boolean) => {
    onJoinRequestChange(value)
    if (!value) {
      onAutoApproveChange(false)
      onMessageEnabledChange(false)
    }
  }

  return (
    <fieldset className="space-y-3 rounded-lg border border-cyan-400/20 bg-cyan-500/[0.05] p-3">
      <legend className="px-1 text-sm font-semibold text-cyan-100">
        Обработка заявки в канал
      </legend>
      <label className="flex min-h-11 items-start justify-between gap-4">
        <span className="min-w-0">
          <span className="block text-sm font-medium text-zinc-100">Заявка на вступление</span>
          <span className="mt-0.5 block text-xs leading-5 text-zinc-500">
            Выключено: пользователь вступает сразу. Включено: Telegram сначала создаёт заявку.
          </span>
        </span>
        <input
          type="checkbox"
          checked={joinRequest}
          onChange={(event) => setJoinRequest(event.target.checked)}
          className="mt-0.5 h-5 w-5 shrink-0 accent-cyan-400"
        />
      </label>

      {joinRequest ? (
        <div className="space-y-3 border-t border-cyan-400/15 pt-3">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="flex min-h-11 items-start justify-between gap-3 rounded-md border border-white/10 bg-black/10 px-3 py-2.5">
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-100">Написать при заявке</span>
                <span className="mt-0.5 block text-xs leading-5 text-zinc-500">
                  Бот-трекер первым отправит сообщение в личный чат.
                </span>
              </span>
              <input
                type="checkbox"
                checked={messageEnabled}
                onChange={(event) => onMessageEnabledChange(event.target.checked)}
                className="mt-0.5 h-5 w-5 shrink-0 accent-cyan-400"
              />
            </label>
            <label className="flex min-h-11 items-start justify-between gap-3 rounded-md border border-white/10 bg-black/10 px-3 py-2.5">
              <span className="min-w-0">
                <span className="block text-sm font-medium text-zinc-100">Автоматически принять</span>
                <span className="mt-0.5 block text-xs leading-5 text-zinc-500">
                  После сообщения бот одобрит заявку без участия администратора.
                </span>
              </span>
              <input
                type="checkbox"
                checked={autoApprove}
                onChange={(event) => onAutoApproveChange(event.target.checked)}
                className="mt-0.5 h-5 w-5 shrink-0 accent-cyan-400"
              />
            </label>
          </div>

          {messageEnabled ? (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-zinc-200">
                Сообщение от бота-трекера
              </span>
              <textarea
                value={message}
                onChange={(event) => onMessageChange(event.target.value)}
                required
                maxLength={4096}
                rows={4}
                placeholder="Напишите короткое приветствие или следующий шаг для подписчика"
                className="min-h-28 w-full resize-y rounded-lg border border-white/10 bg-zinc-950 px-3 py-2 text-base leading-6 text-zinc-100 outline-none ring-cyan-500 transition placeholder:text-zinc-600 focus:ring-2 md:text-sm"
              />
              <span className="mt-1 block text-right text-xs text-zinc-600">
                {message.length}/4096
              </span>
            </label>
          ) : null}
        </div>
      ) : null}
    </fieldset>
  )
}

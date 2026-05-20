import { Copy, LoaderCircle } from 'lucide-react'
import { FormEvent, useMemo, useState } from 'react'

import type { Bot as BotRecord } from '../../bots'
import type { Project } from '../../projects'
import { Modal } from '../../../shared/ui'
import { copyFunnel } from '../api'
import type { Funnel } from '../types'

type CopyFunnelModalProps = {
  funnel: Funnel
  projects: Project[]
  bots: BotRecord[]
  onClose: () => void
  onCopied: (funnelId: string, versionId: string, projectId: string) => void
}

export default function CopyFunnelModal({
  funnel,
  projects,
  bots,
  onClose,
  onCopied,
}: CopyFunnelModalProps) {
  const [projectId, setProjectId] = useState(funnel.project_id)
  const [botId, setBotId] = useState('')
  const [isCopying, setIsCopying] = useState(false)

  const projectBots = useMemo(
    () => bots.filter((bot) => bot.project_id === projectId),
    [bots, projectId],
  )

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const targetBotId = botId || projectBots[0]?.id
    if (!projectId || !targetBotId || isCopying) {
      return
    }
    setIsCopying(true)
    try {
      const result = await copyFunnel(funnel, {
        target_project_id: projectId,
        target_bot_id: targetBotId,
        copy_from_version_id: funnel.published_version_id ?? funnel.draft_version_id,
      })
      onCopied(result.new_funnel_id, result.new_version_id, projectId)
    } finally {
      setIsCopying(false)
    }
  }

  return (
    <Modal
      title="Копировать воронку"
      description="Копия всегда создаётся как draft. Проверьте настройки перед публикацией."
      onClose={onClose}
    >
      <form className="space-y-3" onSubmit={submit}>
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
            Проект
          </span>
          <select
            value={projectId}
            onChange={(event) => {
              setProjectId(event.target.value)
              setBotId('')
            }}
            className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-gray-500">
            Бот
          </span>
          <select
            value={botId}
            onChange={(event) => setBotId(event.target.value)}
            className="w-full rounded-xl border border-white/10 bg-background/70 px-3 py-2 text-sm text-gray-100 outline-none ring-accent-400/50 transition focus:ring-2"
          >
            <option value="">Выберите бота</option>
            {projectBots.map((bot) => (
              <option key={bot.id} value={bot.id}>
                {bot.name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-white/10 bg-white/[0.03] px-4 py-2 text-sm text-gray-200 transition hover:border-white/20"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={isCopying || projectBots.length === 0}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-primary-500 to-accent-500 px-4 py-2 text-sm font-semibold text-white shadow-glow-primary transition hover:shadow-glow-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isCopying ? <LoaderCircle size={16} className="animate-spin" /> : <Copy size={16} />}
            Копировать
          </button>
        </div>
      </form>
    </Modal>
  )
}

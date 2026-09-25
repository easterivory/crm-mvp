import { useEffect, useMemo, useState } from 'react'
import api from '../../api/client'

type Tag = { id: string; name: string }
type TagMetrics = { tag_id: string; tag_name: string; total: number; daily: Array<{ date: string; count: number }> }

export function useTrackingTagMetric(projectId: string | null, dateFrom: string, dateTo: string, botId?: string, linkId?: string, refreshToken?: object | null) {
  const [tags, setTags] = useState<Tag[]>([])
  const [tagId, setTagId] = useState('')
  const [result, setResult] = useState<{ key: string; data: TagMetrics } | null>(null)
  const [error, setError] = useState('')
  const [tagsError, setTagsError] = useState('')
  const [retry, setRetry] = useState(0)
  const key = JSON.stringify([projectId, dateFrom, dateTo, botId, linkId, tagId])
  useEffect(() => { setTagId('') }, [projectId])

  useEffect(() => {
    const controller = new AbortController()
    setTags([])
    setTagsError('')
    if (projectId) void (async () => {
      const collected: Tag[] = []
      let total = Infinity
      while (collected.length < total) {
        const { data } = await api.get<{ items: Tag[]; total: number }>('/tags', {
          params: { project_id: projectId, limit: 100, offset: collected.length }, signal: controller.signal,
        })
        total = data.total
        if (!data.items.length) break
        collected.push(...data.items)
      }
      if (!controller.signal.aborted) setTags(collected)
    })().catch(() => { if (!controller.signal.aborted) setTagsError('Не удалось загрузить теги') })
    return () => controller.abort()
  }, [projectId, retry])

  useEffect(() => {
    const controller = new AbortController()
    setResult(null)
    setError('')
    if (projectId && tagId) void api.get<TagMetrics>('/tracking/metrics/tag', {
      params: { project_id: projectId, tag_id: tagId, date_from: dateFrom || undefined,
        date_to: dateTo || undefined, bot_id: botId, link_id: linkId }, signal: controller.signal,
    }).then(({ data }) => { if (!controller.signal.aborted) setResult({ key, data }) })
      .catch(() => { if (!controller.signal.aborted) setError('Не удалось загрузить статистику тега') })
    return () => controller.abort()
  }, [projectId, dateFrom, dateTo, botId, linkId, tagId, key, retry, refreshToken])

  const data = result?.key === key ? result.data : null
  const counts = useMemo(() => new Map(data?.daily.map((day) => [day.date, day.count]) ?? []), [data])
  return { tags, tagId, setTagId, data, counts, error: tagsError || error, retry: () => setRetry((value) => value + 1) }
}

export function TrackingTagSelector({ metric }: { metric: ReturnType<typeof useTrackingTagMetric> }) {
  return <div className="mb-3 flex min-w-0 flex-col gap-1">
    <label className="text-xs text-gray-400">
      Тег на графике
      <select aria-label="Тег на графике" value={metric.tagId} onChange={(event) => metric.setTagId(event.target.value)}
        className="mt-1 block w-full min-w-0 max-w-sm rounded-md border border-white/10 bg-background px-2 py-2 text-sm text-gray-100">
        <option value="">Без дополнительного тега</option>
        {metric.tags.map((tag) => <option key={tag.id} value={tag.id}>{tag.name}</option>)}
      </select>
    </label>
    {metric.error ? <p role="status" className="text-xs text-red-300">{metric.error}. <button type="button" className="underline" onClick={metric.retry}>Повторить</button></p>
      : metric.tagId ? <p className="text-xs text-gray-400">{metric.data ? `Лиды с тегом по дате входа (UTC): ${metric.data.total}` : 'Загрузка показателя…'}</p> : null}
  </div>
}

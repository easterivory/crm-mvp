type Props = { customFields?: Record<string, unknown> }

export default function ChatterfyImportSource({ customFields }: Props) {
  const raw = customFields?.__chatterfy_import
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const data = raw as Record<string, unknown>
  if (data.schema !== 1) return null
  const fields = [
    ['Бот', data.source_username],
    ['Кампания', data.campaign_id],
    ['Источник', data.source_id],
  ].filter((entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1].length > 0)
  return (
    <section aria-label="Источник Chatterfy" className="min-w-0 border-b border-white/10 pb-4">
      <h3 className="mb-2 text-xs font-medium text-gray-400">Импорт из Chatterfy</h3>
      <dl className="space-y-1 text-xs">
        {fields.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[5rem_minmax(0,1fr)] gap-2">
            <dt className="text-gray-500">{label}</dt>
            <dd className="break-words text-gray-200 [overflow-wrap:anywhere]">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

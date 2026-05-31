type DropOffChartProps = {
  data: any[]
}

export default function DropOffChart({ data }: DropOffChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        Нет данных для отображения
      </div>
    )
  }

  return (
    <div className="p-6">
      <h2 className="mb-4 text-xl font-semibold text-white">Drop-off аналитика</h2>
      <div className="space-y-4">
        {data.map((step, index) => (
          <div key={index} className="rounded-lg border border-white/10 bg-white/5 p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-medium text-white">{step.step_name || `Шаг ${index + 1}`}</span>
              <span className="text-sm text-gray-400">
                {step.completed_count || 0} завершений
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full bg-gradient-to-r from-primary-500 to-accent-500"
                style={{ width: `${step.completion_rate || 0}%` }}
              />
            </div>
            <div className="mt-2 text-sm text-gray-400">
              Конверсия: {step.completion_rate?.toFixed(1) || 0}%
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

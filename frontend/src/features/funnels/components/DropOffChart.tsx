import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { FunnelDropOffStep } from '../types'

type DropOffChartProps = {
  data: FunnelDropOffStep[]
}

function formatPercent(value: number) {
  return `${Number(value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
}

export default function DropOffChart({ data }: DropOffChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-gray-400">
        Нет данных для отображения
      </div>
    )
  }

  const chartData = data.map((step, index) => ({
    ...step,
    name: step.step_title || `Шаг ${index + 1}`,
    entered_leads: Number(step.entered_leads || 0),
    conversion_from_start: Number(step.conversion_from_start || 0),
    conversion_from_previous: Number(step.conversion_from_previous || 0),
  }))
  const totalEntered = chartData[0]?.entered_leads ?? 0
  const lastEntered = chartData[chartData.length - 1]?.entered_leads ?? 0
  const dropOff = Math.max(totalEntered - lastEntered, 0)
  const finalConversion = totalEntered > 0 ? (lastEntered / totalEntered) * 100 : 0

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <SummaryMetric label="Стартовали" value={totalEntered} />
        <SummaryMetric label="Дошли до финала" value={lastEntered} />
        <SummaryMetric label="Конверсия" value={formatPercent(finalConversion)} />
      </div>

      <div className="min-h-[320px] flex-1 rounded-xl border border-white/8 bg-white/[0.03] p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold text-white">Drop-off аналитика</h2>
            <p className="text-sm text-gray-500">Лиды по шагам и конверсия от старта</p>
          </div>
          <div className="rounded-lg border border-red-300/15 bg-red-400/10 px-2 py-1 text-xs text-red-100">
            Отвал {dropOff}
          </div>
        </div>

        <div className="h-[260px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ left: -18, right: 8, top: 12, bottom: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis
                dataKey="name"
                stroke="rgba(255,255,255,0.35)"
                tickLine={false}
                axisLine={false}
                interval={0}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                yAxisId="leads"
                stroke="rgba(255,255,255,0.35)"
                tickLine={false}
                axisLine={false}
                allowDecimals={false}
              />
              <YAxis
                yAxisId="conversion"
                orientation="right"
                domain={[0, 100]}
                tickFormatter={(value) => `${value}%`}
                stroke="rgba(255,255,255,0.35)"
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                formatter={(value, name) => {
                  if (name === 'conversion_from_start') {
                    return [formatPercent(Number(value)), 'Конверсия']
                  }
                  return [Number(value).toLocaleString('ru-RU'), 'Лиды']
                }}
                contentStyle={{
                  background: '#0B0F19',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 12,
                  color: '#e5e7eb',
                }}
              />
              <Bar
                yAxisId="leads"
                dataKey="entered_leads"
                fill="#22d3ee"
                radius={[6, 6, 0, 0]}
                maxBarSize={42}
              />
              <Line
                yAxisId="conversion"
                type="monotone"
                dataKey="conversion_from_start"
                stroke="#a855f7"
                strokeWidth={2}
                dot={{ r: 3, fill: '#a855f7' }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

function SummaryMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-white">{value}</div>
    </div>
  )
}

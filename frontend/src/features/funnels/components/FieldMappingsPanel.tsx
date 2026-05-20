import { Plus, Trash2 } from 'lucide-react'

import type { FunnelFieldMapping, FunnelStep } from '../types'

const leadFields = [
  ['name', 'Имя'],
  ['phone', 'Телефон'],
  ['age', 'Возраст'],
  ['country', 'Страна'],
  ['call_time_text', 'Удобное время'],
  ['call_date', 'Дата звонка'],
  ['call_time_from', 'Время от'],
  ['call_time_to', 'Время до'],
  ['has_card', 'Есть карта'],
  ['experience', 'Опыт'],
] as const

const sources = [
  ['user_answer', 'Ответ пользователя'],
  ['button_value', 'Значение кнопки'],
  ['computed_value', 'Вычисленное значение'],
] as const

type FieldMappingsPanelProps = {
  selectedStep: FunnelStep | null
  mappings: FunnelFieldMapping[]
  onChange: (mappings: FunnelFieldMapping[]) => void
}

export default function FieldMappingsPanel({
  selectedStep,
  mappings,
  onChange,
}: FieldMappingsPanelProps) {
  const stepMappings = selectedStep
    ? mappings.filter((mapping) => mapping.step_id === selectedStep.id)
    : []

  const addMapping = () => {
    if (!selectedStep) {
      return
    }
    onChange([
      ...mappings,
      {
        id: crypto.randomUUID(),
        step_id: selectedStep.id,
        source: 'user_answer',
        lead_field_key: 'phone',
        transform_rule_json: null,
        is_required: false,
      },
    ])
  }

  const patchMapping = (mappingId: string, patch: Partial<FunnelFieldMapping>) => {
    onChange(
      mappings.map((mapping) =>
        mapping.id === mappingId ? { ...mapping, ...patch } : mapping,
      ),
    )
  }

  const removeMapping = (mappingId: string) => {
    onChange(mappings.filter((mapping) => mapping.id !== mappingId))
  }

  return (
    <section className="rounded-lg border border-white/8 bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-white">Field mappings</h3>
        <button
          type="button"
          onClick={addMapping}
          disabled={!selectedStep || selectedStep.step_type !== 'input'}
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.04] px-2 text-xs text-gray-200 disabled:cursor-not-allowed disabled:opacity-45"
        >
          <Plus size={13} />
          Добавить
        </button>
      </div>
      {selectedStep?.step_type !== 'input' ? (
        <p className="mt-2 text-sm text-gray-500">Маппинги доступны для блоков сбора данных.</p>
      ) : null}
      {stepMappings.length > 0 ? (
        <div className="mt-3 space-y-3">
          {stepMappings.map((mapping) => (
            <div key={mapping.id} className="rounded-lg border border-white/8 bg-background/45 p-3">
              <div className="grid gap-2">
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">Источник</span>
                  <select
                    value={mapping.source}
                    onChange={(event) =>
                      patchMapping(mapping.id, {
                        source: event.target.value as FunnelFieldMapping['source'],
                      })
                    }
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  >
                    {sources.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs text-gray-500">Поле лида</span>
                  <select
                    value={mapping.lead_field_key}
                    onChange={(event) =>
                      patchMapping(mapping.id, { lead_field_key: event.target.value })
                    }
                    className="w-full rounded-lg border border-white/10 bg-background/70 px-2 py-1.5 text-sm text-gray-100 outline-none"
                  >
                    {leadFields.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={mapping.is_required}
                    onChange={(event) =>
                      patchMapping(mapping.id, { is_required: event.target.checked })
                    }
                    className="h-4 w-4 rounded border-white/10 bg-background/70"
                  />
                  Обязательное поле
                </label>
              </div>
              <button
                type="button"
                onClick={() => removeMapping(mapping.id)}
                className="mt-2 inline-flex h-8 items-center gap-1 rounded-lg border border-red-300/15 px-2 text-xs text-red-200 transition hover:border-red-300/35"
              >
                <Trash2 size={13} />
                Удалить
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  )
}

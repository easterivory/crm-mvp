const variables = [
  ['{{first_name}}', 'Имя'],
  ['{{username}}', 'Username'],
  ['{{phone}}', 'Телефон'],
  ['{{lead_status}}', 'Статус'],
  ['{{project}}', 'Проект'],
  ['{{bot}}', 'Бот'],
  ['{{custom.field_name}}', 'custom_fields'],
]

type VariablePickerProps = {
  onInsert: (value: string) => void
}

export default function VariablePicker({ onInsert }: VariablePickerProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {variables.map(([value, label]) => (
        <button
          key={value}
          type="button"
          onClick={() => onInsert(value)}
          className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-gray-200 transition hover:border-accent-300/35"
        >
          {label}
        </button>
      ))}
    </div>
  )
}

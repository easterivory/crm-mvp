import { useState } from 'react'
import { Plus } from 'lucide-react'
import api from '../../api/client'
import { useTranslationLanguages } from './languages'

export default function LanguageSettings() {
  const languages = useTranslationLanguages()
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  async function save() {
    if (saving || !code.trim() || !label.trim()) return
    setSaving(true)
    setError('')
    try {
      await api.post('/settings/translation/languages', { value: code, label })
      window.dispatchEvent(new Event('translation-languages-updated'))
      setCode('')
      setLabel('')
    } catch {
      setError('Не удалось сохранить язык. Проверьте код языка и соединение.')
    } finally { setSaving(false) }
  }
  return <section className="mt-6 border-t border-zinc-800 pt-4">
    <h4 className="text-sm font-semibold text-zinc-100">Языки перевода</h4>
    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-400">
      {languages.map((language) => <span key={language.value}>{language.label} ({language.shortLabel})</span>)}
    </div>
    <div className="mt-3 grid gap-3 sm:grid-cols-[100px_minmax(0,1fr)_auto]">
      <input aria-label="Код языка" placeholder="Код: uz" value={code} maxLength={10}
        onChange={(event) => setCode(event.target.value)}
        className="min-w-0 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm" />
      <input aria-label="Название языка" placeholder="Название языка" value={label} maxLength={80}
        onChange={(event) => setLabel(event.target.value)}
        className="min-w-0 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm" />
      <button type="button" onClick={() => void save()} disabled={saving || !code.trim() || !label.trim()}
        className="inline-flex items-center justify-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm disabled:opacity-50">
        <Plus size={16} />Добавить язык
      </button>
    </div>
    {error && <p role="alert" className="mt-2 text-sm text-red-400">{error}</p>}
  </section>
}

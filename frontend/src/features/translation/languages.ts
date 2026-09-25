import { useEffect, useState } from 'react'
import api from '../../api/client'

export type TranslationLanguage = { value: string; label: string }
const languageNames = new Intl.DisplayNames(['ru'], { type: 'language' })

export function translationLanguageName(code: string): string {
  try { return languageNames.of(code) ?? code.toUpperCase() }
  catch { return code.toUpperCase() }
}

export function useTranslationLanguages(...selected: Array<string | null | undefined>) {
  const [languages, setLanguages] = useState<TranslationLanguage[]>([])
  useEffect(() => {
    const controller = new AbortController()
    const load = () => {
      void api.get<TranslationLanguage[]>('/settings/translation/languages', { signal: controller.signal })
        .then(({ data }) => setLanguages(data))
        .catch(() => { /* Existing selected codes remain usable on network failure. */ })
    }
    load()
    window.addEventListener('translation-languages-updated', load)
    return () => {
      controller.abort()
      window.removeEventListener('translation-languages-updated', load)
    }
  }, [])
  const result = [...languages]
  for (const code of selected) {
    if (code && !result.some((item) => item.value === code)) {
      result.push({ value: code, label: translationLanguageName(code) })
    }
  }
  return result.map((language) => ({ ...language, shortLabel: language.value.toUpperCase() }))
}

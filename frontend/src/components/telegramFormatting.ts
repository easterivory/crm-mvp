const telegramTag = /<\/?(?:b|strong|i|em|u|s|del|tg-spoiler|code|pre|blockquote|a)(?=[\s/>])/i
const escapedTelegramTag = /&lt;\/?(?:b|strong|i|em|u|s|del|tg-spoiler|code|pre|blockquote|a)(?=\s|&gt;|\/)/i

export const hasTelegramMarkup = (text: string) => telegramTag.test(text)
export const hasEscapedTelegramMarkup = (text: string) => escapedTelegramTag.test(text)
export const escapeTelegramText = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
export const isOfferLinkTemplate = (text: string) => /^{{\s*offer_link\s*}}$/.test(text)

export const telegramParseMode = (text: string, mode?: 'HTML' | null): 'HTML' | null => mode === 'HTML' || hasTelegramMarkup(text) ? 'HTML' : null

const tags = new Set(['b', 'strong', 'i', 'em', 'u', 's', 'del', 'tg-spoiler', 'code', 'pre', 'blockquote', 'a'])
const documentFor = (text: string) => new DOMParser().parseFromString(text, 'text/html')

export function telegramFormattingError(text: string, mode?: 'HTML' | null): string | null {
  if (!telegramParseMode(text, mode)) return null
  if (/<!--|<!doctype|<\?/i.test(text)) return 'Комментарии и служебные HTML-теги не поддерживаются.'
  const stack: string[] = []
  const token = /<\/?([a-z][\w-]*)(?:\s+(?:[^<>"']|"[^"]*"|'[^']*')*)?\s*\/?>/gi
  for (const match of text.matchAll(token)) {
    const tag = match[1].toLowerCase()
    const source = match[0]
    if (!tags.has(tag)) return `Неподдерживаемый тег оформления: ${tag}.`
    if (source.startsWith('</')) {
      if (stack.pop() !== tag) return 'Незакрытые или пересекающиеся теги оформления.'
      continue
    }
    if (stack.some(parent => parent === 'code' || parent === 'pre') || ((tag === 'code' || tag === 'pre') && stack.length)) {
      return 'Код нельзя вкладывать в другое оформление.'
    }
    const element = documentFor(source + `</${tag}>`).body.firstElementChild
    if (!element || Array.from(element.attributes).some(attr => tag !== 'a' || attr.name !== 'href')) return 'Неподдерживаемые атрибуты оформления.'
    if (tag === 'a') {
      const href = element.getAttribute('href') ?? ''
      try {
        const url = new URL(isOfferLinkTemplate(href) ? 'https://offer.invalid/personal' : href)
        if (!['http:', 'https:', 'tg:', 'mailto:'].includes(url.protocol) || !(url.host || url.pathname)) throw new Error()
      } catch { return 'Некорректный href ссылки. Добавьте ссылку через кнопку «Ссылка».' }
      if (stack.includes('a')) return 'Ссылки нельзя вкладывать друг в друга.'
    }
    if (!source.endsWith('/>')) stack.push(tag)
  }
  if (stack.length || hasTelegramMarkup(text.replace(token, ''))) return 'Не закрыты теги оформления.'
  return null
}

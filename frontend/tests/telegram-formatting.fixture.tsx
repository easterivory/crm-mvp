import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import TelegramTextEditor from '../src/components/TelegramTextEditor'
import PhonePreview from '../src/features/broadcasts/components/PhonePreview'
import '../src/index.css'

function Fixture() {
  const [text, setText] = useState('')
  const [mode, setMode] = useState<'HTML' | null>(null)
  const [photo, setPhoto] = useState(false)
  const legacy = '<b>Offer</b>\n1. <a href="https://t.me/+example">Contact</a>'
  return <main className="mx-auto grid max-w-5xl gap-6 p-4 md:grid-cols-2"><section className="min-w-0">
    <button onClick={() => { setText(legacy); setMode(null); setPhoto(false) }}>Текстовый слот</button>
    <button onClick={() => { setText(legacy); setMode(null); setPhoto(true) }}>Слот с фото</button>
    <TelegramTextEditor value={text} parseMode={mode} onChange={(value, parseMode) => {
      setText(value)
      setMode(parseMode)
    }} />
    <output aria-label="Saved draft" className="mt-4 block break-all text-xs">{JSON.stringify({ text, parse_mode: mode })}</output>
    </section><section aria-label="Предпросмотр Telegram" className="min-w-0">
      <PhonePreview content={{ type: 'message', messages: [{ type: photo ? 'photo' : 'text', text,
        caption: photo ? text : undefined, parse_mode: mode, ...(photo ? { media: { source: 'telegram_file_id', telegram_file_id: 'fixture-photo' } } : {}) }] }} mediaPreviewUrls={{}} />
    </section>
  </main>
}

createRoot(document.getElementById('root')!).render(<Fixture />)

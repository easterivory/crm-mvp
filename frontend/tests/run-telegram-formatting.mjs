import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5183'
const output = new URL('../../tmp/telegram-formatting/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/__telegram-formatting', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218;color:white"><div id="root"></div><script type="module" src="/tests/telegram-formatting.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__telegram-formatting')
    const editor = page.locator('textarea')
    const source = '<b>Offer</b>\n1. <a href="https://t.me/+example">Contact</a>'
    assert.equal(await page.getByRole('checkbox').count(), 0)
    await page.getByRole('toolbar', { name: 'Оформление текста' }).waitFor()
    await editor.fill(source)
    assert.equal(await editor.inputValue(), source)
    const draft = JSON.parse(await page.getByLabel('Saved draft').innerText())
    assert.equal(draft.text, source)
    assert.equal(draft.parse_mode, 'HTML')
    const preview = page.getByLabel('Предпросмотр сообщения')
    assert.equal(await preview.innerText(), 'Offer\n1. Contact')
    assert.equal(await preview.locator('strong').innerText(), 'Offer')
    const phone = page.getByLabel('Предпросмотр Telegram')
    assert.equal(await phone.locator('strong').innerText(), 'Offer')
    assert.equal(await phone.getByRole('link', { name: 'Contact' }).getAttribute('href'), 'https://t.me/+example')
    assert.equal(await page.getByRole('alert').count(), 0)
    await page.screenshot({ path: output + `editor-${width}.png`, fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.getByRole('button', { name: 'Убрать всё оформление' }).click()
    assert.equal(await editor.inputValue(), 'Offer\n1. Contact')
    await page.getByRole('button', { name: 'Текстовый слот', exact: true }).click()
    assert.equal(JSON.parse(await page.getByLabel('Saved draft').innerText()).parse_mode, null)
    assert.equal(await phone.locator('strong').innerText(), 'Offer')
    await page.getByRole('button', { name: 'Слот с фото', exact: true }).click()
    assert.equal(await phone.locator('strong').innerText(), 'Offer')
    assert.equal(await phone.getByRole('link', { name: 'Contact' }).getAttribute('href'), 'https://t.me/+example')
    await page.screenshot({ path: output + `photo-${width}.png`, fullPage: true })
    await page.getByRole('button', { name: 'Убрать всё оформление' }).click()
    await editor.fill('5 < 10 & "yes"')
    assert.equal(await preview.innerText(), '5 < 10 & "yes"')
    const escaped = '&lt;a href=&quot;https://t.me/example&quot;&gt;Contact&lt;/a&gt;'
    await editor.fill(escaped)
    await page.getByRole('alert').filter({ hasText: 'экранированные HTML-теги' }).waitFor()
    assert.equal(await editor.inputValue(), escaped)
    await editor.fill('<b>Offer</b> <a href=&quot;https://t.me/example>Contact</a>')
    await page.getByRole('alert').filter({ hasText: 'Некорректный href' }).waitFor()
    assert.equal(await phone.getByRole('link').count(), 0)
    await editor.fill('<b>Offer')
    await page.getByRole('alert').filter({ hasText: 'Не закрыты теги' }).waitFor()
    assert.equal(await phone.locator('strong').count(), 0)
    await editor.fill('<a href="javascript:alert(1)">Unsafe</a>')
    await page.getByRole('alert').filter({ hasText: 'Некорректный href' }).waitFor()
    assert.equal(await phone.getByRole('link').count(), 0)
    await page.getByRole('button', { name: 'Убрать всё оформление' }).click()
    await editor.fill('5 < 10 & "yes"')
    await editor.press('ControlOrMeta+A')
    await page.getByRole('button', { name: 'Жирный', exact: true }).click()
    assert.equal(await preview.locator('strong').innerText(), '5 < 10 & "yes"')
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Telegram formatting controls passed at 390px and 1440px')
} finally { await browser.close() }

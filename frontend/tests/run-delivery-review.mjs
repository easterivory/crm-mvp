import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5184'
const output = new URL('../../tmp/delivery-review/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    const errors = [], writes = []
    page.on('pageerror', e => errors.push(e.message))
    page.on('dialog', dialog => dialog.accept())
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      let result
      if (path.endsWith('/backup/transport')) result = { stage: 'failed', mode: 'cloud', host: 'api.telegram.org', effective_limit_mb: 49,
        local_created: true, telegram_sent: false, size_bytes: 698045667, warning: 'Для больших бэкапов нужен отдельный Local Bot API' }
      else if (request.method() === 'POST') { writes.push({ path, ...request.postDataJSON() }); result = { status: 'pending' } }
      else result = [
        { id: 'safe', chat_id: 'chat-safe', kind: 'input', status: 'review', failure_count: 1, fingerprint: 'a'.repeat(64), can_retry: true, diagnostics: { error_type: 'DBAPIError', sqlstate: '22001', field: 'country' } },
        { id: 'legacy', chat_id: 'chat-legacy', kind: 'start', status: 'review', failure_count: 0, fingerprint: 'b'.repeat(64), can_retry: false, diagnostics: {} }]
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) })
    })
    await page.route('**/__delivery-review', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218"><div id="root"></div><script type="module" src="/tests/delivery-review.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__delivery-review')
    await page.getByText('Нужна сверка', { exact: true }).waitFor()
    const retry = page.getByTitle('Повторить безопасное задание')
    assert.equal(await retry.count(), 1)
    assert.equal(await retry.isDisabled(), true)
    assert.equal(writes.length, 0)
    await page.getByLabel('Основание повтора').fill('Проверено техником')
    const request = page.waitForRequest(r => r.method() === 'POST')
    await retry.click(); await request
    assert.equal(writes.length, 1); assert.equal(writes[0].fingerprint, 'a'.repeat(64))
    await page.getByText(/665.7 МБ/).waitFor()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(errors, [])
    await page.screenshot({ path: output + `review-${width}.png`, fullPage: true })
    await page.close()
  }
  console.log('Recovery requires evidence and a reason; unknown deliveries cannot replay; backup warning and responsive layout passed')
} finally { await browser.close() }

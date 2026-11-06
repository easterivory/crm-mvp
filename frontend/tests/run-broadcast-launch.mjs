import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5184'
const output = new URL('../../tmp/broadcast-launch/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const scenario of [
    { count: 1000, width: 1440 }, { count: 23852, width: 1440 },
    { count: 23852, width: 390, scheduled: true },
    { count: 23852, width: 390, status: 422, detail: 'Audience is empty' },
    { count: 23852, width: 1440, status: 503 },
  ]) {
    const page = await browser.newPage({ viewport: { width: scenario.width, height: 1000 } })
    const errors = [], launches = []
    page.on('pageerror', error => errors.push(error.message))
    let draft
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      let result
      if (path.endsWith('/audience/preview')) result = { count: scenario.count, sample: [] }
      else if (request.method() === 'PATCH') {
        draft = { ...request.postDataJSON(), id: 'qa-draft', status: 'draft' }; result = draft
      } else if (path.endsWith('/send-now') || path.endsWith('/schedule')) {
        const data = request.postDataJSON(); launches.push({ path, data })
        const status = data.confirmation !== 'ПОДТВЕРЖДАЮ' ? 422 : scenario.status || 200
        result = status === 200
          ? { broadcast: { ...draft, status: scenario.scheduled ? 'scheduled' : 'processing' }, audience: { count: scenario.count, sample: [] } }
          : { detail: scenario.detail || 'Unavailable' }
        await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(result) }); return
      } else result = path.endsWith('/report')
        ? { status: 'processing', total_recipients: scenario.count, sent_count: 0, failed_count: 0, error_examples: [] } : []
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) })
    })
    await page.route('**/__broadcast-launch', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218"><div id="root"></div><script type="module" src="/tests/broadcast-launch.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__broadcast-launch')
    await page.getByRole('button', { name: '2. Аудитория', exact: true }).click()
    await page.getByRole('button', { name: 'Далее', exact: true }).waitFor({ state: 'visible' })
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Далее')?.disabled)
    await page.getByRole('button', { name: '4. Безопасность', exact: true }).click()
    if (scenario.scheduled) {
      await page.getByRole('button', { name: 'Запланировать', exact: true }).click()
      await page.locator('input[type="datetime-local"]').fill('2099-11-06T15:00')
    }
    const hold = page.getByRole('button', { name: /Удерживайте 2 секунды/ })
    // Leaving the safety step cancels an incomplete hold, never launching in the background.
    await hold.dispatchEvent('mousedown'); await page.waitForTimeout(250)
    await page.getByRole('button', { name: '3. Автоматизация', exact: true }).click()
    await page.waitForTimeout(2100); assert.equal(launches.length, 0)
    await page.getByRole('button', { name: '4. Безопасность', exact: true }).click()
    if (scenario.width === 390) {
      await hold.dispatchEvent('touchstart'); await page.waitForTimeout(2300); await hold.dispatchEvent('touchend')
    } else {
      await hold.dispatchEvent('mousedown'); await page.waitForTimeout(2300); await page.mouse.up()
    }
    await page.waitForTimeout(250)
    assert.equal(launches.length, 1)
    assert.equal(launches[0].data.confirmation, 'ПОДТВЕРЖДАЮ')
    assert.equal(launches[0].path.endsWith(scenario.scheduled ? '/schedule' : '/send-now'), true)
    if (scenario.scheduled) assert.ok(launches[0].data.scheduled_at)
    if (scenario.detail) await page.getByText(scenario.detail, { exact: true }).waitFor()
    if (scenario.status === 503) await page.getByText(/запуск мог уже сохраниться/).waitFor()
    assert.deepEqual(errors, [])
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: output + `${scenario.width}-${scenario.scheduled ? 'scheduled' : scenario.status || scenario.count}.png`, fullPage: true })
    await page.close()
  }
  console.log('Broadcast hold confirmation: small/large audiences, now/scheduled, mobile/desktop, unmount cancellation and error details passed (mock API only)')
} finally { await browser.close() }

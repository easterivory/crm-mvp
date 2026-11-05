import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5181'
const output = new URL('../../tmp/postbacks-ui/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    for (const format of ['gambling', 'submission']) {
      const page = await browser.newPage({ viewport: { width, height: 1050 } })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      page.on('dialog', dialog => dialog.accept())
      let endpoints = []
      let dryRuns = 0
      const receipt = { id: 'receipt', lead_id: null, status: 'unmatched', request_method: 'POST', event_type: 'registration',
        error_message: 'No exact identity match', endpoint_revision: 1, created_at: '2026-11-04T09:00:00Z',
        query_payload: {}, body_payload: { event_id: 'sample-operation' }, attempt_log: [] }
      await page.route('**/__postbacks', route => route.fulfill({ contentType: 'text/html', body:
        '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218;color:white"><div id="root"></div><script type="module" src="/tests/postbacks.fixture.tsx"></script></body></html>' }))
      await page.route('**/api/v1/**', async route => {
        const request = route.request()
        const path = new URL(request.url()).pathname
        if (path.endsWith('/projects/qa')) return route.fulfill({ json: { project_format: format } })
        if (path.endsWith('/partners')) return route.fulfill({ json: { items: [], total: 0, limit: 100, offset: 0 } })
        if (path.endsWith('/transport')) return route.fulfill({ json: { origin: 'https://postbacks.example.com', mode: 'relay',
          configuration_status: 'relay_configured', gateway_reachable: true, legacy_status_route_enabled: false } })
        if (path.endsWith('/followups')) return route.fulfill({ json: [] })
        if (path.endsWith('/postback-endpoints')) {
          if (request.method() === 'POST') {
            const payload = request.postDataJSON()
            assert.equal(payload.partner_integration_id, null)
            assert.equal(payload.processing_kind, 'lifecycle_event')
            assert.equal(payload.parameter_mapping.require_event_id, true)
            endpoints = [{ ...payload, id: 'endpoint', project_id: 'qa', url: 'https://postbacks.example.com/pb/secret',
              delivery_mode: 'relay', revision: 1, created_at: receipt.created_at, updated_at: receipt.created_at }]
            return route.fulfill({ status: 201, json: endpoints[0] })
          }
          return route.fulfill({ json: endpoints })
        }
        if (path.endsWith('/receipts')) return route.fulfill({ json: [receipt] })
        if (path.endsWith('/dry-run')) { dryRuns++; return route.fulfill({ json: { status: 'matched', lead_id: 'lead', revision: 1 } }) }
        if (path.endsWith('/reprocess')) { receipt.status = 'processed'; receipt.lead_id = 'lead'; receipt.error_message = null; return route.fulfill({ json: { status: 'processed' } }) }
        return route.fulfill({ status: 404, json: { detail: path } })
      })
      await page.goto(origin + '/__postbacks')
      await page.getByText('https://postbacks.example.com', { exact: true }).waitFor()
      if (format === 'gambling') assert.equal(await page.getByRole('tab', { name: 'Отправка покупателю' }).count(), 0)
      await page.getByPlaceholder('Депозиты партнёра').fill('Казино · регистрация')
      await page.getByRole('button', { name: 'Создать endpoint', exact: true }).click()
      await page.getByText('https://postbacks.example.com/pb/secret', { exact: true }).waitFor()
      await page.getByLabel('Образец постбэка').fill('{"lead_id":"test","event_id":"reg-1"}')
      await page.getByRole('button', { name: 'Проверить без записи' }).click()
      await page.getByRole('status').filter({ hasText: 'matched' }).waitFor()
      assert.equal(dryRuns, 1)
      await page.getByRole('button', { name: 'Повторно разобрать' }).click()
      await page.getByText('processed', { exact: true }).waitFor()
      await page.getByText('Детали запроса', { exact: true }).click()
      await page.getByText('sample-operation', { exact: false }).last().waitFor()
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
      await page.screenshot({ path: output + `${format}-${width}.png`, fullPage: true })
      if (format === 'submission') {
        await page.getByRole('tab', { name: 'Отправка покупателю' }).click()
        await page.getByText('Домен получателя: не задан', { exact: true }).waitFor()
      }
      assert.deepEqual(errors, [])
      await page.close()
    }
  }
  console.log('Postback receive-only, direction, domain, save, dry-run and reprocess controls passed at 390px and 1440px')
} finally { await browser.close() }

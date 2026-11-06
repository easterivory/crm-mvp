import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5184'
const output = new URL('../../tmp/gambling-offers/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    page.on('dialog', dialog => dialog.accept())
    const errors = [], unexpected = [], offers = [], policies = []
    let endpoint = null
    let lastOfferPayload
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/api/v1/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1', ''), method = request.method()
      let body
      if (path === '/gambling-offers' && method === 'GET') body = offers
      else if (path === '/gambling-offers/payout-policies' && method === 'GET') body = policies
      else if (path === '/gambling-offers/payout-policies' && method === 'POST') {
        policies.push({ ...request.postDataJSON(), id: 'policy-1', version: 1 }); body = { id: 'policy-1', version: 1 }
      } else if ((path === '/gambling-offers' && method === 'POST') || (path === '/gambling-offers/offer-1' && method === 'PUT')) {
        lastOfferPayload = request.postDataJSON()
        const value = { ...lastOfferPayload, id: 'offer-1', project_id: 'qa-project', endpoint_id: lastOfferPayload.postbacks_enabled ? 'endpoint-1' : null }
        if (value.postbacks_enabled) endpoint = { id: 'endpoint-1', url: 'https://postbacks.example.org/pb/mock-secret', is_active: false, delivery_mode: 'relay' }
        offers.splice(0, offers.length, value); body = value
      } else if (path === '/gambling-offers/offer-1/settings') body = { ...offers[0], postback: endpoint }
      else if (path === '/postback-endpoints/endpoint-1' && method === 'PATCH') { endpoint = { ...endpoint, ...request.postDataJSON() }; body = endpoint }
      else if (path === '/projects/qa-project') body = { project_format: 'gambling' }
      else if (path === '/gambling-offers/funnel-versions/qa-version') body = { offer_id: method === 'PUT' ? request.postDataJSON().offer_id : null }
      else if (path === '/leads/qa-lead/deposit-summary') body = { events: [
        { id: 'reg', event_type: 'registration', occurred_at: '2026-11-06T07:00:00Z', amount: null, currency: null },
        { id: 'fd', event_type: 'deposit', occurred_at: '2026-11-06T08:00:00Z', amount: '50.25', currency: 'USD' },
        { id: 'rd', event_type: 'redeposit', occurred_at: '2026-11-06T09:00:00Z', amount: '100.00', currency: 'USD' }],
        total_events: 3, totals: [{ currency: 'USD', amount: '150.25', unknown_amount_count: 0 }], automatic_tracking: false, data_complete: false }
      else if (path === '/gambling-offers/finance') body = { rows: [{ policy_id: 'policy-1', policy_name: 'CPA private', version: 1,
        offer_id: 'offer-1', qualified_fd: 1, pending_fd: 0, rejected_fd: 0, currency: 'USD', estimated_commission: '777.00',
        period_from: '2026-10-31T21:00:00Z', period_to_exclusive: '2026-11-30T21:00:00Z' }], unpriced_fd_all_time: 0 }
      else if (path === '/gambling-offers/qualification') body = []
      else if (path === '/gambling-offers/coverage') body = { incomplete: true }
      else if (path === '/tags') body = { items: [], total: 0 }
      else if (path === '/tracking/metrics/step-options') body = []
      else if (path === '/tracking/metrics/cohort-conversion') body = { base: 10, converted: 0, percent: 0 }
      else { unexpected.push([method, path]); body = {} }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.route('**/__gambling-offers', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218"><div id="root"></div><script type="module" src="/tests/gambling-offers.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__gambling-offers')
    const settings = page.getByRole('region', { name: 'Гембл-офферы' })
    await settings.getByRole('tab', { name: 'Условия выплат', exact: true }).click()
    await settings.getByRole('button', { name: 'Условия выплаты', exact: true }).click()
    await settings.getByLabel('Название условий', { exact: true }).fill('CPA private')
    await settings.getByLabel('Партнёрская программа', { exact: true }).fill('PP')
    await settings.getByLabel('Ставка за FD', { exact: true }).fill('777')
    await settings.getByRole('button', { name: 'Порог', exact: true }).click()
    await settings.getByLabel('Порог FD', { exact: true }).fill('10')
    await settings.getByLabel('Размер мотивации', { exact: true }).fill('888')
    await settings.getByRole('button', { name: 'Сохранить условия', exact: true }).click()
    await settings.getByText('CPA private · v1', { exact: true }).waitFor()
    await settings.getByRole('tab', { name: 'Офферы', exact: true }).click()
    await settings.getByRole('button', { name: 'Оффер', exact: true }).click()
    await settings.getByLabel('Название', { exact: true }).fill('Offer with a long name for mobile layout')
    await settings.getByLabel('Партнёрская программа', { exact: true }).fill('PP')
    const original = 'https://example.org/click?campaign=a%20b&campaign=c+d#top'
    await settings.getByLabel('Исходная ссылка', { exact: true }).fill(original)
    await settings.getByLabel('Условия выплаты', { exact: true }).selectOption('policy-1')
    await settings.getByRole('button', { name: 'Сохранить оффер', exact: true }).click()
    await settings.getByRole('button', { name: 'Редактировать оффер' }).waitFor()
    assert.equal(lastOfferPayload.source_url, original)
    assert.equal(lastOfferPayload.postback_mapping, null)
    await settings.getByLabel('Использовать постбэки', { exact: true }).check()
    await settings.getByRole('button', { name: 'Сохранить оффер', exact: true }).click()
    await settings.getByLabel('Адрес приёма постбэков', { exact: true }).waitFor()
    assert.equal(await settings.getByLabel('Адрес приёма постбэков', { exact: true }).inputValue(), 'https://postbacks.example.org/pb/mock-secret')
    await settings.getByLabel('Приём постбэков включён', { exact: true }).click()
    await page.waitForFunction(() => Array.from(document.querySelectorAll('label')).some(label =>
      label.textContent.includes('Приём постбэков включён') && label.querySelector('input')?.checked))
    await page.screenshot({ path: output + `offer-${width}.png`, fullPage: true })
    const manager = page.getByRole('region', { name: 'Карточка менеджера', exact: true })
    assert.match(await manager.innerText(), /150.25 USD/)
    assert.doesNotMatch(await manager.innerText(), /777|private|вознаграждение|выплат/i)
    const conversions = page.locator('.tracking-ratio-value strong')
    assert.deepEqual(await conversions.allInnerTexts(), ['—', '—'])
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await settings.getByRole('tab', { name: 'Вознаграждение', exact: true }).click()
    await settings.getByLabel('Программа выплат', { exact: true }).selectOption('policy-1')
    const reportRequest = page.waitForRequest(request => request.url().includes('/gambling-offers/finance?'))
    await settings.getByRole('button', { name: 'Рассчитать', exact: true }).click()
    assert.equal(new URL((await reportRequest).url()).searchParams.get('policy_id'), 'policy-1')
    await settings.getByRole('cell', { name: '777.00 USD', exact: true }).waitFor()
    await page.screenshot({ path: output + `finance-${width}.png`, fullPage: true })
    assert.deepEqual(errors, [])
    assert.deepEqual(unexpected, [])
    await page.close()
  }
  console.log('Offer/payout forms, domain visibility, deposit card and incomplete conversions passed at 390px and 1440px')
} finally { await browser.close() }

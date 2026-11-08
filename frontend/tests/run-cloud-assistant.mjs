import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5184'
const output = new URL('../../tmp/cloud-assistant/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    const errors = [], writes = []
    page.on('pageerror', error => errors.push(error.message))
    let state = 'pending_approval'
    const proposal = () => ({ id: 'qa-proposal', project_id: 'qa-project', status: state, plan_hash: 'a'.repeat(64),
      expires_at: '2099-11-07T20:00:00Z', effects: [{ kind: 'offer.create_inactive', target_id: null, before: null,
        after: { name: 'Оффер с длинным названием для проверки адаптивности на узком экране', partner_name: 'QA PP',
          url: { host: 'example.org', query_parameters: ['sub1'] }, secure_input_ref: 'qa-input', is_active: false,
          postback_mapping: { identifier_param: 'sub1', event_type_param: 'event', external_event_id_param: 'transaction_id' } } }], result: null, error_code: null })
    await page.route('**/api/v1/assistant/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      let data
      if (request.method() === 'POST') {
        writes.push({ path, body: request.postDataJSON() })
        if (path.endsWith('/reveal')) data = { value: 'https://example.org/?partner=private-qa-value' }
        else if (path.endsWith('/approve-and-apply')) { state = 'applied'; data = proposal() }
        else throw new Error('Unexpected mutation: ' + path)
      } else if (path.endsWith('/status')) data = { enabled: true, allowed: true, mcp_enabled: true, changes_enabled: true, resource_url: 'https://assistant.example/mcp' }
      else if (path.endsWith('/projects')) data = [{ id: 'qa-project', name: 'Ру гембл QA' }]
      else if (path.endsWith('/connections')) data = [{ id: 'qa-connection', client_id: 'qa-client', project_ids: ['qa-project'], scopes: ['crm.catalog.read'], revoked_at: null }]
      else if (path.endsWith('/proposals')) data = [proposal()]
      else data = proposal()
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    })
    await page.route('**/__cloud-assistant**', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218"><div id="root"></div><script type="module" src="/tests/cloud-assistant.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__cloud-assistant?assistant_proposal=qa-proposal')
    const approve = page.getByRole('button', { name: 'Применить изменения' })
    await approve.waitFor(); assert.equal(writes.length, 0); assert.equal(await approve.isDisabled(), true)
    await page.getByRole('checkbox', { name: /Подтверждаю показанные изменения/ }).check()
    assert.equal(await approve.isDisabled(), true)
    assert.equal(await page.getByText(/private-qa-value/).count(), 0)
    await page.getByRole('button', { name: 'Проверить исходный адрес' }).click()
    await page.getByText('https://example.org/?partner=private-qa-value', { exact: true }).waitFor()
    assert.equal(writes.length, 1); assert.equal(await approve.isEnabled(), true)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: output + `approval-${width}.png`, fullPage: true })
    await approve.click()
    await page.getByText('Результат сохранён. Настройки остаются в согласованном состоянии.', { exact: true }).waitFor()
    assert.equal(writes.filter(w => w.path.endsWith('/approve-and-apply')).length, 1)
    assert.equal(writes[1].body.expected_plan_hash, 'a'.repeat(64))
    assert.equal(await approve.count(), 0)
    assert.deepEqual(errors, [])
    await page.close()
  }
  for (const [from, search, expected] of [
    ['/settings', '?assistant_proposal=qa-plan', '/settings?assistant_proposal=qa-plan'],
    ['/settings', '?assistant_authorize=client_id%3Dqa', '/settings?assistant_authorize=client_id%3Dqa'],
    ['/settings', '?tab=project', '/chats'],
    ['https://evil.example', '?assistant_proposal=qa-plan', '/chats'],
  ]) {
    const page = await browser.newPage()
    await page.route('**/api/v1/**', route => {
      const path = new URL(route.request().url()).pathname
      const data = path.endsWith('/users/login') ? { access_token: 'qa-only-login' } : path.endsWith('/users/me')
        ? { id: 'qa-user', role_name: 'super_admin', email: 'qa@example.org' } : { is_configured: false }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    })
    await page.route('**/__assistant-login**', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body><div id="root"></div><script type="module" src="/tests/cloud-assistant-login.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__assistant-login?' + new URLSearchParams({ from, search }))
    await page.getByLabel('Email').fill('qa@example.org')
    await page.getByLabel('Пароль', { exact: true }).fill('qa-placeholder')
    await page.getByRole('button', { name: 'Войти', exact: true }).click()
    await page.getByText(expected, { exact: true }).waitFor()
    await page.close()
  }
  console.log('Cloud assistant UI: explicit approval + private source review, 390/1440px, login return and redirect isolation passed')
} finally { await browser.close() }

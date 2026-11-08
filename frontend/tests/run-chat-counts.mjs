import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5186'
const output = new URL('../../tmp/chat-counts-qa/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    const errors = [], requests = []
    let fail = true, gate, held
    page.on('pageerror', e => errors.push(e.message))
    await page.addInitScript(() => {
      localStorage.setItem('crm:selectedProjectId', 'qa-project')
      localStorage.setItem('user', JSON.stringify({ id: 'qa-user', name: 'QA', role_name: 'superadmin' }))
    })
    await page.route('**/api/v1/**', async route => {
      const url = new URL(route.request().url()), path = url.pathname.replace('/api/v1', '')
      assert.equal(route.request().method(), 'GET', 'UI fixture must never write')
      requests.push(path)
      let result = [], status = 200
      if (path === '/chats/workspace-counts') {
        const currentGate = gate
        if (currentGate) { held?.(); await currentGate }
        if (fail) { status = 503; result = { detail: 'Счётчики временно недоступны. Повторите запрос.' } }
        else result = { all: url.searchParams.get('project_id') === 'qa-other' ? 43 : 17,
          unread: 8, mine: 3, favorites: 1, priority: 2, priority_enabled: true, unanswered: 5 }
      } else if (path === '/chats' || ['/bots', '/tracking/link-options', '/tags', '/users'].includes(path)) result = { items: [], total: 0 }
      else if (/^\/projects\/[^/]+$/.test(path)) result = { id: 'qa-project', project_format: 'submission' }
      try { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(result) }) }
      catch (error) { if (!route.request().failure()) throw error }
    })
    await page.route('**/__chat-counts', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218"><div id="root"></div><script type="module" src="/tests/chat-counts.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__chat-counts')
    await page.getByRole('status').filter({ hasText: 'Счётчики недоступны' }).waitFor()
    if (width < 768) await page.getByRole('button', { name: /^Поиск и фильтры/ }).click()
    const all = page.getByRole('button', { name: /^Все\s/ })
    assert.match(await all.innerText(), /\.\.\./)
    assert.equal(await page.getByLabel('Закрыть уведомление').count(), 0)
    fail = false
    await page.getByTitle('Обновить чаты').click()
    await page.getByRole('button', { name: /^Все\s+17$/ }).waitFor()

    // Multiple triggers while the same count request is pending share one request.
    let release
    gate = new Promise(resolve => { release = resolve })
    const began = new Promise(resolve => { held = resolve })
    await page.getByTitle('Обновить чаты').click(); await began
    const pending = requests.filter(p => p === '/chats/workspace-counts').length
    await page.getByTitle('Обновить чаты').click()
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
    await page.waitForTimeout(100)
    assert.equal(requests.filter(p => p === '/chats/workspace-counts').length, pending)
    const sharedResponse = page.waitForResponse(r => r.url().includes('/chats/workspace-counts'))
    gate = undefined; release(); await sharedResponse
    await page.waitForTimeout(100)

    fail = true
    await page.getByTitle('Обновить чаты').click()
    await page.getByRole('status').filter({ hasText: 'Счётчики не обновлены' }).waitFor()
    assert.match(await all.innerText(), /17/)
    assert.equal(await page.getByLabel('Закрыть уведомление').count(), 0)

    // A filter change reloads the list, not project metadata or global counts.
    const metadata = () => requests.filter(p => p !== '/chats' && p !== '/chats/workspace-counts').length
    const beforeMetadata = metadata(), beforeCounts = requests.filter(p => p === '/chats/workspace-counts').length
    const listRequest = page.waitForRequest(r => new URL(r.url()).pathname === '/api/v1/chats')
    await page.getByRole('button', { name: /^Мои\s/ }).click(); await listRequest
    await page.waitForTimeout(100)
    assert.equal(metadata(), beforeMetadata)
    assert.equal(requests.includes('/tracking/links'), false)
    assert.equal(requests.includes('/tracking/link-options'), true)
    assert.equal(requests.filter(p => p === '/chats/workspace-counts').length, beforeCounts)
    await page.screenshot({ path: output + `counts-warning-${width}.png`, fullPage: true })

    // Old-scope results cannot overwrite new-scope counts, including after abort.
    fail = false
    gate = new Promise(resolve => { release = resolve })
    const oldBegan = new Promise(resolve => { held = resolve })
    await page.getByTitle('Обновить чаты').click(); await oldBegan
    gate = undefined
    await page.getByRole('button', { name: 'QA project', exact: true }).click()
    await page.getByRole('button', { name: /^Все\s+43$/ }).waitFor()
    release(); await page.waitForTimeout(100)
    assert.match(await all.innerText(), /43/)
    const botRequest = page.waitForRequest(r => r.url().includes('workspace-counts') && r.url().includes('bot_id=qa-bot'))
    const botListRequest = page.waitForRequest(r => new URL(r.url()).pathname === '/api/v1/chats' && r.url().includes('bot_id=qa-bot'))
    await page.getByRole('button', { name: 'QA bot', exact: true }).click()
    await Promise.all([botRequest, botListRequest])
    await page.waitForLoadState('networkidle')

    await page.clock.install()
    await page.evaluate(() => Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' }))
    const hiddenRequests = requests.length
    await page.clock.fastForward(31000); await page.waitForTimeout(100)
    assert.deepEqual(requests.slice(hiddenRequests), [], 'Hidden tab must not poll')
    const visibleRequest = page.waitForRequest(r => r.url().includes('/chats/workspace-counts'))
    const hiddenCounts = requests.filter(p => p === '/chats/workspace-counts').length
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await visibleRequest
    await page.waitForTimeout(100)
    assert.equal(requests.filter(p => p === '/chats/workspace-counts').length, hiddenCounts + 1)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Chat counts: failure/last values, no toast spam, single flight, scope cancellation, isolated filters, hidden polls and responsive layout passed')
} finally { await browser.close() }

import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5181'
const output = new URL('../../tmp/hold-schedule/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 } })
    const errors = []
    const diagnostics = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => { if (message.type() === 'error') diagnostics.push(message.text()) })
    page.on('requestfailed', request => diagnostics.push(`${request.url()} ${request.failure()?.errorText}`))
    page.on('response', response => { if (response.status() >= 400) diagnostics.push(`${response.status()} ${response.url()}`) })
    let schedule = { enabled: false, timezone: 'Europe/Moscow', cutoff_time: '18:00', working_days: [0, 1, 2, 3, 4, 5], before_cutoff: 'today', closed_dates: [] }
    let version = { hold_mode: 'manual', is_hold_active: false }
    let saves = 0
    await page.route('**/__hold-schedule', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218;color:white"><div id="root"></div><script type="module" src="/tests/hold-schedule.fixture.tsx"></script></body></html>' }))
    await page.route('**/__qa-version', route => route.fulfill({ json: version }))
    await page.route('**/api/v1/**', async route => {
      const request = route.request()
      if (request.url().includes('/projects/qa')) {
        if (request.method() === 'PATCH') { schedule = request.postDataJSON().hold_schedule; saves++ }
        return route.fulfill({ json: { hold_schedule: schedule } })
      }
      if (request.url().includes('/toggle-hold')) {
        version = request.postDataJSON()
        return route.fulfill({ json: version })
      }
      return route.fulfill({ status: 404, json: {} })
    })
    await page.goto(origin + '/__hold-schedule')
    try {
      await page.getByRole('checkbox', { name: 'Расписание включено' }).check()
    } catch (error) {
      console.error('Browser errors:', errors)
      console.error('Network/console:', diagnostics)
      console.error((await page.locator('body').innerText()).slice(0, 2000))
      throw error
    }
    await page.getByLabel('Время отсечки').fill('17:30')
    await page.getByLabel('Нерабочие даты').fill('2026-11-09\n2026-11-10')
    await page.getByRole('button', { name: 'Сохранить расписание HOLD' }).click()
    await page.getByText('Расписание сохранено').waitFor()
    assert.equal(saves, 1)
    assert.equal(schedule.cutoff_time, '17:30')
    assert.deepEqual(schedule.closed_dates, ['2026-11-09', '2026-11-10'])
    assert.ok(!schedule.working_days.includes(6))
    await page.getByLabel('Режим HOLD').selectOption('project_schedule')
    await page.getByText('Расписание проекта', { exact: true }).waitFor()
    assert.equal(version.hold_mode, 'project_schedule')
    await page.screenshot({ path: output + `schedule-${width}.png`, fullPage: true })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.getByLabel('Режим HOLD').selectOption('manual')
    await page.getByRole('button', { name: 'Hold выключен', exact: true }).click()
    await page.getByRole('button', { name: 'Hold включён', exact: true }).waitFor()
    assert.equal(version.is_hold_active, true)
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('HOLD schedule controls passed at 390px and 1440px')
} finally { await browser.close() }

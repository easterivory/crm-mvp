import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}) })
const origin = process.env.CRM_UI_TEST_URL || 'http://127.0.0.1:5184'
const output = new URL('../../tmp/chatterfy-import/', import.meta.url).pathname
await mkdir(output, { recursive: true })
try {
  for (const width of [390, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/__chatterfy-import', route => route.fulfill({ contentType: 'text/html', body:
      '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><script type="module">import RefreshRuntime from "/@react-refresh"; RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type; window.__vite_plugin_react_preamble_installed__=true;</script></head><body style="margin:0;background:#101218"><div id="root"></div><script type="module" src="/tests/chatterfy-import.fixture.tsx"></script></body></html>' }))
    await page.goto(origin + '/__chatterfy-import')
    const source = page.getByLabel('Источник Chatterfy')
    await source.waitFor()
    assert.match(await source.innerText(), /<script>alert\(1\)<\/script>/)
    assert.equal(await source.locator('script').count(), 0)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: output + `source-${width}.png`, fullPage: true })
    await page.getByRole('button').click()
    assert.equal(await source.count(), 0)
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Chatterfy source card passed at 390px and 1440px')
} finally { await browser.close() }

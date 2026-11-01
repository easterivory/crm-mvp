// Isolated browser checks: every API request is intercepted; no real leads or tokens.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/Users/art/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM })
  const output = path.join(process.cwd(), 'tmp', 'advertising-ui')
  fs.mkdirSync(output, { recursive: true })
  try {
    for (const size of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
      const context = await browser.newContext({ viewport: size })
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', error => { errors.push(error.message); console.error(error.message) })
      const project = { id: 'project', name: 'Вакансии', status: 'active', project_format: 'submission' }
      let slot = { id: 'slot', name: 'Оффер покупателя', enabled: true, position: 0, delay_minutes: 120, revision: 1,
        content_json: { type: 'message', messages: [{ type: 'text', text: 'Рекламный пост с предложением', buttons: [{ label: 'Подробнее', type: 'url', url: 'https://example.com' }] }] } }
      await context.addInitScript(({ project }) => {
        localStorage.setItem('token', 'local-ui-test')
        localStorage.setItem('user', JSON.stringify({ id: 'admin', name: 'Локальный тест', role_name: 'super_admin', project_id: project.id }))
        localStorage.setItem('crm:selectedProjectId', project.id)
      }, { project })
      await page.route('**/api/**', async route => {
        const request = route.request(), url = new URL(request.url()), p = url.pathname.replace(/\/$/, '')
        if (!p.startsWith('/api/')) return route.continue()
        if (['/api/v1/tags', '/api/v1/bots'].includes(p) && Number(url.searchParams.get('limit')) > 100) {
          return route.fulfill({ status: 422, json: { detail: [{ loc: ['query', 'limit'], msg: 'Input should be less than or equal to 100' }] } })
        }
        let data = { items: [], total: 0 }
        if (p === '/api/ui-host-context') data = { crm_ui_allowed: true }
        else if (p.endsWith('/advertising/settings')) data = { enabled: true, bot_ids: ['bot'], protected_tag_ids: ['hot'], audience_tag_id: 'ad', timeout_minutes: 180 }
        else if (p.endsWith('/advertising/slots/slot') && request.method() === 'PUT') { slot = { id: 'slot', ...request.postDataJSON(), revision: 2 }; data = slot }
        else if (p.endsWith('/advertising/slots')) data = [slot]
        else if (p.endsWith('/bots')) data = { items: [{ id: 'bot', name: 'Вакансии бот', transport_type: 'bot_api', project_id: 'project' }], total: 1 }
        else if (p.endsWith('/tags')) {
          const tags = [{ id: 'hot', name: 'HOT HOT' }, { id: 'ad', name: 'Материал для рекламы' },
            ...Array.from({ length: 98 }, (_, i) => ({ id: `tag-${i}`, name: `Тег ${i}` })),
            { id: 'last', name: 'Защита со второй страницы' }]
          const offset = Number(url.searchParams.get('offset') || 0)
          data = { items: tags.slice(offset, offset + 100), total: tags.length }
        }
        else if (p.endsWith('/projects')) data = { items: [project], total: 1 }
        else if (p.endsWith('/advertising/backfill/preview')) data = { preview_id: 'preview', count: 25, sample_chat_ids: ['local-chat'] }
        else if (p.endsWith('/advertising/backfill/start')) { assert.equal(request.postDataJSON().confirmation, 'ЗАПУСТИТЬ'); data = { run_id: 'run', state: 'queued' } }
        else if (p.endsWith('/advertising/tracking')) data = { cohort_counts: { active: 123, completed: 456 }, slots: [{ slot_id: 'slot', name: slot.name, status: 'sent', count: 579 }], sources: [{ tracking_link_id: null, count: 579 }] }
        await route.fulfill({ json: data })
      })
      await page.goto('http://127.0.0.1:5177/advertising')
      await page.screenshot({ path: path.join(output, `initial-${size.width}.png`), fullPage: true })
      await page.getByRole('button', { name: '#1 Оффер покупателя' }).click()
      await page.getByRole('button', { name: 'Сохранить слот', exact: true }).click()
      await page.getByRole('status').filter({ hasText: 'Слот сохранён' }).waitFor()
      await page.getByRole('link', { name: 'Настройки сценария', exact: true }).click()
      await page.getByLabel('Рекламный сценарий включён').waitFor()
      await page.getByText('Защита со второй страницы', { exact: true }).first().waitFor()
      await page.screenshot({ path: path.join(output, `settings-${size.width}.png`), fullPage: true })
      await page.getByRole('button', { name: 'Слоты', exact: true }).click()
      await page.getByRole('button', { name: '#1 Оффер покупателя' }).click()
      await page.screenshot({ path: path.join(output, `slots-${size.width}.png`), fullPage: true })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      await page.getByRole('button', { name: 'Старая база', exact: true }).click()
      await page.getByRole('button', { name: 'Проверить аудиторию' }).click()
      assert.equal(await page.getByRole('button', { name: 'Запустить прогон' }).isDisabled(), true)
      await page.getByLabel('Подтверждение: ЗАПУСТИТЬ').fill('ЗАПУСТИТЬ')
      await page.getByRole('button', { name: 'Запустить прогон' }).click()
      await page.getByRole('status').filter({ hasText: 'Прогон поставлен' }).waitFor()
      await page.getByRole('link', { name: 'Статистика', exact: true }).click()
      await page.getByRole('button', { name: 'Рассчитать' }).click()
      await page.getByRole('heading', { name: 'Отправки по слотам' }).waitFor()
      await page.screenshot({ path: path.join(output, `tracking-${size.width}.png`), fullPage: true })
      let failed = true
      await page.route('**/api/v1/advertising/settings*', route => failed
        ? route.fulfill({ status: 500, json: { detail: 'Сервер недоступен' } }) : route.fallback())
      await page.goto('http://127.0.0.1:5177/settings/advertising')
      await page.getByRole('alert').waitFor()
      assert.equal(await page.getByText('Загрузка…', { exact: true }).count(), 0)
      failed = false
      await page.getByRole('button', { name: 'Повторить загрузку' }).click()
      await page.getByLabel('Рекламный сценарий включён').waitFor()
      assert.deepEqual(errors, [])
      await context.close()
    }
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require('playwright')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'report-admin', username: '报表测试', role: 'tenant_admin', tenant_id: 'test', permissions: [] }
const account = { id: 'local-account', account_id: 'act_meta_123', account_name: '测试账户', currency: 'USD', timezone: 'UTC', system_status: 'DISABLED' }

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  const errors = [], posts = [], queries = []
  let state = 'PENDING', outcome = 'success', reads = 0
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-report-token', url: baseURL }])
    await context.addInitScript(user => { localStorage.setItem('user', JSON.stringify(user)); localStorage.setItem('site-locale', 'zh') }, user)
    const page = await context.newPage()
    page.setDefaultTimeout(15000)
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname.replace('/api/v1', '')
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const respond = value => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) })
      if (path === '/auth/me') return respond(user)
      if (path === '/accounts' || path.endsWith('/accounts')) return respond([account])
      if (path === '/workbench/notifications') return respond({ alerts: 0, failed_jobs: 0, total: 0 })
      if (path === '/reports/breakdown') {
        reads++
        queries.push(Object.fromEntries(url.searchParams))
        const days = Math.round((Date.parse(url.searchParams.get('end_date')) - Date.parse(url.searchParams.get('start_date'))) / 86400000) + 1
        return respond({ items: [{ entity_id: 'local-account', meta_id: 'act_meta_123', entity_name: '测试账户', currency: 'USD', spend: 10, impressions: 100, clicks: 10, conversions: 1, conversion_rate: 10 }],
          data_quality: [{ status: 'INCOMPLETE', covered_days: 3, expected_days: days }] })
      }
      if (path === '/reports/account-overview') {
        reads++
        return respond({ items: [{ account_name: '测试账户', meta_account_id: 'act_meta_123', currency: 'USD', spend: 10, sync_status: outcome === 'success' ? 'FRESH' : 'FAILED', sync_error: outcome === 'success' ? null : 'Meta timeout', data_quality: { complete: outcome === 'success', covered_days: outcome === 'success' ? 3 : 0, expected_days: 3 } }], currency_totals: [] })
      }
      if (path === '/reports/sync') {
        posts.push(Object.fromEntries(url.searchParams))
        return respond({ task_ids: ['abc123'], account_count: 1 })
      }
      if (path === '/tasks/abc123') return respond({ state, result: state === 'SUCCESS' ? { status: outcome, error_count: outcome === 'success' ? 0 : 1 } : undefined })
      return respond([])
    })
    await page.goto(baseURL + '/dashboard/reports')
    await page.getByText('act_meta_123', { exact: true }).waitFor()
    assert.ok((await page.locator('.metric-note').allTextContents()).some(text => text.includes('已覆盖 3/30 天')))
    const selectPreset = async label => {
      await page.locator('.date-range-select').click()
      await page.getByRole('option', { name: label, exact: true }).click()
      await page.locator('.date-range-menu.el-popper:visible').waitFor({ state: 'hidden' })
      if (label === '自定义时间') await page.waitForFunction(() => {
        const panel = document.querySelector('.date-range-custom-popper')
        return panel && panel.getAttribute('aria-hidden') !== 'true' && getComputedStyle(panel).opacity === '1'
      })
    }
    assert.equal(await page.locator('.date-range-inputs input').count(), 0, 'custom inputs should be hidden initially')
    assert.equal(await page.locator('.date-range-shortcuts').count(), 0, 'presets should not crowd the toolbar')
    await selectPreset('自定义时间')
    await page.getByRole('dialog', { name: '自定义时间', exact: true }).waitFor()
    assert.equal(await page.locator('.date-range-inputs input').count(), 2)
    const draftReads = reads
    const start = page.getByPlaceholder('选择或输入开始日期'), end = page.getByPlaceholder('选择或输入结束日期')
    await start.fill('2026-09-10'); await start.press('Enter'); await start.blur()
    await end.fill('2026-09-12'); await end.press('Enter'); await end.blur()
    assert.equal(reads, draftReads, 'editing a custom draft must not refresh reports')
    await page.getByRole('button', { name: '应用时间', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('.metric-note') != null)
    await page.getByText('报表同步：日期未补全；已覆盖 3/3 天', { exact: true }).waitFor()
    assert.equal(queries.at(-1).start_date, '2026-09-10')
    assert.equal(queries.at(-1).end_date, '2026-09-12')
    const invalidReads = reads
    await selectPreset('自定义时间')
    await start.fill('2026-09-15'); await start.press('Enter'); await start.blur()
    await page.getByText('开始日期不能晚于结束日期', { exact: true }).waitFor()
    assert.ok(await page.getByRole('button', { name: '应用时间', exact: true }).isDisabled())
    assert.ok(await page.getByRole('button', { name: '同步所选日期', exact: true }).isDisabled())
    assert.equal(reads, invalidReads)
    assert.equal(posts.length, 0)
    await page.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(queries.at(-1).start_date, '2026-09-10', 'cancel keeps applied dates')
    assert.ok(await page.getByRole('button', { name: '同步所选日期', exact: true }).isEnabled())
    await selectPreset('近90天')
    await page.getByText('报表同步：日期未补全；已覆盖 3/90 天', { exact: true }).waitFor()
    const before = reads
    await page.getByRole('button', { name: '同步所选日期', exact: true }).click()
    await page.waitForTimeout(300)
    assert.equal(Math.round((Date.parse(posts.at(-1).end_date) - Date.parse(posts.at(-1).start_date)) / 86400000) + 1, 90)
    assert.equal(posts.at(-1).days, undefined)
    assert.equal(reads, before, 'must wait for task completion before refreshing reports')
    state = 'SUCCESS'
    await page.getByText('报表同步完成', { exact: true }).waitFor()
    assert.equal(reads, before + 1)
    outcome = 'failed'
    await page.getByRole('button', { name: '同步所选日期', exact: true }).click()
    await page.getByText('1 个账户同步失败，请查看同步错误后重试', { exact: true }).waitFor()
    await page.goto(baseURL + '/dashboard/account-overview')
    await page.getByRole('button', { name: '同步所选日期' }).click()
    await page.getByText('1 个账户同步失败，请查看同步错误后重试', { exact: true }).waitFor()
    assert.ok(posts.at(-1).start_date && posts.at(-1).end_date)
    await page.getByText('1 个账户的所选日期报表尚未完整同步，当前汇总可能不完整；显示 0 不代表实际消耗为 0。', { exact: true }).waitFor()
    assert.equal(posts.at(-1).days, undefined)
    await page.waitForTimeout(300)
    assert.ok(await page.getByText('1 个账户同步失败，请查看同步错误后重试', { exact: true }).isVisible(), 'refresh must preserve failure notice')
    assert.deepEqual(errors, [])
    fs.mkdirSync('test-results', { recursive: true })
    await page.screenshot({ path: 'test-results/report-sync-smoke.png', fullPage: true })
    await page.locator('.filters').screenshot({ path: 'test-results/date-range-toolbar.png' })
    await selectPreset('自定义时间')
    await start.click()
    const calendar = page.locator('.date-single-popper:visible')
    await calendar.waitFor()
    await calendar.getByRole('button', { name: '上个月' }).click()
    await calendar.locator('td.available').filter({ hasText: /^15$/ }).first().click()
    assert.ok(await page.getByRole('dialog', { name: '自定义时间', exact: true }).isVisible(), 'calendar selection must not dismiss the custom panel')
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await page.setViewportSize({ width: 390, height: 844 })
    await selectPreset('自定义时间')
    const panel = page.locator('.date-range-custom-popper:visible')
    const bounds = await panel.boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 391, 'custom panel must fit a narrow viewport')
    await panel.screenshot({ path: 'test-results/date-range-custom-mobile.png' })
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await page.setViewportSize({ width: 1440, height: 1000 })
    await selectPreset('自定义时间')
    await page.locator('.date-range-custom-popper:visible').screenshot({ path: 'test-results/date-range-custom.png' })
    console.log('PASS: compact preset dropdown, custom draft/apply/cancel, invalid range, nested calendar, mobile panel, 90-day sync and failure notice')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

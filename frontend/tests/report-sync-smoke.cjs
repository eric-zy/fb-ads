const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require('playwright')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'report-admin', username: '报表测试', role: 'tenant_admin', tenant_id: 'test', permissions: [] }
const account = { id: 'local-account', account_id: 'act_meta_123', account_name: '测试账户', currency: 'USD', timezone: 'UTC', system_status: 'DISABLED' }

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  const errors = [], posts = []
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
        return respond({ items: [{ entity_id: 'local-account', meta_id: 'act_meta_123', entity_name: '测试账户', currency: 'USD', spend: 10, impressions: 100, clicks: 10, conversions: 1, conversion_rate: 10 }],
          data_quality: [{ status: 'INCOMPLETE', covered_days: 3, expected_days: Number(url.searchParams.get('days')) }] })
      }
      if (path === '/reports/account-overview') {
        reads++
        return respond({ items: [{ account_name: '测试账户', meta_account_id: 'act_meta_123', currency: 'USD', spend: 10, sync_status: outcome === 'success' ? 'FRESH' : 'FAILED', sync_error: outcome === 'success' ? null : 'Meta timeout' }], currency_totals: [] })
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
    await page.locator('.filters .el-select').nth(1).click()
    await page.getByRole('option', { name: '近 90 天' }).click()
    await page.getByRole('button', { name: '同步最近 90 天' }).waitFor()
    const before = reads
    await page.getByRole('button', { name: '同步最近 90 天' }).click()
    await page.waitForTimeout(300)
    assert.equal(posts.at(-1).days, '90')
    assert.equal(reads, before, 'must wait for task completion before refreshing reports')
    state = 'SUCCESS'
    await page.getByText('报表同步完成', { exact: true }).waitFor()
    assert.equal(reads, before + 1)
    outcome = 'failed'
    await page.getByRole('button', { name: '同步最近 90 天' }).click()
    await page.getByText('1 个账户同步失败，请查看同步错误后重试', { exact: true }).waitFor()
    await page.goto(baseURL + '/dashboard/account-overview')
    await page.getByRole('button', { name: '同步所选日期' }).click()
    await page.getByText('1 个账户同步失败，请查看同步错误后重试', { exact: true }).waitFor()
    assert.ok(posts.at(-1).start_date && posts.at(-1).end_date)
    assert.equal(posts.at(-1).days, undefined)
    await page.waitForTimeout(300)
    assert.ok(await page.getByText('1 个账户同步失败，请查看同步错误后重试', { exact: true }).isVisible(), 'refresh must preserve failure notice')
    assert.deepEqual(errors, [])
    fs.mkdirSync('test-results', { recursive: true })
    await page.screenshot({ path: 'test-results/report-sync-smoke.png', fullPage: true })
    console.log('PASS: daily window coverage, Meta ID, 90-day sync, completion polling, failure notice and selected date range')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

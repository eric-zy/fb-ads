const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'comparison-admin', role: 'tenant_admin', tenant_id: 'test', permissions: [] }
const account = { id: 'comparison-account', account_id: 'act_comparison', account_name: '环比测试账户', currency: 'USD', timezone: 'UTC' }

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  const errors = []
  let scenario = 'slow', releasePrevious, previousHeld
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-comparison-token', url: baseURL }])
    await context.addInitScript(user => { localStorage.setItem('user', JSON.stringify(user)); localStorage.setItem('site-locale', 'zh') }, user)
    const page = await context.newPage()
    page.setDefaultTimeout(12000)
    page.on('pageerror', error => errors.push(error.message))
    const today = new Date().toISOString().slice(0, 10)
    await page.route('**/*', async route => {
      const url = new URL(route.request().url()), path = url.pathname.replace('/api/v1', '')
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
      if (path === '/auth/me') return respond(user)
      if (path === '/accounts') return respond([account])
      if (path.endsWith('/accounts')) return respond({ accounts: [account] })
      if (path === '/workbench/notifications') return respond({ total: 0 })
      if (path !== '/reports/breakdown') return respond([])
      const selectedScenario = scenario
      const isCurrent = url.searchParams.get('end_date') === today
      const days = Math.round((Date.parse(url.searchParams.get('end_date')) - Date.parse(url.searchParams.get('start_date'))) / 86400000) + 1
      if (!isCurrent && ['slow', 'race'].includes(selectedScenario) && days === 30) {
        previousHeld = true
        await new Promise(resolve => { releasePrevious = resolve })
      }
      if (!isCurrent && selectedScenario === 'failed') return respond({ detail: 'prior unavailable' }, 503)
      const partial = (isCurrent && selectedScenario === 'current-partial') || (!isCurrent && selectedScenario === 'prior-partial')
      const item = { entity_id: account.id, entity_name: account.account_name, meta_id: account.account_id,
        currency: !isCurrent && selectedScenario === 'currency' ? 'EUR' : 'USD',
        spend: isCurrent ? (days === 7 ? 700 : 300) : (days === 7 ? 350 : 100),
        conversions: isCurrent ? 3 : 1, clicks: 10, impressions: 100 }
      if (!isCurrent && selectedScenario === 'null') item.spend = null
      if (!isCurrent && selectedScenario === 'zero') item.spend = 0
      const data = { items: !isCurrent && selectedScenario === 'empty' ? [] : [item],
        data_quality: [{ account_id: account.id, status: partial ? 'INCOMPLETE' : 'FRESH',
          covered_days: partial ? 1 : days, expected_days: days, complete: !partial }] }
      // Superseded requests are deliberately aborted by the component.
      try { await respond(data) } catch (error) {
        if (!/Target closed|closed|disposed|Invalid InterceptionId|already handled/i.test(error.message)) throw error
      }
    })
    const row = page.locator('.el-table__body tbody tr').first()
    const spendComparison = () => row.locator('td').nth(3)
    const reload = async value => {
      scenario = value; previousHeld = false
      await page.goto(baseURL + '/dashboard/reports')
      await page.getByText('act_comparison', { exact: true }).waitFor()
    }
    await reload('slow')
    assert(previousHeld)
    await page.getByText('正在加载上一周期，当前周期数据可先查看', { exact: true }).waitFor()
    assert.equal(await row.locator('td').nth(2).innerText(), '300')
    assert.equal(await spendComparison().innerText(), '—')
    await page.locator('.el-loading-mask:visible').waitFor({ state: 'hidden' })
    releasePrevious()
    await spendComparison().getByText('+200.0%', { exact: true }).waitFor()
    for (const value of ['prior-partial', 'current-partial']) {
      await reload(value)
      await page.getByText(`${value === 'prior-partial' ? '上一' : '当前'}周期同步记录未完整覆盖，暂不计算环比`, { exact: true }).waitFor()
      assert.equal(await spendComparison().innerText(), '—')
    }
    await reload('failed')
    await page.getByText('上一周期数据暂不可用，当前周期数据仍可查看', { exact: true }).waitFor()
    assert.equal(await row.locator('td').nth(2).innerText(), '300')
    assert.equal(await spendComparison().innerText(), '—')
    for (const value of ['empty', 'zero']) {
      await reload(value)
      await spendComparison().getByText('新增', { exact: true }).waitFor()
    }
    for (const value of ['null', 'currency']) {
      await reload(value)
      await page.getByText('正在加载上一周期，当前周期数据可先查看', { exact: true }).waitFor({ state: 'hidden' })
      assert.equal(await spendComparison().innerText(), '—')
    }
    await reload('race')
    assert(previousHeld)
    const releaseOld = releasePrevious
    await page.locator('.date-range-select').click()
    await page.getByRole('option', { name: '近7天', exact: true }).click()
    await spendComparison().getByText('+100.0%', { exact: true }).waitFor()
    releaseOld()
    await page.waitForTimeout(150)
    assert.equal(await row.locator('td').nth(2).innerText(), '700')
    assert.equal(await spendComparison().innerText(), '+100.0%')
    assert.deepEqual(errors, [])
    console.log('PASS comparison: slow/failed prior, partial coverage, zero/empty/null, currency mismatch and superseded requests')
  } finally { releasePrevious?.(); await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

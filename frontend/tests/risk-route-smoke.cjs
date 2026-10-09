const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'risk-route-admin', role: 'tenant_admin', tenant_id: 'test', permissions: [] }
const account = { id: 'risk-route-account', account_id: 'act_route', account_name: '路由测试账户', currency: 'USD' }

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  const errors = [], calls = []
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-risk-token', url: baseURL }])
    await context.addInitScript(user => { localStorage.setItem('user', JSON.stringify(user)); localStorage.setItem('site-locale', 'zh') }, user)
    const page = await context.newPage()
    page.setDefaultTimeout(12000)
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url()), path = url.pathname.replace('/api/v1', '')
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      calls.push(path)
      let data = []
      if (path === '/auth/me') data = user
      if (path.endsWith('/accounts') && path !== '/accounts') data = { accounts: [account] }
      if (path === '/workbench/notifications') data = { total: 0 }
      if (path === '/risk-control/overview') data = { scope: { account_count: 0 }, account_status: {}, unresolved_events: 0, today_paused: 0 }
      if (path === '/risk-control/automation') data = { kill_switch: false }
      if (path === '/risk-control/events' || path === '/risk-control/executions') data = { items: [], total: 0 }
      if (path === '/risk-control/rules') data = { items: [] }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    })
    await page.goto(baseURL + '/app/risk/rules?source=bookmark')
    await page.getByRole('tab', { name: '风控规则', exact: true }).waitFor()
    await page.locator('.head-actions .account-name').getByText('路由测试账户', { exact: true }).waitFor()
    assert.equal(await page.getByRole('tab', { name: '风控规则', exact: true }).getAttribute('aria-selected'), 'true')
    assert(new URL(page.url()).searchParams.get('source') === 'bookmark')
    // Use the application's router to exercise reuse and KeepAlive without a document reload.
    const navigate = path => page.evaluate(path => document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(path), path)
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/risk-control/executions')),
      navigate('/app/risk/stops'),
    ])
    await page.waitForFunction(() => document.querySelector('[role=tab][aria-selected=true]')?.textContent?.includes('止损记录'))
    assert(calls.includes('/risk-control/executions'))
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/risk-control/rules')),
      page.getByRole('tab', { name: '风控规则', exact: true }).click(),
    ])
    await navigate('/dashboard/risk-control?tab=events')
    await page.waitForFunction(() => document.querySelector('[role=tab][aria-selected=true]')?.textContent?.includes('风险事件'))
    await page.clock.install()
    await navigate('/dashboard/reports')
    await page.getByText('请选择广告账户', { exact: true }).waitFor()
    const before = calls.filter(path => path === '/risk-control/overview').length
    await page.clock.fastForward(60000)
    assert.equal(calls.filter(path => path === '/risk-control/overview').length, before, 'deactivated risk page stops polling')
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/risk-control/overview')),
      navigate('/app/risk/rules'),
    ])
    await page.waitForFunction(() => document.querySelector('[role=tab][aria-selected=true]')?.textContent?.includes('风控规则'))
    assert(calls.filter(path => path === '/risk-control/overview').length > before, 'cached reentry refreshes data')
    await navigate('/dashboard/risk-control?tab=invalid')
    await page.waitForFunction(() => document.querySelector('[role=tab][aria-selected=true]')?.textContent?.includes('风险事件'))
    assert.deepEqual(errors, [])
    console.log('PASS risk navigation: legacy entry, query/manual tab changes, cached reentry and polling cleanup')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

const assert = require('node:assert/strict')
const { chromium } = require('playwright')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'assigned-user', username: 'test002', role: 'user', tenant_id: 'test', permissions: ['job:create'], settings: {} }

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-page-test', url: baseURL }])
    await context.addInitScript(data => { localStorage.setItem('user', JSON.stringify(data)); localStorage.setItem('site-locale', 'zh') }, user)
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    let pageListFails = true
    const calls = []
    await page.route('**/*', route => {
      const url = new URL(route.request().url())
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const path = url.pathname.replace('/api/v1', '')
      calls.push(path)
      const respond = (data, status = 200, headers = {}) => route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(data) })
      if (path === '/auth/me') return respond(user)
      if (path === '/meta-pages') return pageListFails ? respond({ detail: '模拟列表读取失败' }, 503) : respond([])
      if (path.includes('/notifications')) return respond({ items: [], total: 0 })
      if (path === '/sinan/status') return respond({ verified: false })
      if (path === '/accounts/available-for-deployment') return respond({ total: 0, accounts: [] })
      if (path.endsWith('/accounts') && path.startsWith('/users/')) return respond({ accounts: [] })
      if (path === '/accounts') return respond([{ id: 'assigned-account', account_id: 'act_1', account_name: '分配账户', system_status: 'ACTIVE', is_deployable: false }], 200, { 'x-total-count': '4' })
      if (path === '/meta-auth/mode') return respond({ access_mode: 'connector' })
      return respond([])
    })
    await page.goto(`${baseURL}/dashboard/batch-publish`)
    await page.locator('.el-form-item').filter({ hasText: /^投放方式/ }).locator('.el-select').click()
    await page.getByRole('option', { name: '直接配置投放', exact: true }).click()
    await page.getByText('Facebook Page 列表加载失败，请重新加载。', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: '同步 Facebook 页面', exact: true }).count(), 0)
    pageListFails = false
    await page.getByRole('button', { name: '重新加载', exact: true }).click()
    await page.getByText(/请管理员为已分配账户指定委派执行授权并同步 Page/).waitFor()
    assert.equal(await page.getByRole('button', { name: '重新加载', exact: true }).count(), 0)
    await page.getByRole('button', { name: '我的 Meta 授权', exact: true }).click()
    await page.waitForURL('**/dashboard/meta-connections')
    await page.getByText('暂无 Meta 授权，请先完成 OAuth', { exact: true }).waitFor()
    await page.goto(`${baseURL}/dashboard/accounts`)
    const statistic = page.locator('.el-card').filter({ has: page.getByText('当前用户可访问的广告账户', { exact: true }) })
    await statistic.locator('.stat-value').filter({ hasText: /^4$/ }).waitFor()
    assert.equal(await statistic.getByText('授权账号', { exact: true }).count(), 0)
    assert(!calls.includes('/meta-pages/sync-all'))
    assert.deepEqual(errors, [])
    console.log('PASS: Page request failure, empty authorization guidance, self-authorization navigation, assigned account count')
  } finally {
    await browser.close()
  }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const fs = require('node:fs')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const admin = { id: 'nav-admin', username: '测试管理员', role: 'tenant_admin', tenant_id: 'tenant-one', permissions: [], settings: {} }
const publisher = { id: 'nav-publisher', username: '测试投手', role: 'user', tenant_id: 'tenant-one', permissions: [], settings: {} }
const account = { id: 'nav-account', account_id: 'act_123', account_name: '分配测试账户', system_status: 'ACTIVE', account_status: '1', risk_score: 0, currency: 'USD' }
const assignments = [
  { user_id: admin.id, username: admin.username, assignment_status: 'ACTIVE', is_primary: true },
  { user_id: publisher.id, username: publisher.username, assignment_status: 'ACTIVE', is_primary: false },
]
const calls = []
const errors = []
let failPending = true
let lastPage

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    async function createPage(user) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
      await context.addCookies([{ name: 'auth_token', value: 'isolated-navigation-token', url: baseURL }])
      await context.addInitScript(data => {
        localStorage.setItem('user', JSON.stringify(data))
        localStorage.setItem('site-locale', 'zh')
      }, user)
      const page = await context.newPage()
      lastPage = page
      page.setDefaultTimeout(10000)
      page.on('pageerror', error => errors.push(error.message))
      page.on('dialog', dialog => dialog.dismiss())
      await page.route('**/*', async route => {
        const req = route.request()
        const url = new URL(req.url())
        if (url.origin !== baseURL) return route.abort()
        if (!url.pathname.startsWith('/api/')) return route.continue()
        const path = url.pathname.replace('/api/v1', '')
        const method = req.method()
        const body = req.postData() ? req.postDataJSON() : null
        calls.push({ path, method, body })
        const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
        if (path === '/auth/me') return respond(user)
        if (path === '/accounts') return respond([account])
        if (path === '/meta-accounts/pending-ad-accounts') {
          if (failPending) return respond({ detail: '模拟扫描失败' }, 500)
          return respond({ accounts: [{ id: 'act_999', name: '待导入测试账户', meta_account_id: 'pending-bm', business_name: '测试 BM' }], errors: [{ business_name: '失效 BM', error: '授权已失效' }] })
        }
        if (path === `/users/${user.id}/accounts`) return respond({ accounts: [account] })
        if (path === '/users') return respond([
          { ...admin, is_active: true, last_login: '2026-10-07T01:02:03.654321', created_at: '2026-09-01T03:04:05.123456' },
          { ...publisher, is_active: true, last_login: null, created_at: '2026-09-01T03:04:05.123456' },
        ])
        if (path === `/accounts/${account.id}/users`) return respond(assignments)
        if (path.endsWith('/operation-lease')) return respond({ lease: { lease_token: 'mock-assignment-lease' } })
        if (path === '/sinan/status') return respond({ verified: false })
        if (path.includes('notifications')) return respond({ total: 0, items: [] })
        if (path === '/workbench/summary') return respond({
          scope: { role: user.role, account_count: 1, accounts: [] },
          range: { start_date: '2026-10-01', end_date: '2026-10-07' },
          freshness: { status: 'FRESH', account_count: 1, stale_account_count: 0, never_synced_account_count: 0 },
          kpis: { active_campaigns: 0, total_campaigns: 0, average_ctr: 0, pending_jobs: 0, failed_jobs: 0, open_alerts: 0, status_drift: 0, highest_risk_score: 0 },
          delivery_health: { status_counts: {}, status_drift: 0 },
          job_status: {}, currency_totals: [], trend: [], recent_tasks: [], alerts: [],
        })
        return respond([])
      })
      return page
    }

    const page = await createPage(admin)
    await page.goto(`${baseURL}/admin`)
    await page.waitForURL('**/admin/dashboard')
    await page.getByRole('button', { name: '分配广告账户给投手', exact: true }).click()
    await page.waitForURL('**/admin/accounts')
    assert.equal(await page.getByRole('button', { name: '分配给投手', exact: true }).count(), 0)
    await page.locator('.el-table__body tr').first().locator('.el-checkbox').click()
    await page.getByRole('button', { name: '批量添加协作者', exact: true }).waitFor()
    await page.getByRole('button', { name: '已分配用户', exact: true }).click()
    await page.getByRole('dialog').getByText(publisher.username, { exact: true }).waitFor()
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click()
    console.log('PASS assignment navigation: unified bulk entry and assigned-user information are discoverable')

    await page.getByText('待导入', { exact: true }).click()
    await page.waitForFunction(() => !document.querySelector('.el-loading-mask'))
    assert.equal(await page.getByText(account.account_name, { exact: true }).count(), 0)
    failPending = false
    await page.getByRole('button', { name: '刷新', exact: true }).click()
    await page.getByText('待导入测试账户', { exact: true }).waitFor()
    await page.getByText('部分 BM 扫描失败，当前待导入列表不完整', { exact: true }).waitFor()
    await page.getByText('失效 BM：授权已失效', { exact: true }).waitFor()
    await page.goto(`${baseURL}/admin/users`)
    await page.getByText('暂无登录记录', { exact: true }).waitFor()
    const adminRow = page.locator('.el-table__body tr').filter({ hasText: admin.username })
    assert.match(await adminRow.innerText(), /2026-10-07 \d{2}:\d{2}:03/)
    assert.doesNotMatch(await adminRow.innerText(), /654321|123456|T01:02/)
    console.log('PASS admin data: failed scan clears stale accounts, partial scan shows warning; login and creation dates stop at seconds')

    await page.goto(`${baseURL}/admin/accounts?business_id=original-bm`)
    await page.getByRole('menuitem', { name: '返回用户端', exact: true }).click()
    await page.waitForURL('**/dashboard/overview')
    await page.getByText('2026-10-01 至 2026-10-07', { exact: true }).first().waitFor()
    await page.locator('.el-message').waitFor({ state: 'hidden' })
    fs.mkdirSync('test-results', { recursive: true })
    await page.locator('.header').screenshot({ path: 'test-results/admin-return-header.png' })
    await page.reload()
    await page.getByRole('button', { name: '返回管理后台', exact: true }).click()
    await page.waitForURL('**/admin/accounts?business_id=original-bm')
    assert.equal(await page.locator('.el-menu-item.is-active').innerText(), '广告账户分配')
    await page.getByRole('menuitem', { name: '返回用户端', exact: true }).click()
    await page.setViewportSize({ width: 1000, height: 1000 })
    await page.getByRole('menuitem', { name: '返回管理后台', exact: true }).click()
    await page.waitForURL('**/admin/accounts?business_id=original-bm')
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.goto(`${baseURL}/dashboard/jobs`)
    await page.getByRole('menuitem', { name: '账号中心', exact: true }).click()
    await page.getByRole('menuitem', { name: '广告账户分配', exact: true }).click()
    await page.waitForURL('**/admin/accounts')
    assert.equal(calls.filter(call => call.path === '/auth/logout' || call.path === '/auth/login').length, 0)
    console.log('PASS navigation: header/sidebar return preserves previous admin path and filters across reload; direct assignment shortcut needs no login')

    await page.evaluate(() => sessionStorage.setItem('admin-return:nav-admin:tenant-one', '/admin/missing'))
    await page.goto(`${baseURL}/dashboard/jobs`)
    await page.getByRole('button', { name: '返回管理后台', exact: true }).click()
    await page.waitForURL('**/admin/dashboard')
    await page.evaluate(() => {
      sessionStorage.removeItem('admin-return:nav-admin:tenant-one')
      sessionStorage.setItem('admin-return:other-user:tenant-one', '/admin/users')
      sessionStorage.setItem('admin-return:nav-admin:other-tenant', '/admin/users')
    })
    await page.goto(`${baseURL}/dashboard/jobs`)
    await page.getByRole('button', { name: '返回管理后台', exact: true }).click()
    await page.waitForURL('**/admin/dashboard')
    console.log('PASS return history: invalid path falls back; another user or tenant history is ignored')

    const userPage = await createPage(publisher)
    await userPage.goto(`${baseURL}/dashboard`)
    await userPage.waitForURL('**/dashboard/overview')
    assert.equal(await userPage.getByText('返回管理后台', { exact: true }).count(), 0)
    assert.equal(await userPage.getByText('广告账户分配', { exact: true }).count(), 0)
    await userPage.goto(`${baseURL}/admin/accounts`)
    await userPage.waitForURL('**/dashboard/overview')
    assert.equal(await userPage.getByRole('button', { name: '分配给投手', exact: true }).count(), 0)
    for (const role of ['admin', 'platform_admin']) {
      const rolePage = await createPage({ ...admin, role, id: `nav-${role}` })
      await rolePage.goto(`${baseURL}/dashboard/jobs`)
      await rolePage.getByRole('button', { name: '返回管理后台', exact: true }).click()
      await rolePage.waitForURL('**/admin/dashboard')
    }
    assert.deepEqual(errors, [])
    console.log('PASS access: ordinary users have no admin shortcuts and cannot enter admin routes; no runtime errors')
  } catch (error) {
    fs.mkdirSync('test-results', { recursive: true })
    if (lastPage) await lastPage.screenshot({ path: 'test-results/admin-navigation-failure.png', fullPage: true })
    throw error
  } finally { await browser.close() }
}

main().catch(error => { console.error(error); process.exitCode = 1 })

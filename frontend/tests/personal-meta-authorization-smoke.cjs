const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const fs = require('node:fs')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const publisher = { id: 'personal-a', username: '投手 A', role: 'user', tenant_id: 'test', permissions: [], settings: {} }
const admin = { ...publisher, id: 'personal-admin', username: '管理员', role: 'tenant_admin' }
const calls = []
const errors = []
const connection = { id: 'connection-a', tenant_id: 'test', meta_user_id: 'meta-a', app_id: 'meta-app', status: 'ACTIVE', health: 'EXPIRING', scopes: ['ads_read', 'ads_management'], authorized_by_username: '投手 A', is_owner: true, version: 2, account_names: ['已分配账户'], executable_account_ids: ['account-a'], account_count: 1, business_count: 1, page_count: 1, credential_count: 1, expires_at: '2026-10-14T01:02:03.123456', data_access_expires_at: '2026-10-12T01:02:03.456789' }

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    async function createPage(user) {
      const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
      await context.addCookies([{ name: 'auth_token', value: 'isolated-personal-oauth-test', url: baseURL }])
      await context.addInitScript(data => { localStorage.setItem('user', JSON.stringify(data)); localStorage.setItem('site-locale', 'zh') }, user)
      const page = await context.newPage()
      page.setDefaultTimeout(10000)
      page.on('pageerror', error => errors.push(error.message))
      await page.route('**/*', route => {
        const req = route.request()
        const url = new URL(req.url())
        if (url.origin !== baseURL) return route.abort()
        if (!url.pathname.startsWith('/api/')) return route.continue()
        const path = url.pathname.replace('/api/v1', '')
        const method = req.method()
        const body = req.postData() ? req.postDataJSON() : null
        calls.push({ path, method, body, scope: url.searchParams.get('scope') })
        const respond = data => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
        if (path === '/auth/me') return respond(user)
        if (path.startsWith('/users/') && path.endsWith('/accounts')) return respond({ accounts: [] })
        if (path === '/sinan/status') return respond({ verified: false })
        if (path.includes('/notifications')) return respond({ items: [], total: 0 })
        if (path === '/meta-auth/mode') return respond({ access_mode: 'connector' })
        if (path === '/meta-connections') {
          if (url.searchParams.get('scope') === 'tenant') return respond([
            { ...connection, is_owner: false },
            { ...connection, id: 'connection-admin', meta_user_id: 'meta-admin', authorized_by_username: '管理员', is_owner: true },
            { ...connection, id: 'legacy-unknown', meta_user_id: '历史授权', status: 'OWNER_UNKNOWN', health: 'OWNER_UNKNOWN', is_owner: false },
          ])
          return respond([connection])
        }
        if (path.endsWith('/execution-default') || path.endsWith('/reporting-default')) return respond({ success: true })
        if (path.endsWith('/disconnect')) { connection.status = connection.health = 'REVOKED'; return respond({ success: true, cancelled_jobs: 2 }) }
        if (path.endsWith('/sync')) return respond({ status: 'QUEUED', task_ids: ['mock-sync'] })
        if (path === '/meta-auth/authorize-first') return respond({ authorization_url: `${baseURL}/dashboard/accounts?meta_auth=businesses&credential_id=opaque-returned&state=bound-intent&receipt=signed-result` })
        if (path === '/meta-auth/claim') { assert.deepEqual(body, { state: 'bound-intent', receipt: 'signed-result' }); return respond({ credential_id: 'owned-opaque', connection_id: 'connection-new' }) }
        if (path === '/meta-auth/ad-accounts') { assert.equal(url.searchParams.get('credential_id'), 'owned-opaque'); return respond({ accounts: [{ id: 'act_new', name: '新接入测试账户', business: { id: 'bm_new', name: '测试 BM' } }] }) }
        if (path === '/meta-auth/complete-accounts') return respond({ success: true, accounts: [{ id: 'account-new', account_id: 'act_new', assignment_required: false }], page_sync: { status: 'SUCCESS', count: 1 } })
        if (path === '/accounts') return respond([{ id: 'account-new', account_id: 'act_new', account_name: '新接入测试账户', system_status: 'ACTIVE', account_status: '1', is_deployable: true }])
        return respond([])
      })
      return page
    }
    const page = await createPage(publisher)
    await page.goto(`${baseURL}/dashboard/meta-connections`)
    await page.getByRole('heading', { name: '我的 Meta 授权', exact: true }).waitFor()
    await page.getByText('7 天内到期', { exact: true }).waitFor()
    assert.equal(calls.find(call => call.path === '/meta-connections').scope, 'mine')
    assert.equal(await page.getByText('123456', { exact: false }).count(), 0)
    await page.getByRole('button', { name: '执行授权', exact: true }).click()
    await page.getByRole('button', { name: '确定', exact: true }).click()
    await page.getByText('执行授权已设置', { exact: true }).waitFor()
    await page.getByRole('dialog', { name: '选择执行授权', exact: true }).waitFor({ state: 'hidden' })
    assert.deepEqual(calls.find(call => call.path.endsWith('/execution-default')).body, { account_ids: ['account-a'] })
    fs.mkdirSync('test-results', { recursive: true })
    await page.screenshot({ path: 'test-results/personal-meta-authorizations.png', fullPage: true })
    await page.getByRole('button', { name: '解除授权', exact: true }).click()
    await page.getByRole('button', { name: '确定', exact: true }).click()
    await page.getByText('授权已解除，取消 2 个待执行任务', { exact: true }).waitFor()
    await page.getByRole('button', { name: '接入我的 Meta 个号' }).click()
    await page.locator('.business-option').filter({ hasText: '新接入测试账户' }).locator('.el-checkbox').click()
    await page.getByRole('button', { name: '确认接入并同步' }).click()
    await page.getByRole('heading', { name: 'Meta 授权成功', exact: true }).waitFor()
    assert.ok(calls.findIndex(call => call.path === '/meta-auth/claim') < calls.findIndex(call => call.path === '/meta-auth/ad-accounts'))
    assert.deepEqual(calls.find(call => call.path === '/meta-auth/complete-accounts').body, { credential_id: 'owned-opaque', account_ids: ['act_new'] })
    assert.ok(!page.url().includes('receipt='))
    connection.status = 'ACTIVE'
    connection.health = 'EXPIRING'
    const adminPage = await createPage(admin)
    await adminPage.goto(`${baseURL}/admin/meta-connections`)
    await adminPage.getByRole('heading', { name: 'Meta 个人授权管理', exact: true }).waitFor()
    const others = adminPage.locator('.el-table__body tr').filter({ has: adminPage.getByText('meta-a', { exact: true }) })
    assert.equal(await others.getByRole('button', { name: '重新授权', exact: true }).count(), 0)
    await adminPage.getByText('请原投手重新接入确认归属', { exact: true }).waitFor()
    await others.locator('.el-table__expand-icon').click()
    await adminPage.getByRole('button', { name: '设为系统同步授权', exact: true }).click()
    await adminPage.getByRole('dialog', { name: '指定系统同步授权', exact: true }).waitFor()
    await adminPage.getByRole('button', { name: '确定', exact: true }).click()
    await adminPage.getByText('系统同步授权已指定', { exact: true }).waitFor()
    assert.deepEqual(calls.find(call => call.path === '/meta-connections/connection-a/reporting-default').body, { account_ids: ['account-a'] })
    assert.deepEqual(errors, [])
    console.log('personal-meta-authorization-smoke: PASS')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

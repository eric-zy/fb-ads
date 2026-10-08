const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const fs = require('node:fs')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const admin = { id: 'admin', username: '管理员', role: 'tenant_admin', tenant_id: 'test', permissions: [], settings: {} }
const publisher = { ...admin, id: 'publisher', username: '委派投手', role: 'user', permissions: ['job:create'] }
const account = { id: 'account', account_id: 'act_1', account_name: '委派测试账户', system_status: 'ACTIVE', account_status: '1', is_deployable: true, execution_source: 'DELEGATED', authorized_by_username: '授权管理员' }
const connection = { id: 'connection', meta_user_id: 'fb-owner', app_id: 'app', status: 'ACTIVE', health: 'ACTIVE', account_count: 1, page_count: 1, business_count: 0, account_names: [account.account_name], authorized_by_username: '授权管理员', execution_source: 'DELEGATED', can_manage: false, is_owner: false }
const calls = []
const errors = []
let revoked = false

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    async function createPage(user) {
      const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } })
      await context.addCookies([{ name: 'auth_token', value: 'isolated-delegation-test', url: baseURL }])
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
        const body = req.postData() ? req.postDataJSON() : null
        calls.push({ path, method: req.method(), body, query: url.searchParams.toString() })
        const respond = data => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
        if (path === '/auth/me') return respond(user)
        if (path === '/users') return respond([{ ...publisher, is_active: true }])
        if (path === `/accounts/${account.id}/users`) return respond([{ user_id: publisher.id, username: publisher.username, assignment_status: 'ACTIVE', is_primary: true }])
        if (path.endsWith('/execution-authorizations')) return respond({ items: [{ connection_id: connection.id, meta_user_id: connection.meta_user_id, authorized_by_username: connection.authorized_by_username, page_count: 1 }] })
        if (path.endsWith('/operation-lease')) return respond({ lease: { lease_token: 'isolated-lease' } })
        if (path.endsWith('/assign')) return respond({ success: true })
        if (path === '/accounts') return respond([account])
        if (path === '/accounts/available-for-deployment') return respond({ accounts: [account], total: 1 })
        if (path.startsWith('/users/') && path.endsWith('/accounts')) return respond({ accounts: [account] })
        if (path === '/meta-connections') return respond(url.searchParams.get('scope') === 'delegated' ? [connection] : [])
        if (path === '/meta-pages') return respond(revoked ? [] : [{ id: 'page', page_id: '101', page_name: '委派可用 Page', status: 'ACTIVE', tasks: ['ADVERTISE'] }])
        if (path === '/campaign-templates' || path === '/templates') return respond([{ id: 'template', name: '委派测试模板', objective: 'OUTCOME_TRAFFIC', daily_budget: 10, adsets: [], creative_config_json: { page_id: '101' } }])
        if (path === '/meta-auth/mode') return respond({ access_mode: 'connector' })
        if (path === '/sinan/status') return respond({ verified: false })
        if (path.includes('notifications')) return respond({ items: [], total: 0 })
        return respond([])
      })
      return page
    }
    const adminPage = await createPage(admin)
    await adminPage.goto(`${baseURL}/admin/accounts`)
    const open = async () => {
      await adminPage.getByRole('button', { name: '分配给投手', exact: true }).click()
      const dialog = adminPage.getByRole('dialog', { name: `分配给投手 - ${account.account_name}` })
      await dialog.locator('.el-form-item').filter({ hasText: /^执行方式/ }).locator('.el-select').click()
      return dialog
    }
    let dialog = await open()
    await adminPage.getByRole('option', { name: '管理员委派授权', exact: true }).click()
    await dialog.locator('.el-form-item').filter({ hasText: /^执行 Meta 授权/ }).locator('.el-select').click()
    await adminPage.getByRole('option', { name: /授权管理员 · Meta fb-owner/ }).click()
    await adminPage.keyboard.press('Escape')
    fs.mkdirSync('test-results', { recursive: true })
    await dialog.screenshot({ path: 'test-results/admin-delegated-execution.png' })
    await dialog.getByRole('button', { name: '保存分配', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    assert.equal(calls.filter(x => x.path.endsWith('/assign')).at(-1).body.execution_connection_id, connection.id)
    dialog = await open()
    await adminPage.getByRole('option', { name: '本人 Meta 授权', exact: true }).click()
    await dialog.getByRole('button', { name: '保存分配', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    assert.equal(calls.filter(x => x.path.endsWith('/assign')).at(-1).body.execution_connection_id, null)

    const page = await createPage(publisher)
    await page.goto(`${baseURL}/dashboard/meta-connections`)
    await page.getByText('暂无 Meta 授权，请先完成 OAuth', { exact: true }).waitFor()
    await page.getByText('管理员委派给我', { exact: true }).click()
    await page.getByText('fb-owner', { exact: true }).waitFor()
    await page.getByText('授权管理员', { exact: true }).waitFor()
    assert.equal(await page.getByRole('radio', { name: '管理员委派给我', exact: true }).isChecked(), true)
    for (const name of ['同步资产', '解除授权', '重新授权', '执行授权']) assert.equal(await page.getByRole('button', { name, exact: true }).count(), 0)
    await page.screenshot({ path: 'test-results/publisher-delegated-execution.png', fullPage: true })
    await page.goto(`${baseURL}/dashboard/accounts`)
    await page.getByText('管理员委派 · 授权人：授权管理员', { exact: true }).waitFor()
    await page.goto(`${baseURL}/dashboard/batch-publish`)
    await page.locator('.el-form-item').filter({ hasText: /^投放模板/ }).locator('.el-select').click()
    await page.getByRole('option', { name: /委派测试模板/ }).click()
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.getByRole('heading', { name: '广告账户与本次投放参数', exact: true }).waitFor()
    await page.locator('.el-form-item').filter({ hasText: /^广告账户/ }).locator('.el-select').click()
    await page.getByRole('option', { name: /委派测试账户/ }).click()
    await page.keyboard.press('Escape')
    await page.waitForFunction(() => !document.querySelector('.el-loading-mask'))
    assert(calls.some(x => x.path === '/meta-pages' && new URLSearchParams(x.query).get('account_ids') === account.id))
    await page.getByRole('button', { name: '上一步', exact: true }).click()
    await page.getByRole('button', { name: '上一步', exact: true }).click()
    await page.locator('.el-form-item').filter({ hasText: /^投放方式/ }).locator('.el-select').click()
    await page.getByRole('option', { name: '直接配置投放', exact: true }).click()
    const pages = page.locator('.el-form-item').filter({ hasText: /^Facebook Page/ }).locator('.el-select')
    await pages.click()
    await page.getByRole('option', { name: /委派可用 Page/ }).waitFor()
    revoked = true
    await page.reload()
    await page.locator('.el-form-item').filter({ hasText: /^投放方式/ }).locator('.el-select').click()
    await page.getByRole('option', { name: '直接配置投放', exact: true }).click()
    await page.getByText(/请管理员为已分配账户指定委派执行授权并同步 Page/).waitFor()
    assert.equal(calls.filter(x => /disconnect|sync-all|authorize-first/.test(x.path)).length, 0)
    assert.deepEqual(errors, [])
    console.log('PASS: admin delegates and revokes explicitly; publisher sees delegation without OAuth management; Page follows selected accounts')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

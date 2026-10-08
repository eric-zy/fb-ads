const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'oauth-tester', username: '授权测试投手', role: 'user', tenant_id: 'test', permissions: [], settings: {} }
const callback = '/dashboard/accounts?meta_auth=businesses&credential_id=unclaimed&state=test-intent&receipt=test-receipt'
const errors = []
async function main() {
  const exported = {}
  vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/utils/authRedirect.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: exported, URL })
  assert.equal(exported.safeAuthRedirect(callback), callback)
  assert.equal(exported.safeAuthRedirect('/admin/accounts?tab=all#list'), '/admin/accounts?tab=all#list')
  for (const input of ['https://other.invalid', '//other.invalid', '/\\other.invalid', '/dashboard/../../login', '/login', '/dashboard\n', ['/dashboard'], null]) assert.equal(exported.safeAuthRedirect(input), null)
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    async function scenario(options = {}) {
      const context = await browser.newContext({ viewport: { width: 1500, height: 1000 } })
      if (options.authenticated !== false) await context.addCookies([{ name: 'auth_token', value: 'isolated-oauth-test', url: baseURL }])
      await context.addInitScript(data => { localStorage.setItem('user', JSON.stringify(data)); localStorage.setItem('site-locale', 'zh') }, user)
      const page = await context.newPage()
      page.setDefaultTimeout(10000)
      page.on('pageerror', error => errors.push(error.message))
      const calls = []
      let claims = 0, discoveries = 0, imported = false, releaseList, waitingList = false
      const delayedList = new Promise(resolve => { releaseList = resolve })
      await context.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url())
        if (url.origin !== baseURL) return route.abort()
        if (!url.pathname.startsWith('/api/')) return route.continue()
        const path = url.pathname.replace('/api/v1', ''), body = req.postData() ? req.postDataJSON() : null
        calls.push({ path, body })
        const respond = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
        if (path === '/auth/me') return respond(user)
        if (path === '/auth/login') return respond({ access_token: 'renewed-test-token', user })
        if (path.startsWith('/users/') && path.endsWith('/accounts')) return respond({ accounts: [] })
        if (path === '/sinan/status') return respond({ verified: false })
        if (path.includes('/notifications')) return respond({ items: [], total: 0 })
        if (path === '/meta-auth/authorize-first') return respond({ authorization_url: baseURL + callback })
        if (path === '/meta-auth/claim') {
          claims += 1
          assert.deepEqual(body, { state: 'test-intent', receipt: 'test-receipt' })
          if (options.expired && claims === 1) return respond({ detail: '登录已过期' }, 401)
          if (options.claimError) return respond({ detail: '本次授权回执已失效，请重新授权' }, 403)
          return respond({ credential_id: 'owned-credential' })
        }
        if (path === '/meta-auth/ad-accounts') {
          discoveries += 1
          assert.equal(url.searchParams.get('credential_id'), 'owned-credential')
          if (options.discoveryError && discoveries === 1) return respond({ detail: '账户读取暂时失败，请重试' }, 503)
          return respond({ accounts: [{ id: 'act_new', name: '回跳后可接入账户', business: { id: 'bm_new', name: '测试 BM' } }] })
        }
        if (path === '/meta-auth/complete-accounts') {
          assert.deepEqual(body, { credential_id: 'owned-credential', account_ids: ['act_new'] })
          imported = true
          return respond({ accounts: [{ id: 'new-account', account_id: 'act_new' }], page_sync: { status: 'SUCCESS' } })
        }
        if (path === '/accounts') {
          if (options.slowList && !waitingList) { waitingList = true; await delayedList }
          return respond(imported ? [{ id: 'new-account', account_id: 'act_new', account_name: '回跳后可接入账户', system_status: 'ACTIVE', is_deployable: true }] : [])
        }
        return respond([])
      })
      return { context, page, calls, releaseList, waiting: () => waitingList }
    }
    async function selection(page) {
      await page.getByText('选择要接入的广告账户', { exact: true }).waitFor()
      await page.locator('.business-option').getByText('回跳后可接入账户', { exact: true }).waitFor()
      assert.equal(new URL(page.url()).search, '')
    }
    async function login(page) {
      await page.waitForURL(url => url.pathname === '/login' && url.searchParams.has('redirect'))
      assert.equal(new URL(page.url()).searchParams.get('redirect'), callback)
      await page.locator('#username').fill('oauth-tester')
      await page.locator('#password').fill('test-password')
      await page.getByRole('button', { name: /登\s*录/ }).click()
      await selection(page)
    }
    const normal = await scenario()
    await normal.page.goto(baseURL + '/dashboard/accounts')
    await normal.page.getByRole('button', { name: '接入我的 Meta 账号', exact: true }).click()
    await normal.page.getByRole('button', { name: '登录 Meta 并授权', exact: true }).click()
    await selection(normal.page)
    assert.equal(normal.context.pages().length, 1, 'OAuth should return in the current tab')
    assert.equal(normal.calls.filter(c => c.path === '/meta-auth/claim').length, 1)
    assert(normal.calls.findIndex(c => c.path === '/meta-auth/claim') < normal.calls.findIndex(c => c.path === '/meta-auth/ad-accounts'))
    await normal.page.locator('.business-option .el-checkbox').click()
    await normal.page.getByRole('button', { name: '确认接入并同步', exact: true }).click()
    await normal.page.getByRole('heading', { name: 'Meta 授权成功', exact: true }).waitFor()
    assert.equal(normal.calls.filter(c => c.path === '/meta-auth/complete-accounts').length, 1)
    await normal.context.close()
    console.log('PASS current-tab OAuth, signed claim before discovery, selection and import')
    const slow = await scenario({ slowList: true })
    try {
      await slow.page.goto(baseURL + callback, { waitUntil: 'domcontentloaded' })
      await selection(slow.page)
      assert.equal(slow.waiting(), true)
      assert.equal(slow.calls.filter(c => c.path === '/meta-auth/claim').length, 1)
      console.log('PASS callback proceeds while the account list is still loading')
    } finally { slow.releaseList(); await slow.context.close() }
    const failed = await scenario({ claimError: true })
    await failed.page.goto(baseURL + callback)
    await failed.page.locator('.el-dialog .el-alert').getByText('本次授权回执已失效，请重新授权', { exact: true }).waitFor()
    await failed.page.getByRole('button', { name: '登录 Meta 并授权', exact: true }).waitFor()
    assert.equal(failed.calls.filter(c => c.path === '/meta-auth/ad-accounts').length, 0)
    assert.equal(new URL(failed.page.url()).search, '')
    await failed.context.close()
    console.log('PASS failed claim displays its reason and prevents asset discovery')
    const malformed = await scenario()
    await malformed.page.goto(baseURL + '/dashboard/accounts?meta_auth=businesses&credential_id=unclaimed&receipt=test-receipt')
    await malformed.page.locator('.el-dialog .el-alert').getByText('授权回调缺少 state，请重新发起授权', { exact: true }).waitFor()
    assert.equal(malformed.calls.filter(c => c.path === '/meta-auth/claim' || c.path === '/meta-auth/ad-accounts').length, 0)
    await malformed.context.close()
    console.log('PASS incomplete signed callbacks are rejected before asset access')
    const direct = await scenario()
    await direct.page.goto(baseURL + '/dashboard/accounts?meta_auth=businesses&credential_id=owned-credential')
    await selection(direct.page)
    assert.equal(direct.calls.filter(c => c.path === '/meta-auth/claim').length, 0)
    await direct.context.close()
    console.log('PASS direct-mode owned credentials still enter account selection')
    const cancelled = await scenario()
    await cancelled.page.goto(baseURL + '/dashboard/accounts?meta_auth=error&message=' + encodeURIComponent('用户取消了 Meta 授权'))
    await cancelled.page.locator('.el-dialog .el-alert').getByText('用户取消了 Meta 授权', { exact: true }).waitFor()
    assert.equal(cancelled.calls.filter(c => c.path === '/meta-auth/claim').length, 0)
    assert.equal(new URL(cancelled.page.url()).search, '')
    await cancelled.context.close()
    console.log('PASS cancellation displays its reason')
    const retry = await scenario({ discoveryError: true })
    await retry.page.goto(baseURL + callback)
    await retry.page.locator('.el-dialog .el-alert').getByText('账户读取暂时失败，请重试', { exact: true }).waitFor()
    await retry.page.getByRole('button', { name: '重新读取账户', exact: true }).click()
    await selection(retry.page)
    assert.equal(retry.calls.filter(c => c.path === '/meta-auth/claim').length, 1)
    assert.equal(retry.calls.filter(c => c.path === '/meta-auth/ad-accounts').length, 2)
    await retry.context.close()
    console.log('PASS account discovery retry does not reuse the receipt')
    const loggedOut = await scenario({ authenticated: false })
    await loggedOut.page.goto(baseURL + callback)
    await login(loggedOut.page)
    await loggedOut.context.close()
    console.log('PASS logged-out callback continues after login')
    const expired = await scenario({ expired: true })
    await expired.page.goto(baseURL + callback)
    await login(expired.page)
    assert.equal(expired.calls.filter(c => c.path === '/meta-auth/claim').length, 2)
    await expired.context.close()
    console.log('PASS expired login during claim recovers the callback')
    assert.deepEqual(errors, [])
    console.log('PASS safe internal redirects reject external destinations')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
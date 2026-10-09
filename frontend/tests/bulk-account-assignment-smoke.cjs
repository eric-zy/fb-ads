const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const fs = require('node:fs')
const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const admin = { id: 'admin', username: '管理员', role: 'tenant_admin', tenant_id: 'test', permissions: [], settings: {} }
const user = { id: 'publisher', username: 'test002' }
const accounts = [1, 2, 3].map(i => ({ id: `account-${i}`, account_id: `act_${i}`, account_name: `批量账户 ${i}`, system_status: 'ACTIVE', account_status: '1', risk_score: 0, currency: 'USD' }))
const candidate = { connection_id: 'connection', meta_user_id: 'fb-owner', authorized_by_username: '授权管理员', page_count: 1, health: 'ACTIVE' }
const otherCandidate = { ...candidate, connection_id: 'other-connection', meta_user_id: 'fb-other', authorized_by_username: '另一授权人' }
const collaborator = { id: 'collaborator', username: '协作投手' }
const calls = [], errors = []
let busy = true, blocked = false, multipleCandidates = false
let page

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-bulk-assignment', url: baseURL }])
    await context.addInitScript(data => { localStorage.setItem('user', JSON.stringify(data)); localStorage.setItem('site-locale', 'zh') }, admin)
    page = await context.newPage(); page.setDefaultTimeout(10000)
    page.on('pageerror', error => errors.push(error.message))
    const result = (id, status = 'READY') => ({ account_id: id, account_name: accounts.find(a => a.id === id).account_name,
      status, preview_hash: `preview-${id}`, old_primary_user_id: 'original', old_primary_label: '原负责人', primary_label: user.username, primary_changed: true,
      assignments: [{ user_id: user.id, username: user.username, execution_label: '授权管理员 · Meta fb-owner' }], warnings: [] })
    await page.route('**/*', route => {
      const req = route.request(), url = new URL(req.url())
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const path = url.pathname.replace('/api/v1', ''), body = req.postData() ? req.postDataJSON() : null
      calls.push({ path, body })
      const respond = (data, headers = {}) => route.fulfill({ status: 200, contentType: 'application/json', headers, body: JSON.stringify(data) })
      if (path === '/auth/me') return respond(admin)
      if (path === '/accounts') return respond(url.searchParams.get('page') === '2' ? [accounts[2]] : accounts.slice(0, 2), { 'x-total-count': '21' })
      if (path.startsWith('/users/') && path.endsWith('/accounts')) return respond({ accounts })
      if (path.endsWith('/users')) return respond([{ user_id: 'original', username: '原负责人', assignment_status: 'ACTIVE', is_primary: true }])
      if (path === '/accounts/bulk-assignment/context') return respond({ users: [user, collaborator], items: body.account_ids.map(id => ({
        account_id: id, account_name: accounts.find(a => a.id === id).account_name,
        candidates: multipleCandidates ? [candidate, otherCandidate] : [candidate], assignments: [{ user_id: 'original', username: '原负责人', assignment_role: 'PRIMARY', effective: true }],
      })) })
      if (path === '/accounts/bulk-assignment/preview') return respond({ items: body.account_ids.map(id => blocked && id === 'account-3'
        ? { ...result(id, 'BLOCKED'), error: '此账户缺少有效授权' } : result(id)), ready_count: body.account_ids.length - Number(blocked), blocked_count: Number(blocked) })
      if (path === '/accounts/bulk-assignment/submit') return respond({ items: body.account_ids.map(id => busy && id === 'account-2'
        ? { account_id: id, account_name: '批量账户 2', status: 'FAILED', error: '账户正在被其他用户操作，请稍后重试' } : result(id, 'SUCCESS')),
      success_count: body.account_ids.length - Number(busy && body.account_ids.includes('account-2')), failed_count: Number(busy && body.account_ids.includes('account-2')) })
      if (path === '/sinan/status') return respond({ verified: false })
      if (path.includes('notifications')) return respond({ total: 0, items: [] })
      return respond([])
    })
    await page.goto(`${baseURL}/admin/accounts`)
    assert.equal(await page.getByRole('button', { name: '分配给投手', exact: true }).count(), 0)
    await page.locator('.el-table__body tr').filter({ hasText: '批量账户 1' }).locator('.el-checkbox').click()
    await page.locator('.el-table__body tr').filter({ hasText: '批量账户 2' }).locator('.el-checkbox').click()
    await page.locator('.el-pagination .btn-next').click()
    await page.getByText('批量账户 3', { exact: true }).waitFor()
    await page.locator('.el-table__body tr').filter({ hasText: '批量账户 3' }).locator('.el-checkbox').click()
    await page.getByText('已选 3 个账户（含跨页选择）', { exact: true }).waitFor()
    await page.getByRole('button', { name: '批量添加协作者', exact: true }).click()
    let dialog = page.getByRole('dialog', { name: '批量添加协作者（3 个账户）' })
    await dialog.locator('.el-form-item').filter({ hasText: /^目标投手/ }).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible').getByRole('option', { name: user.username, exact: true }).click()
    await page.keyboard.press('Escape')
    await dialog.locator('.el-radio').filter({ hasText: '使用已接入的 Meta 授权' }).click()
    await dialog.locator('.el-form-item').filter({ hasText: /^这批账户的授权/ }).getByText(/授权管理员 · Meta fb-owner/).waitFor()
    assert.equal(await dialog.getByRole('button', { name: /^确认分配/ }).count(), 0)
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).click()
    await dialog.getByRole('button', { name: '确认分配（3 个账户）', exact: true }).waitFor()
    fs.mkdirSync('test-results', { recursive: true })
    await dialog.screenshot({ path: 'test-results/bulk-account-assignment-preview.png' })
    await dialog.getByRole('button', { name: '确认分配（3 个账户）', exact: true }).click()
    await dialog.getByText('成功 2 个，失败 1 个', { exact: true }).waitFor()
    const first = calls.filter(x => x.path.endsWith('/submit')).at(-1).body
    assert.deepEqual([...first.account_ids].sort(), ['account-1', 'account-2', 'account-3'])
    assert.equal(first.action, 'COLLABORATOR')
    assert.equal(first.execution_connection_id, candidate.connection_id)
    assert.equal(first.preserve_existing_execution, true)
    assert.deepEqual(first.execution_overrides, {})
    busy = false
    await dialog.getByRole('button', { name: '重试失败项（1）', exact: true }).click()
    await dialog.getByText('成功 3 个，失败 0 个', { exact: true }).waitFor()
    const retry = calls.filter(x => x.path.endsWith('/submit')).at(-1).body
    assert.deepEqual(retry.account_ids, ['account-2'])
    assert.equal(retry.idempotency_key, first.idempotency_key)
    assert.equal(retry.preview_hashes['account-2'], first.preview_hashes['account-2'])
    await dialog.getByRole('button', { name: '完成', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })

    await page.getByRole('button', { name: '批量变更负责人', exact: true }).click()
    dialog = page.getByRole('dialog', { name: '批量变更负责人（3 个账户）' })
    assert.equal(await dialog.locator('.el-form-item').filter({ hasText: /^目标投手/ }).count(), 0)
    await dialog.locator('.el-form-item').filter({ hasText: /^新负责人/ }).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible').getByRole('option', { name: user.username, exact: true }).click(); await page.keyboard.press('Escape')
    await dialog.locator('.el-checkbox').filter({ hasText: '同时添加协作者' }).click()
    await dialog.locator('.el-form-item').filter({ hasText: /^协作者/ }).locator('.el-select').click()
    await page.locator('.bulk-collaborator-options').getByRole('option', { name: collaborator.username, exact: true }).click(); await page.keyboard.press('Escape')
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).click()
    await dialog.getByRole('button', { name: '确认分配（3 个账户）', exact: true }).waitFor()
    assert.deepEqual(calls.filter(x => x.path.endsWith('/preview')).at(-1).body.user_ids.sort(), [user.id, collaborator.id].sort())
    await dialog.locator('.el-checkbox').filter({ hasText: '同时添加协作者' }).click()
    blocked = true
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).click()
    await dialog.getByRole('button', { name: '仅确认通过账户（2 个账户）', exact: true }).waitFor()
    assert.equal(await dialog.getByText('可保存', { exact: true }).count(), 2)
    await dialog.getByText('可保存', { exact: true }).first().waitFor({ state: 'visible' })
    await dialog.screenshot({ path: 'test-results/bulk-primary-preview.png' })
    await dialog.locator('.el-radio').filter({ hasText: '投手使用自己的 Meta 授权' }).click()
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).waitFor()
    assert.equal(await dialog.getByRole('button', { name: /^确认分配/ }).count(), 0)
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).click()
    await dialog.getByRole('button', { name: '仅确认通过账户（2 个账户）', exact: true }).click()
    await dialog.getByText('成功 2 个，失败 1 个', { exact: true }).waitFor()
    const primary = calls.filter(x => x.path.endsWith('/submit')).at(-1).body
    assert.equal(primary.action, 'PRIMARY'); assert.equal(primary.primary_user_id, user.id)
    assert.deepEqual(primary.user_ids, [user.id])
    assert.deepEqual(primary.account_ids.sort(), ['account-1', 'account-2'])
    await dialog.getByRole('button', { name: '修改失败项', exact: true }).click()
    await page.getByRole('dialog', { name: '批量变更负责人（1 个账户）' }).waitFor()
    dialog = page.getByRole('dialog', { name: '批量变更负责人（1 个账户）' })
    await dialog.locator('.el-radio').filter({ hasText: '使用已接入的 Meta 授权' }).click()
    await dialog.locator('.authorization-summary').getByText(/授权管理员/).waitFor()
    assert.equal(await dialog.getByRole('checkbox', { name: '按账户单独设置', exact: true }).count(), 0)
    assert.equal(await dialog.getByText('账户授权例外', { exact: true }).count(), 0)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })

    multipleCandidates = true
    await page.getByRole('button', { name: '批量设置执行授权', exact: true }).click()
    dialog = page.getByRole('dialog', { name: '批量设置执行授权（3 个账户）' })
    await dialog.locator('.el-form-item').filter({ hasText: /^目标投手/ }).locator('.el-select').click()
    await page.locator('.el-select-dropdown:visible').getByRole('option', { name: user.username, exact: true }).click(); await page.keyboard.press('Escape')
    await dialog.locator('.el-form-item').filter({ hasText: /^这批账户的授权/ }).locator('.el-select').click()
    await page.locator('.bulk-execution-options').getByRole('option', { name: /授权管理员 · Meta fb-owner/ }).click(); await page.keyboard.press('Escape')
    assert.equal(await dialog.getByText('该账户使用的授权', { exact: true }).count(), 0)
    await dialog.locator('.el-checkbox').filter({ hasText: '按账户单独设置' }).click()
    await dialog.locator('.el-table__body tr').filter({ hasText: '批量账户 1' }).locator('.el-select').click()
    await page.locator('.bulk-account-options-account-1').getByRole('option', { name: /另一授权人 · Meta fb-other/ }).click(); await page.keyboard.press('Escape')
    await dialog.locator('.el-radio').filter({ hasText: '所选投手统一改用本次授权' }).click()
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).click()
    assert.equal(calls.filter(x => x.path.endsWith('/preview')).at(-1).body.execution_overrides['account-1'], 'other-connection')
    await dialog.locator('.el-checkbox').filter({ hasText: '按账户单独设置' }).click()
    await dialog.getByRole('button', { name: '下一步：核对变更', exact: true }).click()
    const simplified = calls.filter(x => x.path.endsWith('/preview')).at(-1).body
    assert.deepEqual(simplified.execution_overrides, {})
    assert.equal(simplified.preserve_existing_execution, false)
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: '取消全部选择', exact: true }).click()
    assert.equal(await page.getByText(/含跨页选择/).count(), 0)
    assert.equal(calls.filter(x => /\/assign$/.test(x.path)).length, 0)
    assert.deepEqual(errors, [])
    console.log('PASS: unified bulk entry, cross-page selection, delegation auto-fill, preview invalidation, partial save and retry, primary transfer, clear selection')
  } catch (error) {
    if (page) await page.screenshot({ path: 'test-results/bulk-assignment-failure.png', fullPage: true })
    throw error
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

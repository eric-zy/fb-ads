const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require('playwright')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'delete-admin', username: '删除测试', role: 'tenant_admin', tenant_id: 'test', permissions: [] }
const campaigns = [
  { id: 'campaign-a', name: '合并系列', status: 'ACTIVE', meta_status: 'ACTIVE', ad_account_id: 'account-a', grouped: true, grouped_ids: ['campaign-a', 'campaign-b'], account_count: 2, account_name: '账户A、账户B' },
  { id: 'legacy-campaign', name: '历史系列', status: 'DELETED', meta_status: 'PAUSED', deletion_state: 'LOCAL_REMOVED', ad_account_id: 'account-a', account_name: '账户A', meta_campaign_id: 'meta-legacy' },
  { id: 'deleted-campaign', name: '已删除系列', status: 'DELETED', meta_status: 'DELETED', deletion_state: 'REMOTE_DELETED', ad_account_id: 'account-a', account_name: '账户A', meta_campaign_id: 'meta-deleted' },
]
const details = {
  'campaign-a': { object_type: 'CAMPAIGN', object: { id: 'campaign-a', name: '系列A', status: 'ACTIVE', meta_campaign_id: 'meta-a' }, account: { id: 'account-a', account_name: '账户A' }, children: [{ ads: [{}] }], ancestors: {}, recent_actions: [] },
  'campaign-b': { object_type: 'CAMPAIGN', object: { id: 'campaign-b', name: '系列B', status: 'ACTIVE', meta_campaign_id: 'meta-b' }, account: { id: 'account-b', account_name: '账户B' }, children: [{ ads: [{}, {}] }], ancestors: {}, recent_actions: [] },
  'legacy-campaign': { object_type: 'CAMPAIGN', object: campaigns[1], account: { id: 'account-a', account_name: '账户A' }, children: [], ancestors: {}, recent_actions: [] },
}

async function main() {
  fs.mkdirSync('test-results', { recursive: true })
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  const errors = []; const posts = []; let actions = []; let outcome = 'UNKNOWN'
  try {
    const context = await browser.newContext({ viewport: { width: 1680, height: 1100 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-token', url: baseURL }])
    await context.addInitScript(user => { localStorage.setItem('user', JSON.stringify(user)); localStorage.setItem('site-locale', 'zh') }, user)
    const page = await context.newPage(); page.setDefaultTimeout(12000)
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const req = route.request(); const url = new URL(req.url()); const path = url.pathname.replace('/api/v1', '')
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const respond = value => route.fulfill({ contentType: 'application/json', body: JSON.stringify(value) })
      if (path === '/auth/me') return respond(user)
      if (path === '/campaigns') return respond({ items: campaigns, total: 3, page: 1, page_size: 20 })
      if (path === '/campaigns/deleted-campaign/detail') return respond({ template: { id: 'original-template' } })
      if (path === '/templates/original-template/clone') { posts.push({ clone: 'original-template' }); return respond({ id: 'copy-template' }) }
      if (path === '/templates') return respond([{ id: 'copy-template', name: '复制模板', status: 'ACTIVE', objective: 'OUTCOME_TRAFFIC', creative_config_json: {} }])
      if (path === '/jobs' || path === '/tasks') return respond([])
      if (path === '/delivery-actions') return respond(actions)
      if (/^\/delivery-objects\/CAMPAIGN\//.test(path)) return respond(details[path.split('/').at(-1)])
      if (/operation-lease/.test(path)) return respond({ lease: { lease_token: 'test-lease' } })
      if (/\/adsets$|\/ads$/.test(path)) return respond({ items: [], total: 0, page: 1, page_size: 20 })
      if (path === '/campaigns/actions') {
        const payload = req.postDataJSON(); posts.push(payload)
        actions = payload.ids.map(id => ({ id: `action-${id}`, action: 'DELETE', object_type: 'CAMPAIGN', object_id: id,
          account_id: details[id].account.id, object_name: details[id].object.name, account_name: details[id].account.account_name,
          meta_object_id: details[id].object.meta_campaign_id, status: outcome, error_message: outcome === 'UNKNOWN' ? '等待确认' : '没有权限' }))
        return respond({ status: 'QUEUED', action_ids: actions.map(row => row.id), task_ids: ['celery-task'], object_count: actions.length })
      }
      if (/\/delivery-actions\/[^/]+\/retry$/.test(path)) {
        posts.push({ retry: path, payload: req.postDataJSON() })
        actions[0].status = 'SUCCESS'; actions[0].remote_status = 'DELETED'
        return respond({ status: 'REQUESTED', action_id: actions[0].id, task_id: 'confirm-task' })
      }
      if (/^\/delivery-actions\//.test(path)) return respond(actions.find(row => row.id === path.split('/').at(-1)))
      return respond([])
    })
    await page.goto(`${baseURL}/dashboard/campaigns`)
    const campaignPane = page.locator('#pane-campaigns')
    await campaignPane.getByRole('button', { name: '删除 Meta 广告', exact: true }).first().click()
    let dialog = page.getByRole('dialog', { name: '删除 Meta 广告系列', exact: true })
    await dialog.getByText('meta-a', { exact: true }).waitFor()
    await dialog.getByText('meta-b', { exact: true }).waitFor()
    await dialog.getByText('1 个广告组，2 个广告', { exact: true }).waitFor()
    await page.waitForTimeout(300)
    await page.screenshot({ path: 'test-results/meta-delete-scope.png', fullPage: true })
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(posts.length, 0, 'Cancel must not submit any deletion')
    await campaignPane.getByRole('button', { name: '删除 Meta 广告', exact: true }).first().click()
    dialog = page.getByRole('dialog', { name: '删除 Meta 广告系列', exact: true })
    await dialog.getByText('meta-b', { exact: true }).waitFor()
    await dialog.locator('.el-table__body tr').nth(1).locator('.el-checkbox').click()
    await dialog.getByRole('button', { name: '确认删除 Meta 对象', exact: true }).click()
    await page.locator('#pane-jobs').getByText('删除结果待确认', { exact: true }).waitFor()
    assert.deepEqual(posts[0].ids, ['campaign-a'])
    assert.deepEqual(Object.keys(posts[0].operation_leases), ['account-a'])
    await page.waitForTimeout(300)
    await page.screenshot({ path: 'test-results/meta-delete-unknown.png', fullPage: true })
    await page.getByRole('button', { name: '核对结果', exact: true }).click()
    await page.getByRole('button', { name: '确定', exact: true }).click()
    await page.getByText('Meta 删除成功', { exact: true }).waitFor()
    assert.equal(posts.filter(row => row.action === 'DELETE').length, 1, 'Reconciliation must not resubmit DELETE')

    await page.getByRole('tab', { name: '广告系列', exact: true }).click()
    const legacyRow = campaignPane.locator('.el-table__body tr').filter({ hasText: '历史系列' })
    await legacyRow.getByText('历史本地移除', { exact: true }).waitFor()
    assert.equal(await legacyRow.getByRole('button', { name: '取消归档', exact: true }).count(), 0)
    await legacyRow.getByRole('button', { name: '删除 Meta 广告', exact: true }).click()
    dialog = page.getByRole('dialog', { name: '删除 Meta 广告系列', exact: true })
    await dialog.getByText('meta-legacy', { exact: true }).waitFor()
    outcome = 'FAILED'
    await dialog.getByRole('button', { name: '确认删除 Meta 对象', exact: true }).click()
    await page.getByRole('button', { name: '重试失败项', exact: true }).waitFor()
    await page.getByRole('tab', { name: '广告系列', exact: true }).click()
    await legacyRow.getByText('历史本地移除', { exact: true }).waitFor()
    await campaignPane.locator('.el-table__body tr').filter({ hasText: '已删除系列' }).getByRole('button', { name: '复制新建', exact: true }).click()
    await page.waitForURL('**/dashboard/batch-publish?**')
    assert.equal(new URL(page.url()).searchParams.get('template_id'), 'copy-template')
    assert.equal(new URL(page.url()).searchParams.get('account_ids'), 'account-a')
    assert(posts.some(row => row.clone === 'original-template'))
    await page.locator('.el-select').filter({ hasText: '复制模板' }).first().waitFor()
    assert.deepEqual(errors, [])
    console.log('PASS Meta deletion: scope selection, cancel, exact object/account submission, unknown reconciliation, success, failed result and legacy removal')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })

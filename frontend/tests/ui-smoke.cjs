const assert = require('node:assert/strict')
const { chromium } = require('playwright')
const fs = require('node:fs')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const user = { id: 'smoke-user', username: '测试管理员', email: 'smoke@example.com', role: 'tenant_admin', tenant_id: 'test', permissions: [], settings: { language: 'zh-CN' } }
const account = { id: 'account-101', account_id: '101', account_name: '第101个账户', currency: 'USD', system_status: 'ACTIVE', account_status: '1', business: { id: null, name: '测试BM' }, accessible_businesses: [], credential: { status: 'ACTIVE' }, risk_score: 0 }
const template = { id: 'template-1', name: '测试投放模板', status: 'ACTIVE', objective: 'OUTCOME_TRAFFIC', optimization_goal: 'LINK_CLICKS', billing_event: 'IMPRESSIONS', buying_type: 'AUCTION', budget_type: 'DAILY', daily_budget: 10, creative_config_json: { page_id: 'page-1', creatives: [{ asset_id: 'asset-1', landing_url: 'https://example.com' }] } }
const calls = []
const errors = []
let lastPage
let saveFailure = true
let previewNumber = 0
let submitted = null
let instagramSyncFails = true

async function main() {
  // 对已构建前端执行隔离回归。API 全部由本文件模拟，外部网络请求全部阻断。
  let ready = false
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await fetch(baseURL, { signal: AbortSignal.timeout(1000) })).ok) { ready = true; break } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  assert(ready, `请先启动 Vite preview：${baseURL}`)
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
    await context.addCookies([{ name: 'auth_token', value: 'isolated-smoke-token', url: baseURL }])
    await context.addInitScript(data => { localStorage.setItem('user', JSON.stringify(data)); localStorage.setItem('site-locale', 'zh') }, user)
    const page = await context.newPage()
    lastPage = page
    page.setDefaultTimeout(12000)
    page.on('pageerror', error => errors.push(error.message))
    page.on('dialog', async dialog => { calls.push({ dialog: dialog.message() }); await dialog.dismiss() })
    await page.route('**/*', async route => {
      const request = route.request()
      const url = new URL(request.url())
      if (url.origin !== baseURL) return route.abort()
      if (!url.pathname.startsWith('/api/')) return route.continue()
      const path = url.pathname.replace('/api/v1', '')
      const method = request.method()
      calls.push({ path, method, query: url.search })
      const respond = (data, headers = {}, status = 200) => route.fulfill({ status, contentType: 'application/json', headers, body: JSON.stringify(data) })
      if (path === '/auth/me') return respond(user)
      if (path === '/users/smoke-user/settings') {
        if (saveFailure) return respond({ detail: '模拟保存失败' }, {}, 500)
        return respond({ settings: request.postDataJSON().settings })
      }
      if (path === '/accounts') return respond([{ ...account, account_name: url.searchParams.get('page') === '2' ? '第二页账户' : account.account_name }], { 'x-total-count': '121' })
      if (path === '/users') return respond([{ ...user, username: url.searchParams.get('page') === '2' ? '第二页用户' : user.username, is_active: true, created_at: '2026-10-06T00:00:00' }], { 'x-total-count': '121' })
      if (path === '/users/smoke-user/accounts') return respond({ accounts: [account] })
      if (path === '/accounts/available-for-deployment') return respond({ total: 1, accounts: [account] })
      if (path === '/meta-pages') return respond([{ id: 'page-local', page_id: 'page-1', page_name: '测试 Page', status: 'ACTIVE' }, { id: 'page-local-2', page_id: 'page-2', page_name: '第二个 Page', status: 'ACTIVE' }])
      if (path === '/media') {
        if (url.searchParams.get('workspace_mode') === 'archive') return respond([
          { id: 'archived-image', name: '已归档图片', asset_type: 'image', status: 'ARCHIVED', storage_status: 'DELETED', processing_status: 'READY', can_edit: true },
          { id: 'archived-video', name: '已归档视频', asset_type: 'video', status: 'ARCHIVED', storage_status: 'DELETED', processing_status: 'PENDING', can_edit: true },
        ])
        return respond([{ id: 'asset-1', name: '测试图片', asset_type: 'image', status: 'READY', storage_status: 'READY', processing_status: 'READY', is_current: true, can_edit: true, created_by: user.id, tag_ids: ['tag-us'] }])
      }
      if (path === '/creative-asset-tags/categories') return respond([
        { id: 'category-region', name: '地区', selection_mode: 'SINGLE', status: 'ACTIVE', sort_order: 0 },
        { id: 'category-format', name: '形式', selection_mode: 'MULTIPLE', status: 'ACTIVE', sort_order: 1 },
      ])
      if (path === '/creative-asset-tags') return respond([
        { id: 'tag-us', name: 'US', category_id: 'category-region', status: 'ACTIVE' },
        { id: 'tag-uk', name: 'UK', category_id: 'category-region', status: 'ACTIVE' },
        { id: 'tag-ugc', name: 'UGC', category_id: 'category-format', status: 'ACTIVE' },
      ])
      if (path === '/creative-asset-tags/assets/asset-1' && method === 'PUT') return respond({ asset_id: 'asset-1', tag_ids: request.postDataJSON().tag_ids })
      if (path === '/media/stats/overview') return respond({ asset_count: 2, ready_asset_count: 0, used_asset_count: 0, unused_asset_count: 2, inventory_usage_rate: 0, account_coverage_rate: 0, bound_account_count: 0, available_account_count: 0, binding_count: 0, ready_binding_count: 0, usage_count: 0, successful_usage_count: 0, failed_usage_count: 0, success_rate: 0, funnel: [{ key: 'inventory', label: '库存素材', count: 2, rate: 100 }, { key: 'ready', label: '就绪素材', count: 0, rate: 0 }], top_assets: [] })
      if (path === '/media/stats/performance') return respond({ has_data: false, items: [] })
      if (path === '/meta-instagram') return respond({ source: 'LOCAL_SNAPSHOT', items: url.searchParams.get('page_id') === 'page-1' ? [{ id: '200', username: 'brand', account_ids: [account.id] }] : [], accounts: [{ account_pk: account.id, account_name: account.account_name, sync_status: 'HEALTHY' }] })
      if (path === `/meta-instagram/${account.id}/sync`) return respond({ status: 'QUEUED', task_id: 'abc123' })
      if (path === '/meta-instagram/tasks/abc123') return respond({ task_id: 'abc123', state: instagramSyncFails ? 'FAILURE' : 'SUCCESS', error: instagramSyncFails ? '模拟 Instagram 同步失败' : null })
      if (path.endsWith('/accounts') || path === '/targeting/region-groups' || path === '/targeting/packages' || path === '/sinan-promotions') return respond([])
      if (path === '/sinan/status') return respond({ verified: false })
      if (path.includes('notifications')) return respond({ total: 0, items: [] })
      if (path === '/templates') return respond([template])
      if (path === '/meta-tracking-assets') return respond({ items: [], account_count: 1, source: 'LOCAL_SNAPSHOT', unsynced_account_ids: [], synced_at: null })
      if (path.endsWith('/audiences')) return respond([])
      if (path.endsWith('/rate-limit-status')) return respond({ rate_limits: { hour: { used: 0, limit: 100 } } })
      if (path.endsWith('/operation-lease')) return respond({ lease: { lease_token: 'mock-lease' } })
      if (path === '/jobs/campaign-preflight') {
        previewNumber++
        return respond({ passed: true, template_id: template.id, preview_id: `preview-${previewNumber}`, snapshot_hash: `hash-${previewNumber}`, ready_account_ids: [account.id], accounts: [{ account_id: account.id, status: 'READY' }], errors: [], warnings: [] })
      }
      if (path === '/jobs/campaign-dry-run') {
        const data = request.postDataJSON()
        return respond({ preview_id: data.preview_id, passed: true, will_write_meta: false, warnings: [], errors: [], accounts: [{ account_id: account.id, account_name: account.account_name, campaign_count: 1, adset_count: 1, ad_count: 1, errors: [], payload: { campaign: { name: template.name }, adsets: [] } }] })
      }
      if (path === '/jobs/campaign-create') {
        submitted = request.postDataJSON()
        return respond({ job_id: 'submitted-job', source: 'TEMPLATE', total_accounts: 1, status: 'PENDING' })
      }
      const job = (id) => ({ id, campaign_name: 'His Scent, Her Dreams_第2集', ad_names: ['His Scent, Her Dreams_第2集 G1 A1'], action_type: 'CREATE', status: 'SUCCESS', total_accounts: 1, success_count: 1, failed_count: 0, created_at: '2026-10-06T00:00:00', publisher: { username: '测试管理员' }, items: [] })
      if (path === '/jobs') return respond([job(url.searchParams.get('page') === '2' ? 'job-page-two' : 'job-page-one')], { 'x-total-count': '121' })
      if (path === '/jobs/submitted-job') return respond(job('submitted-job'))
      return respond([])
    })

    await page.goto(`${baseURL}/dashboard/settings`)
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await page.waitForFunction(() => document.querySelector('button.btn-primary')?.disabled === false)
    assert.equal(await page.getByText('已保存 ✓', { exact: true }).count(), 0)
    assert(calls.some(item => item.dialog?.includes('保存失败')))
    saveFailure = false
    await page.getByRole('button', { name: '保存设置', exact: true }).click()
    await page.getByText('已保存 ✓', { exact: true }).waitFor()
    await page.getByPlaceholder('搜索账户名称或 ID', { exact: true }).fill('101')
    await page.waitForRequest(req => new URL(req.url()).searchParams.get('search') === '101')
    console.log('PASS settings: failed save stays failed; successful save persists; account search reaches server')

    await page.goto(`${baseURL}/dashboard/jobs`)
    await page.locator('.job-id').waitFor()
    await page.getByText('His Scent, Her Dreams_第2集 G1 A1', { exact: true }).waitFor()
    await page.locator('.el-pagination .number').filter({ hasText: /^2$/ }).click()
    await page.locator('.job-id').filter({ hasText: 'ge-two' }).waitFor()
    assert(calls.some(item => item.path === '/jobs' && item.query.includes('page=2')))
    console.log('PASS jobs: server pagination reads page two')

    await page.goto(`${baseURL}/dashboard/batch-publish`)
    await page.getByText('His Scent, Her Dreams_第2集 G1 A1', { exact: true }).waitFor()
    await page.locator('.el-form-item').filter({ hasText: /^投放模板/ }).locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: template.name }).click()
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.locator('.el-form-item').filter({ hasText: /^广告账户/ }).locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: account.account_name }).click()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.getByRole('button', { name: '执行 Dry Run', exact: true }).waitFor()
    const submitButton = page.locator('.step-actions button').last()
    assert.equal(await submitButton.isDisabled(), true)
    await page.getByRole('button', { name: '执行 Dry Run', exact: true }).click()
    await page.getByText('Dry Run 通过，可以确认提交', { exact: true }).waitFor()
    assert.equal(await submitButton.isDisabled(), false)
    await page.getByRole('button', { name: '上一步', exact: true }).click()
    await page.locator('.el-form-item').filter({ hasText: /^预算覆盖/ }).getByRole('spinbutton').fill('20')
    await page.keyboard.press('Tab')
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.getByRole('button', { name: '执行 Dry Run', exact: true }).waitFor()
    assert.equal(await submitButton.isDisabled(), true)
    assert.equal(await page.getByText('Dry Run 通过，可以确认提交', { exact: true }).count(), 0)
    await page.getByRole('button', { name: '执行 Dry Run', exact: true }).click()
    await page.getByText('Dry Run 通过，可以确认提交', { exact: true }).waitFor()
    await submitButton.click()
    await page.getByRole('dialog', { name: '确认提交广告发布' }).getByRole('button', { name: '取消', exact: true }).click()
    assert.equal(submitted, null)
    assert.equal(previewNumber, 2)
    await submitButton.click()
    await Promise.all([
      page.waitForResponse(res => new URL(res.url()).pathname === '/api/v1/jobs/campaign-create'),
      page.getByRole('button', { name: '确认提交', exact: true }).click(),
    ])
    assert.equal(previewNumber, 2)
    assert.equal(submitted.preview_id, 'preview-2')
    assert.equal(submitted.snapshot_hash, 'hash-2')
    assert.equal(submitted.budget_override, 20)
    console.log('PASS delivery: submission requires Dry Run; changed configuration invalidates review; cancel has no job; submitted snapshot matches reviewed snapshot')

    await page.goto(`${baseURL}/admin/accounts`)
    await page.locator('.el-pagination .number').filter({ hasText: /^2$/ }).click()
    await page.getByText('第二页账户', { exact: true }).waitFor()
    await page.goto(`${baseURL}/admin/users`)
    await page.locator('.el-pagination .number').filter({ hasText: /^2$/ }).click()
    await page.getByText('第二页用户', { exact: true }).waitFor()
    console.log('PASS admin: accounts and users paginate on the server')

    await page.goto(`${baseURL}/dashboard/templates`)
    await page.getByRole('button', { name: '编辑', exact: true }).click()
    const editor = page.getByRole('dialog')
    for (let step = 0; step < 3; step++) await editor.getByRole('button', { name: '下一步', exact: true }).click()
    const templateIdentity = editor.locator('.instagram-selector')
    await templateIdentity.locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: '@brand' }).click()
    await templateIdentity.getByRole('button', { name: '同步 Instagram 身份', exact: true }).click()
    await page.getByText('模拟 Instagram 同步失败', { exact: true }).waitFor()
    assert.equal(await page.getByText('Instagram 身份同步完成', { exact: true }).count(), 0)
    instagramSyncFails = false
    await templateIdentity.getByRole('button', { name: '同步 Instagram 身份', exact: true }).click()
    await page.getByText('Instagram 身份同步完成', { exact: true }).waitFor()
    await editor.locator('.page-select').click()
    await page.getByRole('option').filter({ hasText: '第二个 Page' }).click()
    assert.equal(await templateIdentity.getByText('@brand (200)', { exact: true }).count(), 0)
    await editor.getByRole('button', { name: '取消', exact: true }).click()
    console.log('PASS Instagram template: identity selection; failed sync stays failed; successful sync reloads; Page change clears identity')

    await page.goto(`${baseURL}/dashboard/batch-publish`)
    await page.locator('.el-form-item').filter({ hasText: /^投放方式/ }).locator('.el-select').click()
    await page.getByRole('option', { name: '直接配置投放', exact: true }).click()
    await page.locator('.el-form-item').filter({ hasText: /^Facebook Page/ }).locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: '测试 Page' }).click()
    await page.locator('.instagram-selector .el-select').click()
    await page.getByRole('option').filter({ hasText: '@brand' }).click()
    await page.locator('.el-form-item').filter({ hasText: /^标签筛选/ }).locator('.el-select').click()
    await Promise.all([
      page.waitForRequest(req => new URL(req.url()).pathname === '/api/v1/media' && new URL(req.url()).searchParams.get('tag_ids') === 'tag-us'),
      page.getByRole('option', { name: 'US', exact: true }).click(),
    ])
    await page.locator('.direct-creative .el-select').click()
    await page.getByRole('option').filter({ hasText: '测试图片' }).last().click()
    await page.getByPlaceholder('https://example.com/landing（图片广告最终必须有有效链接）', { exact: true }).fill('https://example.com')
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    await page.locator('.el-form-item').filter({ hasText: /^广告账户/ }).locator('.el-select').click()
    await page.getByRole('option').filter({ hasText: account.account_name }).click()
    await page.keyboard.press('Escape')
    const preflightRequest = page.waitForRequest(req => new URL(req.url()).pathname.endsWith('/jobs/campaign-preflight'))
    await page.getByRole('button', { name: '下一步', exact: true }).click()
    assert.equal((await preflightRequest).postDataJSON().inline_config.instagram_user_id, '200')
    console.log('PASS Instagram direct: selected identity reaches preflight configuration')

    await page.goto(`${baseURL}/dashboard/material`)
    await page.locator('.card').filter({ hasText: '测试图片' }).waitFor()
    await page.locator('.card').getByRole('button', { name: '编辑标签' }).click()
    await page.getByRole('dialog', { name: /编辑标签/ }).getByRole('button', { name: '保存' }).click()
    assert(calls.some(item => item.path === '/creative-asset-tags/assets/asset-1' && item.method === 'PUT'))
    const uploadSessionCalls = () => calls.filter(item => item.path === '/media/upload-sessions').length
    const beforeChoose = uploadSessionCalls()
    await page.locator('.header-actions input[type="file"]').first().setInputFiles({ name: 'sample.png', mimeType: 'image/png', buffer: Buffer.from('fake image') })
    await page.getByRole('dialog', { name: '上传素材' }).getByText('sample.png', { exact: false }).waitFor()
    assert.equal(uploadSessionCalls(), beforeChoose)
    await page.getByRole('dialog', { name: '上传素材' }).getByRole('button', { name: '取消' }).click()
    console.log('PASS materials: edit tags; file selection opens confirmation without submitting an upload')
    await page.getByRole('button', { name: '已归档', exact: true }).click()
    await page.locator('.card').filter({ hasText: '已归档图片' }).waitFor()
    assert.equal(await page.locator('.card .status').filter({ hasText: '素材就绪' }).count(), 0)
    assert.equal(await page.locator('.card .status').filter({ hasText: '处理中' }).count(), 0)
    const previewRequests = calls.filter(item => item.path?.includes('/download-url')).length
    await page.locator('.card').filter({ hasText: '已归档视频' }).locator('.thumb').click()
    await page.getByText('素材已归档，源文件已删除，无法预览', { exact: true }).waitFor()
    assert.equal(calls.filter(item => item.path?.includes('/download-url')).length, previewRequests)
    console.log('PASS archive: deleted files are not shown as ready or processing; preview explains why')

    assert.deepEqual(errors, [])
    console.log('PASS no browser runtime exceptions')
  } catch (error) {
    fs.mkdirSync('test-results', { recursive: true })
    await lastPage.screenshot({ path: 'test-results/ui-smoke-failure.png', fullPage: true })
    throw error
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); console.error(JSON.stringify({ errors, calls: calls.slice(-15) }, null, 2)); process.exitCode = 1 })

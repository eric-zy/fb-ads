const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const { createRouter, createMemoryHistory } = require('vue-router')

const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText

async function main() {
  const routerSource = fs.readFileSync('src/router/index.ts', 'utf8')
  const routes = vm.runInNewContext(compile(routerSource.slice(routerSource.indexOf('const routes:'), routerSource.indexOf('const router =')) + '\nroutes;'))
  const stubComponents = records => records.forEach(record => {
    if (record.component) record.component = { render: () => null }
    if (record.children) stubComponents(record.children)
  })
  stubComponents(routes)
  const router = createRouter({ history: createMemoryHistory(), routes })
  const legacy = routes.find(route => route.path.startsWith('/app/'))
  const mappings = /const legacyRoutes[^=]*=\s*\{([\s\S]*?)\n\s*\}/.exec(routerSource)[1]
  const entries = [...mappings.matchAll(/'([^']+)': '([^']+)'/g)]
  assert(entries.length >= 20, 'exercise the complete legacy map')
  for (const [, original, target] of entries) {
    await router.push(original + '?source=bookmark#retained')
    assert.equal(router.currentRoute.value.path, target, original)
    assert.equal(router.currentRoute.value.query.source, 'bookmark')
    assert.equal(router.currentRoute.value.hash, '#retained')
    if (original === '/app/risk/rules') assert.equal(router.currentRoute.value.query.tab, 'rules')
    if (original === '/app/risk/stops') assert.equal(router.currentRoute.value.query.tab, 'executions')
  }
  // Vue Router also accepts a scalar parameter for callers using named route objects.
  assert.equal(legacy.redirect({ params: { legacyPath: 'overview' }, query: {}, hash: '' }).path, '/dashboard/overview')
  await router.push('/app/risk/rules/?tab=events')
  assert.equal(router.currentRoute.value.query.tab, 'rules')
  await router.push('/app/unknown/path')
  assert.equal(router.currentRoute.value.path, '/dashboard/overview')

  const functions = {}
  vm.runInNewContext(compile(fs.readFileSync('src/utils/reportComparison.ts', 'utf8')), { exports: functions })
  const { hasCompleteCoverage, percentageChange } = functions
  const quality = { account_id: 'a', status: 'FRESH', covered_days: 30, expected_days: 30, complete: true }
  assert(hasCompleteCoverage([quality], 'a', 30))
  assert(hasCompleteCoverage([{ ...quality, status: 'STALE' }], 'a', 30))
  for (const partial of [{ ...quality, complete: false }, { ...quality, covered_days: 1 }, { ...quality, expected_days: 1 },
    { ...quality, status: 'FAILED' }, { ...quality, status: 'SYNCING' }, { ...quality, account_id: 'other' }]) {
    assert.equal(hasCompleteCoverage([partial], 'a', 30), false)
  }
  assert.equal(hasCompleteCoverage([], 'a', 30), false)
  assert.equal(hasCompleteCoverage(undefined, 'a', 30), false)
  assert.equal(percentageChange(300, 100), '+200.0%')
  assert.equal(percentageChange(50, 100), '-50.0%')
  assert.equal(percentageChange(0, 0), '0%')
  assert.equal(percentageChange(10, 0), '新增')
  assert.equal(percentageChange(null, 0), '—')
  assert.equal(percentageChange(1, undefined), '—')
  assert.equal(percentageChange(Infinity, 1), '—')
  console.log(`PASS ${entries.length} legacy routes, query/hash preservation, coverage and percentage boundaries`)
}
main().catch(error => { console.error(error); process.exitCode = 1 })

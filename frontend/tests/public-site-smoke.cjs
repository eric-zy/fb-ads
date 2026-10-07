const assert = require('node:assert/strict')
const fs = require('node:fs')
const { chromium } = require('playwright')

const baseURL = process.env.UI_TEST_BASE_URL || 'http://127.0.0.1:4178'
const email = 'bhtf2026@ahpcwl.cn'
const pages = [
  { path: '/', en: 'Make ad delivery simpler', zh: /让广告投放，\s*更简单/ },
  { path: '/about', en: 'About us', zh: '关于公司' },
  { path: '/privacy-policy', en: 'Privacy Policy', zh: '隐私政策' },
  { path: '/terms', en: 'Terms of Service', zh: '服务条款' },
  { path: '/data-deletion', en: 'Data Deletion', zh: '数据删除' },
  { path: '/contact', en: 'Contact us', zh: '联系我们' },
]

async function selectLanguage(page, label) {
  await page.locator('.language-switcher').click()
  await page.getByRole('option', { name: label, exact: true }).click()
}

async function checkEmails(page) {
  const links = await page.locator('a[href^="mailto:"]').evaluateAll(elements => elements.map(element => ({ text: element.textContent, href: element.getAttribute('href') })))
  assert(links.length > 0)
  assert(links.every(link => link.text === email && link.href.startsWith(`mailto:${email}`)))
  assert(!(await page.locator('.public-card').innerText()).includes('yz6837053@gmail.com'))
}

async function main() {
  fs.mkdirSync('test-results', { recursive: true })
  const browser = await chromium.launch({ executablePath: process.env.UI_TEST_BROWSER_PATH || undefined, headless: true })
  const errors = []
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' })
    await context.addInitScript(() => { if (!localStorage.getItem('site-locale')) localStorage.setItem('site-locale', 'zh') })
    await context.route('**/*', route => {
      const url = new URL(route.request().url())
      if (url.origin !== baseURL) return route.abort()
      if (url.pathname.startsWith('/api/')) return route.fulfill({ contentType: 'application/json', body: '{"locale":"zh"}' })
      return route.continue()
    })
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(error.message))
    await page.goto(baseURL)
    await page.locator('h1').filter({ hasText: '让广告投放' }).waitFor()
    assert.equal(await page.locator('.language-switcher').count(), 1)
    assert.equal(await page.locator('.home .language').count(), 0)
    await selectLanguage(page, 'English')
    await page.getByRole('heading', { level: 1, name: pages[0].en }).waitFor()
    for (const target of pages) {
      if (target.path !== '/') await page.locator(`header nav a[href="${target.path}"]`).click()
      await page.getByRole('heading', { level: 1, name: target.en, exact: true }).waitFor()
      assert(!/[\u3400-\u9fff]/.test(await page.locator('.public-card').innerText()), `${target.path} still has visible Chinese copy`)
      assert.equal(await page.locator('html').getAttribute('lang'), 'en')
      await checkEmails(page)
    }
    await page.screenshot({ path: 'test-results/public-contact-en.png', fullPage: true })
    await page.reload()
    await page.getByRole('heading', { name: 'Contact us', exact: true }).waitFor()
    assert.equal(await page.evaluate(() => localStorage.getItem('site-locale')), 'en')
    await page.locator('header nav a[href="/"]').click()
    await page.getByRole('heading', { level: 1, name: pages[0].en, exact: true }).waitFor()
    await page.screenshot({ path: 'test-results/public-home-en.png', fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'English homepage overflows on mobile')
    await page.screenshot({ path: 'test-results/public-home-en-mobile.png', fullPage: true })
    await selectLanguage(page, '中文')
    for (const target of pages) {
      if (target.path !== '/') await page.locator(`header nav a[href="${target.path}"]`).click()
      await page.getByRole('heading', { level: 1, name: target.zh, exact: true }).waitFor()
      assert.equal(await page.locator('html').getAttribute('lang'), 'zh-CN')
      await checkEmails(page)
    }
    console.log('PASS public site: all six pages switch navigation, body and footer; email links updated; reload persists language; mobile fits')

    // A slow region lookup must not overwrite a language chosen by the visitor.
    const raceContext = await browser.newContext({ locale: 'zh-CN' })
    let reply
    const pending = new Promise(resolve => { reply = resolve })
    await raceContext.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.origin !== baseURL) return route.abort()
      if (url.pathname === '/api/v1/public/locale') {
        await pending
        return route.fulfill({ contentType: 'application/json', body: '{"locale":"zh"}' })
      }
      if (url.pathname.startsWith('/api/')) return route.abort()
      return route.continue()
    })
    const racePage = await raceContext.newPage()
    racePage.on('pageerror', error => errors.push(error.message))
    const localeRequest = racePage.waitForRequest(request => request.url().endsWith('/api/v1/public/locale'))
    await racePage.goto(baseURL)
    await localeRequest
    await selectLanguage(racePage, 'English')
    const localeResponse = racePage.waitForResponse(response => response.url().endsWith('/api/v1/public/locale'))
    reply()
    await localeResponse
    await racePage.getByRole('heading', { level: 1, name: pages[0].en }).waitFor()
    assert.equal(await racePage.evaluate(() => localStorage.getItem('site-locale')), 'en')
    assert.deepEqual(errors, [])
    console.log('PASS public locale: a late region lookup preserves the visitor’s explicit choice')
  } finally { await browser.close() }
}

main().catch(error => { console.error(error); process.exitCode = 1 })

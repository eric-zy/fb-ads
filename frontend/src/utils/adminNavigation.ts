import type { Router } from 'vue-router'

const defaultAdminRoute = '/admin/dashboard'

function storageKey(userId: string, tenantId?: string | null) {
  return `admin-return:${userId}:${tenantId || ''}`
}

export function rememberAdminRoute(userId: string, tenantId: string | null | undefined, fullPath: string) {
  try {
    sessionStorage.setItem(storageKey(userId, tenantId), fullPath)
  } catch {
    // 禁用浏览器存储时仍可使用默认的管理后台入口。
  }
}

export function getAdminReturnRoute(router: Router, userId?: string, tenantId?: string | null): string {
  if (!userId) return defaultAdminRoute
  try {
    const saved = sessionStorage.getItem(storageKey(userId, tenantId))
    if (!saved || !saved.startsWith('/admin/')) return defaultAdminRoute
    const resolved = router.resolve(saved)
    if (resolved.matched.some(record => record.meta.requiresAdmin)
      && !resolved.matched[resolved.matched.length - 1]?.redirect) return resolved.fullPath
  } catch {
    // 失效或不可读取的历史路径回退到后台首页。
  }
  return defaultAdminRoute
}

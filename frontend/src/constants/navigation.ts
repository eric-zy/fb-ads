import type { Component } from 'vue'
import {
  DataBoard,
  Promotion,
  Connection,
  TrendCharts,
  Warning,
  Setting,
} from '@element-plus/icons-vue'

export type NavRole = 'admin' | 'platform_admin' | 'tenant_admin' | 'manager' | 'user'

export interface NavItem {
  key: string
  label: string
  route: string
  roles?: NavRole[]
  permissions?: string[]
  badge?: string
}

export interface NavSection {
  key: string
  label: string
  icon: Component
  items: NavItem[]
}

export const APP_NAVIGATION: NavSection[] = [
  {
    key: 'overview',
    label: '总览',
    icon: DataBoard,
    items: [
      { key: 'app-overview', label: '经营总览', route: '/dashboard/overview' },
    ],
  },
  {
    key: 'delivery',
    label: '投放管理',
    icon: Promotion,
    items: [
      { key: 'campaigns', label: 'Campaign', route: '/dashboard/campaigns' },
      { key: 'templates', label: '投放模板', route: '/dashboard/templates' },
      { key: 'batch-publish', label: '批量投放', route: '/dashboard/batch-publish' },
      { key: 'jobs', label: '任务中心', route: '/dashboard/jobs' },
      { key: 'material', label: '素材资产', route: '/dashboard/material' },
      { key: 'scheduled-tasks', label: '定时任务', route: '/dashboard/scheduled-tasks' },
    ],
  },
  {
    key: 'accounts',
    label: '账号中心',
    icon: Connection,
    items: [
      { key: 'platforms', label: '平台管理', route: '/dashboard/accounts', roles: ['admin', 'manager'] },
      { key: 'meta-accounts', label: 'Meta 账号', route: '/dashboard/accounts', roles: ['admin', 'manager'] },
      { key: 'bms', label: 'BM 管理', route: '/dashboard/accounts', roles: ['admin', 'manager'] },
      { key: 'ad-accounts', label: '广告账户', route: '/dashboard/accounts' },
      { key: 'account-tree', label: 'BM / 账户树', route: '/dashboard/accounts' },
    ],
  },
  {
    key: 'reports',
    label: '数据中心',
    icon: TrendCharts,
    items: [
      { key: 'reports-overview', label: '系统总报表', route: '/dashboard/reports' },
      { key: 'reports-platform', label: '平台报表', route: '/dashboard/reports' },
      { key: 'reports-bm', label: 'BM 报表', route: '/dashboard/reports' },
      { key: 'reports-account', label: '广告账户报表', route: '/dashboard/account-overview' },
    ],
  },
  {
    key: 'risk',
    label: '风控中心',
    icon: Warning,
    items: [
      { key: 'risk-accounts', label: '风险账户', route: '/dashboard/risk-control?tab=events' },
      { key: 'risk-stops', label: '止损记录', route: '/dashboard/risk-control?tab=executions' },
      { key: 'risk-rules', label: '风控规则', route: '/dashboard/risk-control?tab=rules', roles: ['admin', 'manager'] },
    ],
  },
  {
    key: 'system',
    label: '系统管理',
    icon: Setting,
    items: [
      { key: 'system-users', label: '用户', route: '/admin/users', roles: ['admin'] },
      { key: 'system-roles', label: '角色', route: '/admin/roles', roles: ['admin'] },
      { key: 'system-permissions', label: '权限', route: '/admin/roles', roles: ['admin'] },
      { key: 'system-logs', label: '操作日志', route: '/admin/operations', roles: ['admin'] },
      { key: 'system-settings', label: '系统设置', route: '/dashboard/settings' },
    ],
  },
]

export function canAccessNavItem(item: NavItem, role?: NavRole | null): boolean {
  if (!item.roles || item.roles.length === 0) return true
  if (!role) return false
  return item.roles.includes(role === 'platform_admin' || role === 'tenant_admin' ? 'admin' : role)
}

export function canAccessPermission(permission: string, permissions?: string[] | null): boolean {
  return !!permissions?.includes(permission)
}

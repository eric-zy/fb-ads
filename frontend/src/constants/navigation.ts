import type { Component } from 'vue'
import {
  DataBoard,
  Promotion,
  Connection,
  TrendCharts,
  Warning,
  Setting,
} from '@element-plus/icons-vue'

export type NavRole = 'admin' | 'manager' | 'user'

export interface NavItem {
  key: string
  label: string
  route: string
  roles?: NavRole[]
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
      { key: 'app-overview', label: '经营总览', route: '/app/overview' },
    ],
  },
  {
    key: 'delivery',
    label: '投放管理',
    icon: Promotion,
    items: [
      { key: 'campaigns', label: 'Campaign', route: '/app/delivery/campaigns' },
      { key: 'templates', label: '投放模板', route: '/app/delivery/templates' },
      { key: 'batch-publish', label: '批量投放', route: '/app/delivery/batch-publish' },
      { key: 'jobs', label: '任务中心', route: '/app/delivery/jobs' },
      { key: 'material', label: '素材资产', route: '/app/delivery/material' },
      { key: 'scheduled-tasks', label: '定时任务', route: '/app/delivery/scheduled-tasks' },
    ],
  },
  {
    key: 'accounts',
    label: '账号中心',
    icon: Connection,
    items: [
      { key: 'platforms', label: '平台管理', route: '/app/accounts/platforms', roles: ['admin', 'manager'] },
      { key: 'meta-accounts', label: 'Meta 账号', route: '/app/accounts/meta-accounts', roles: ['admin', 'manager'] },
      { key: 'bms', label: 'BM 管理', route: '/app/accounts/bms', roles: ['admin', 'manager'] },
      { key: 'ad-accounts', label: '广告账户', route: '/app/accounts/ad-accounts' },
      { key: 'account-tree', label: 'BM / 账户树', route: '/app/accounts/tree' },
    ],
  },
  {
    key: 'reports',
    label: '数据中心',
    icon: TrendCharts,
    items: [
      { key: 'reports-overview', label: '系统总报表', route: '/app/reports/overview' },
      { key: 'reports-platform', label: '平台报表', route: '/app/reports/platforms' },
      { key: 'reports-bm', label: 'BM 报表', route: '/app/reports/bms' },
      { key: 'reports-account', label: '广告账户报表', route: '/app/reports/accounts' },
    ],
  },
  {
    key: 'risk',
    label: '风控中心',
    icon: Warning,
    items: [
      { key: 'risk-accounts', label: '风险账户', route: '/app/risk/accounts' },
      { key: 'risk-stops', label: '止损记录', route: '/app/risk/stops' },
      { key: 'risk-rules', label: '风控规则', route: '/app/risk/rules', roles: ['admin', 'manager'] },
    ],
  },
  {
    key: 'system',
    label: '系统管理',
    icon: Setting,
    items: [
      { key: 'system-users', label: '用户', route: '/app/system/users', roles: ['admin'] },
      { key: 'system-roles', label: '角色', route: '/app/system/roles', roles: ['admin'] },
      { key: 'system-permissions', label: '权限', route: '/app/system/permissions', roles: ['admin'] },
      { key: 'system-logs', label: '操作日志', route: '/app/system/logs', roles: ['admin'] },
      { key: 'system-settings', label: '系统设置', route: '/app/system/settings' },
    ],
  },
]

export function canAccessNavItem(item: NavItem, role?: NavRole | null): boolean {
  if (!item.roles || item.roles.length === 0) return true
  if (!role) return false
  return item.roles.includes(role)
}

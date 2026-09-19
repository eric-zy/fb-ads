export interface PermissionItem {
  value: string
  label: string
  description: string
}

export interface PermissionGroup {
  key: string
  label: string
  description: string
  permissions: PermissionItem[]
}

/**
 * 权限目录的唯一前端来源。
 * 角色模板和用户直接授权都复用这里，避免两套权限清单逐渐不一致。
 */
export const permissionGroups: PermissionGroup[] = [
  {
    key: 'assets',
    label: '账户与资产',
    description: 'Meta 资产、授权连接和广告账户',
    permissions: [
      { value: 'meta_asset:manage', label: '管理 Meta 资产', description: '管理 BM、凭据、连接和 Page 同步' },
      { value: 'meta_account:read', label: '查看 BM', description: '查看 Business Manager 信息' },
      { value: 'meta_connection:read', label: '查看 Meta 授权', description: '查看 Meta 授权连接状态' },
      { value: 'ad_account:read', label: '查看广告账户', description: '查看可访问的广告账户' },
      { value: 'ad_account:manage', label: '管理广告账户', description: '绑定、编辑和维护广告账户' },
    ],
  },
  {
    key: 'jobs',
    label: '投放任务',
    description: '创建、执行和维护投放任务',
    permissions: [
      { value: 'job:create', label: '创建投放任务', description: '创建批量投放和定时任务' },
      { value: 'job:retry', label: '重试任务', description: '重新执行失败的任务项' },
      { value: 'job:cancel', label: '取消任务', description: '取消排队或执行中的任务' },
    ],
  },
  {
    key: 'campaigns',
    label: '广告系列',
    description: '管理已发布的 Campaign、Ad Set 和 Ad',
    permissions: [
      { value: 'campaign:read', label: '查看已发布广告', description: '查看投放对象和发布状态' },
      { value: 'campaign:pause', label: '暂停广告', description: '暂停已发布的投放对象' },
      { value: 'campaign:enable', label: '启用广告', description: '重新启用已暂停的投放对象' },
      { value: 'campaign:update_budget', label: '修改预算', description: '调整广告系列预算' },
      { value: 'campaign:sync', label: '同步 Meta 状态', description: '从 Meta 刷新投放状态' },
      { value: 'campaign:archive', label: '归档广告', description: '归档不再使用的投放对象' },
      { value: 'campaign:restore', label: '恢复广告', description: '恢复已归档的投放对象' },
      { value: 'campaign:delete', label: '移除广告记录', description: '删除本地广告记录' },
    ],
  },
  {
    key: 'insights',
    label: '数据分析',
    description: '查看投放表现和数据报表',
    permissions: [
      { value: 'insight:read', label: '查看报表', description: '查看广告账户消耗和投放报表' },
    ],
  },
  {
    key: 'settings',
    label: '系统设置',
    description: '访问个人和租户级系统设置',
    permissions: [
      { value: 'settings:read', label: '查看系统设置', description: '查看系统设置页面' },
    ],
  },
]

export const allPermissionItems = permissionGroups.flatMap(group => group.permissions)
export const allPermissionValues = allPermissionItems.map(item => item.value)

const permissionMap = new Map(allPermissionItems.map(item => [item.value, item]))

export function permissionLabel(value: string): string {
  return permissionMap.get(value)?.label || value
}

export function permissionGroupLabel(value: string): string {
  const group = permissionGroups.find(item => item.permissions.some(permission => permission.value === value))
  return group?.label || '其他权限'
}

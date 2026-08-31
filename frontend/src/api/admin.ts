// 用户与账户管理接口封装
import request from '@/utils/request'

// ============ 用户管理 ============
export interface AdminUser {
  id: string
  email: string
  username: string
  role: string
  company_id: string | null
  is_active: boolean
  is_verified: boolean
  permissions: string[]
  created_at: string | null
  last_login: string | null
}

export const userApi = {
  list: (params?: { search?: string; role?: string; is_active?: boolean; page?: number; page_size?: number }) =>
    request.get('/api/v1/users', { params }),
  create: (data: { email: string; username: string; password?: string; role?: string; company_id?: string; is_active?: boolean }) =>
    request.post('/api/v1/users', data),
  update: (id: string, data: Partial<{ email: string; username: string; role: string; company_id: string; is_active: boolean; permissions: string[] }>) =>
    request.put('/api/v1/users/' + id, data),
  resetPassword: (id: string, password: string) =>
    request.post('/api/v1/users/' + id + '/reset-password', { password }),
  toggleActive: (id: string) =>
    request.post('/api/v1/users/' + id + '/toggle-active'),
  delete: (id: string) =>
    request.delete('/api/v1/users/' + id),
}

// ============ 账户管理 ============

/** 系统侧状态：是否允许参与批量投放（管理员维护，同步不覆盖） */
export type SystemStatus = 'ACTIVE' | 'DISABLED'

export interface AdAccountItem {
  id: string
  account_id: string
  account_name: string
  currency: string
  timezone: string | null
  // 归属 BM
  business_id: string | null
  business_name: string | null
  // Meta 侧状态（同步覆盖）
  account_status: string | null
  effective_status: string | null
  disable_reason: string | null
  // 系统侧状态（同步不覆盖）
  system_status: SystemStatus
  system_status_reason: string | null
  system_status_at: string | null
  capabilities: Record<string, unknown> | null
  // 金额：一律最小货币单位（分），展示前用 utils/money 换算
  spend_cap: number
  amount_spent: number
  balance: number
  daily_spend_limit: number
  monthly_spend_limit: number
  // 风控 / 同步
  risk_score: number
  last_risk_check: string | null
  last_synced_at: string | null
  last_sync_error: string | null
  created_at: string | null
  updated_at: string | null
}

/** 可投放账户（available-for-deployment 返回结构） */
export interface DeployableAccount {
  id: string
  account_id: string
  account_name: string
  currency: string
  system_status: SystemStatus
  account_status: string | null
  business: { id: string | null; name: string | null; business_id: string | null }
  credential: { id: string | null; status: string | null; is_expired: boolean | null; masked: string | null }
}

export interface AccountUser {
  user_id: string
  username: string
  email: string
  role: string
}

export const accountApi = {
  list: (params?: {
    search?: string
    system_status?: string
    account_status?: string
    business_id?: string
    page?: number
    page_size?: number
  }) => request.get('/api/v1/accounts', { params }),
  detail: (id: string) =>
    request.get('/api/v1/accounts/' + id),
  create: (data: {
    business_id: string
    account_id: string
    account_name?: string
    account_status?: string
    currency?: string
    timezone?: string
    system_status?: SystemStatus
    daily_spend_limit?: number
    monthly_spend_limit?: number
    risk_score?: number
    skip_verification?: boolean
  }) => request.post('/api/v1/accounts', data),
  update: (id: string, data: Partial<{
    account_name: string
    currency: string
    timezone: string
    system_status: SystemStatus
    system_status_reason: string
    daily_spend_limit: number
    monthly_spend_limit: number
    risk_score: number
    business_id: string
    skip_verification: boolean
  }>) => request.put('/api/v1/accounts/' + id, data),
  freeze: (id: string, reason?: string) =>
    request.post('/api/v1/accounts/' + id + '/freeze', reason ? { reason } : {}),
  unfreeze: (id: string) => request.post('/api/v1/accounts/' + id + '/unfreeze'),
  /** 转移 BM 归属（business_id 必填，V1 不允许解除归属） */
  transfer: (id: string, data: { business_id: string | null; skip_verification?: boolean }) =>
    request.post('/api/v1/accounts/' + id + '/transfer', data),
  /** 批量操作：freeze / unfreeze / delete / transfer */
  bulk: (data: {
    action: 'freeze' | 'unfreeze' | 'delete' | 'transfer'
    account_ids: string[]
    reason?: string
    business_id?: string
    skip_verification?: boolean
  }) => request.post('/api/v1/accounts/bulk', data),
  /** 可参与批量投放的账户池（判断规则由后端统一计算，前端不要自行拼接） */
  availableForDeployment: (params?: { business_id?: string }) =>
    request.get('/api/v1/accounts/available-for-deployment', { params }),
  assign: (id: string, user_ids: string[]) => request.post('/api/v1/accounts/' + id + '/assign', { user_ids }),
  unassign: (id: string, user_ids: string[]) => request.post('/api/v1/accounts/' + id + '/unassign', { user_ids }),
  users: (id: string) => request.get('/api/v1/accounts/' + id + '/users'),
  delete: (id: string) => request.delete('/api/v1/accounts/' + id),
}

// ============ 主账号（BM）管理 ============

/** BM 业务状态（人工维护） */
export type BusinessStatus = 'ACTIVE' | 'DISABLED' | 'ARCHIVED'
/** BM 同步状态（同步任务维护），与业务状态不可混用 */
export type SyncStatus = 'PENDING' | 'SYNCING' | 'SUCCESS' | 'FAILED'

export interface MetaAccountItem {
  id: string
  name: string
  business_id: string
  app_id: string | null
  is_default: boolean
  // 业务状态
  status: BusinessStatus
  is_active: boolean
  // Meta 侧属性
  timezone: string | null
  currency: string | null
  description: string | null
  // 同步状态
  sync_status: SyncStatus
  last_synced_at: string | null
  last_sync_error: string | null
  account_count: number
  created_at: string | null
  updated_at: string | null
  // 凭据健康状态（三层分离：BM 主表不再存明文 Token）
  credential_id: string | null
  credential_status: string // ACTIVE / EXPIRED / INVALID / DISABLED / NONE
  credential_masked: string | null
  credential_expires_at: string | null
  credential_is_expired: boolean
  has_credential: boolean
  credential_source: string // CREDENTIALS / NONE
}

export interface VerifyResult {
  verified: boolean
  dev_mode: boolean
  error: string | null
  account_name: string | null
}

/** BM 连通性校验结果（verify_connection） */
export interface BusinessVerifyResult {
  ok: boolean
  dev_mode: boolean
  error: string | null
  business: Record<string, unknown> | null
  business_id_matched: boolean
}

/** 同步日志（meta_sync_logs，与 audit_logs 分开） */
export interface SyncLogItem {
  id: string
  business_id: string | null
  sync_type: 'BUSINESS' | 'AD_ACCOUNT' | 'FULL'
  status: 'RUNNING' | 'SUCCESS' | 'PARTIAL_SUCCESS' | 'FAILED'
  total_count: number
  success_count: number
  failed_count: number
  error_message: string | null
  error_detail: string | null
  celery_task_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string | null
}

/** 异步同步的提交结果 */
export interface SyncSubmitResult {
  success: boolean
  job_id: string
  status: 'QUEUED'
  message: string
}

export const metaAccountApi = {
  list: () => request.get('/api/v1/meta-accounts'),
  detail: (id: string) => request.get('/api/v1/meta-accounts/' + id),
  getDefault: () => request.get('/api/v1/meta-accounts/default'),
  create: (data: {
    name: string
    business_id: string
    access_token?: string
    app_id?: string
    is_default?: boolean
    token_type?: string
    timezone?: string
    currency?: string
    description?: string
    verify_before_save?: boolean
  }) => request.post('/api/v1/meta-accounts', data),
  update: (id: string, data: Partial<{
    name: string
    business_id: string
    access_token: string
    app_id: string
    is_default: boolean
    status: BusinessStatus
    timezone: string
    currency: string
    description: string
  }>) => request.put('/api/v1/meta-accounts/' + id, data),
  setDefault: (id: string) => request.post('/api/v1/meta-accounts/' + id + '/set-default'),
  remove: (id: string) => request.delete('/api/v1/meta-accounts/' + id),
  verify: (meta_account_id: string, account_id: string) =>
    request.post('/api/v1/meta-accounts/verify-account', { meta_account_id, account_id }),
  /** 异步同步该 BM 下的广告账户，返回 job_id，结果查 /sync-logs */
  syncAccounts: (id: string) =>
    request.post('/api/v1/meta-accounts/' + id + '/sync-accounts'),
  /** 该 BM 的同步日志 */
  syncLogs: (id: string, params?: { limit?: number }) =>
    request.get('/api/v1/meta-accounts/' + id + '/sync-logs', { params }),
  /** 验证该 BM 与凭据能否连通 Meta */
  verifyConnection: (id: string) => request.post('/api/v1/meta-accounts/' + id + '/verify'),
  /** 禁用 BM */
  disable: (id: string) => request.post('/api/v1/meta-accounts/' + id + '/disable'),
  /** 归档 BM */
  archive: (id: string) => request.post('/api/v1/meta-accounts/' + id + '/archive'),
  /** 轮换该 BM 的 Access Token */
  rotateToken: (id: string, data: { access_token: string; token_type?: string }) =>
    request.post('/api/v1/meta-accounts/' + id + '/rotate-token', data),
  /** 该 BM 名下的凭据列表（脱敏） */
  credentials: (id: string) => request.get('/api/v1/meta-accounts/' + id + '/credentials'),
}

// ============ 凭据管理 ============
export interface CredentialItem {
  id: string
  meta_account_id: string | null
  meta_account_name?: string | null
  business_id?: string | null
  name: string | null
  app_id: string | null
  token_type: string // USER / SYSTEM_USER / PAGE
  expires_at: string | null
  status: string // ACTIVE / VERIFYING / EXPIRED / INVALID / DISABLED
  last_error: string | null
  last_verified_at: string | null
  is_expired: boolean
  access_token_masked?: string | null
  created_at: string | null
  updated_at: string | null
}

export interface VerifyCredentialResult {
  credential_id: string
  valid: boolean
  dev_mode: boolean
  error: string | null
  token_info: { id: string; name: string } | null
  status: string
  last_verified_at: string | null
  last_error: string | null
}

export const credentialApi = {
  list: (params?: {
    meta_account_id?: string
    status?: string
    page?: number
    page_size?: number
  }) => request.get('/api/v1/credentials', { params }),
  detail: (id: string) => request.get('/api/v1/credentials/' + id),
  create: (data: {
    meta_account_id: string
    access_token: string
    name?: string
    app_id?: string
    token_type?: string
    expires_at?: string | null
    replace_active?: boolean
  }) => request.post('/api/v1/credentials', data),
  update: (id: string, data: Partial<{
    name: string
    app_id: string
    token_type: string
    expires_at: string | null
    status: string
  }>) => request.patch('/api/v1/credentials/' + id, data),
  /** 轮换 Token：写入新凭据，旧凭据默认保留为 DISABLED */
  rotate: (id: string, data: {
    access_token: string
    name?: string
    token_type?: string
    expires_at?: string | null
    keep_old?: boolean
  }) => request.post('/api/v1/credentials/' + id + '/rotate', data),
  verify: (id: string) => request.post('/api/v1/credentials/' + id + '/verify'),
  disable: (id: string) => request.post('/api/v1/credentials/' + id + '/disable'),
  enable: (id: string) => request.post('/api/v1/credentials/' + id + '/enable'),
  /** 查看明文（高危，服务端会写审计日志），必须显式 confirm=true */
  reveal: (id: string) =>
    request.post('/api/v1/credentials/' + id + '/reveal', { confirm: true }),
  remove: (id: string) => request.delete('/api/v1/credentials/' + id),
}

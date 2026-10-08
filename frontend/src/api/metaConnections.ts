import request from '@/utils/request'

export interface MetaConnection {
  id: string
  tenant_id: string
  meta_user_id: string
  app_id: string
  status: string
  health?: string
  authorized_by_user_id?: string | null
  authorized_by_username?: string
  is_owner?: boolean
  can_manage?: boolean
  execution_source?: 'PERSONAL' | 'DELEGATED'
  version?: number
  account_names?: string[]
  executable_account_ids?: string[]
  data_access_expires_at?: string | null
  scopes: string[]
  expires_at?: string | null
  last_synced_at?: string | null
  last_error?: string | null
  business_count: number
  account_count: number
  page_count: number
  credential_count: number
}

export const metaConnectionsApi = {
  list: (scope: 'mine' | 'tenant' | 'delegated' = 'mine') => request.get<MetaConnection[]>('/api/v1/meta-connections', { params: { scope } }),
  sync: (id: string) => request.post(`/api/v1/meta-connections/${id}/sync`),
  disconnect: (id: string) => request.post<{ cancelled_jobs: number }>(`/api/v1/meta-connections/${id}/disconnect`),
  chooseDefault: (id: string, accountIds: string[]) => request.post(`/api/v1/meta-connections/${id}/execution-default`, { account_ids: accountIds }),
  chooseReportingDefault: (id: string, accountIds: string[]) => request.post(`/api/v1/meta-connections/${id}/reporting-default`, { account_ids: accountIds }),
}

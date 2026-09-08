import request from '@/utils/request'

export interface MetaConnection {
  id: string
  tenant_id: string
  meta_user_id: string
  app_id: string
  status: string
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
  list: () => request.get<MetaConnection[]>('/api/v1/meta-connections'),
  sync: (id: string) => request.post(`/api/v1/meta-connections/${id}/sync`),
}

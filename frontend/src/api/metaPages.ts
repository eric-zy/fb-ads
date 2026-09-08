import request from '@/utils/request'

export interface MetaPage {
  id: string
  tenant_id: string
  page_id: string
  page_name: string
  category?: string | null
  tasks: string[]
  credential_id: string
  status: string
  last_error?: string | null
  last_synced_at?: string | null
}

export const metaPagesApi = {
  list: (status = 'ACTIVE') =>
    request.get<MetaPage[]>('/api/v1/meta-pages', { params: { status } }),
  sync: (credentialId: string) =>
    request.post('/api/v1/meta-pages/sync', null, { params: { credential_id: credentialId } }),
}

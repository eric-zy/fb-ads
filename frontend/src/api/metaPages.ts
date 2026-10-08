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
  list: async (status = 'ACTIVE', accountIds: string[] = []) => {
    const ids = [...new Set(accountIds)]
    const chunks: string[][] = []
    for (let i = 0; i < ids.length; i += 50) chunks.push(ids.slice(i, i + 50))
    if (!chunks.length) chunks.push([])
    const responses = await Promise.all(chunks.map(account_ids => request.get<MetaPage[]>(
      '/api/v1/meta-pages', { params: { status, ...(account_ids.length ? { account_ids } : {}) }, paramsSerializer: { indexes: null } },
    )))
    return { ...responses[0], data: responses[0].data.filter(page => responses.every(r => r.data.some(p => p.page_id === page.page_id))) }
  },
  syncAll: () => request.post('/api/v1/meta-pages/sync-all'),
  sync: (credentialId: string) =>
    request.post('/api/v1/meta-pages/sync', null, { params: { credential_id: credentialId } }),
}

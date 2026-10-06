import request from '@/utils/request'

export interface InstagramIdentity { id: string; username: string; account_ids: string[] }
export interface InstagramAccountHealth {
  account_pk: string
  account_name: string
  sync_status: 'HEALTHY' | 'NEVER' | 'STALE' | 'ERROR' | 'AUTH_CHANGED'
  page_error?: string | null
  last_synced_at?: string | null
}
export interface InstagramIdentityList { items: InstagramIdentity[]; accounts: InstagramAccountHealth[]; source: string }

export const metaInstagramApi = {
  async list(pageId: string, accountIds?: string[]) {
    const ids = [...new Set(accountIds || [])]
    const chunks: string[][] = []
    for (let offset = 0; offset < ids.length; offset += 50) chunks.push(ids.slice(offset, offset + 50))
    if (!chunks.length) chunks.push([])
    const responses = await Promise.all(chunks.map(account_ids => request.get<InstagramIdentityList>('/api/v1/meta-instagram', {
      params: { page_id: pageId, ...(account_ids.length ? { account_ids } : {}) }, paramsSerializer: { indexes: null },
    })))
    const merged = new Map<string, InstagramIdentity>()
    for (const response of responses) for (const item of response.data.items) {
      const previous = merged.get(item.id)
      merged.set(item.id, { ...item, account_ids: [...new Set([...(previous?.account_ids || []), ...item.account_ids])] })
    }
    return { items: [...merged.values()], accounts: responses.flatMap(response => response.data.accounts), source: 'LOCAL_SNAPSHOT' }
  },
  sync: (accountPk: string) => request.post<{ status: string; task_id: string }>(`/api/v1/meta-instagram/${accountPk}/sync`),
  taskStatus: (taskId: string) => request.get<{ task_id: string; state: string; error?: string | null }>(`/api/v1/meta-instagram/tasks/${taskId}`),
}

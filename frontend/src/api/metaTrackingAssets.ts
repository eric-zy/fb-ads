import request from '@/utils/request'

export interface MetaTrackingAsset {
  id: string
  name: string
  asset_type: 'PIXEL' | 'DATASET'
  account_ids: string[]
  account_names?: string[]
  last_fired_time?: string | null
  status?: string
  usable?: boolean
  last_synced_at?: string | null
  last_sync_error?: string | null
}

export interface TrackingAssetHealthItem {
  account_pk: string
  account_id: string
  account_name: string
  owner_type: string
  business_name?: string | null
  sync_status: 'HEALTHY' | 'STALE' | 'NEVER' | 'ERROR'
  last_synced_at?: string | null
  asset_count: number
  usable_count: number
  assets: Array<Pick<MetaTrackingAsset, 'id' | 'name' | 'asset_type'>>
}

export const metaTrackingAssetsApi = {
  list: (accountIds: string[]) => request.get<{ items: MetaTrackingAsset[]; account_count: number; synced_at: string }>(
    '/api/v1/meta-tracking-assets',
    // FastAPI 接收重复的 account_ids 参数；indexes: null 避免 axios
    // 默认序列化成 account_ids[]=xxx，保证多账户筛选可被后端正确解析。
    { params: { account_ids: accountIds }, paramsSerializer: { indexes: null } },
  ),
  health: () => request.get<{ items: TrackingAssetHealthItem[]; summary: Record<string, number> }>('/api/v1/meta-tracking-assets/health'),
  sync: (accountPk: string) => request.post<{ status: string; task_id?: string; account_pk: string }>(`/api/v1/meta-tracking-assets/${accountPk}/sync`),
}

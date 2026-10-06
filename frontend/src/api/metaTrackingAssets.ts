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

interface TrackingAssetList {
  items: MetaTrackingAsset[]
  account_count: number
  synced_at: string | null
  source: string
  unsynced_account_ids: string[]
}

async function listTrackingAssets(accountIds: string[]) {
  const ids = [...new Set(accountIds)]
  const chunks: string[][] = []
  for (let offset = 0; offset < ids.length; offset += 50) chunks.push(ids.slice(offset, offset + 50))
  if (!chunks.length) chunks.push([])
  const responses = await Promise.all(chunks.map(account_ids => request.get<TrackingAssetList>(
    '/api/v1/meta-tracking-assets', { params: { account_ids }, paramsSerializer: { indexes: null } },
  )))
  if (responses.length === 1) return responses[0]
  const merged = new Map<string, MetaTrackingAsset>()
  for (const response of responses) for (const item of response.data.items) {
    const key = `${item.asset_type}:${item.id}`
    const previous = merged.get(key)
    if (!previous) merged.set(key, { ...item })
    else {
      previous.account_ids = [...new Set([...previous.account_ids, ...item.account_ids])]
      previous.account_names = [...new Set([...(previous.account_names || []), ...(item.account_names || [])])]
      previous.usable = previous.usable !== false && item.usable !== false
      if (item.status && item.status !== 'ACTIVE') previous.status = item.status
      previous.last_sync_error = previous.last_sync_error || item.last_sync_error
      previous.last_synced_at = [previous.last_synced_at, item.last_synced_at].filter((value): value is string => !!value).sort()[0] || null
    }
  }
  return { ...responses[0], data: {
    items: [...merged.values()], account_count: ids.length, source: 'LOCAL_SNAPSHOT',
    synced_at: responses.map(response => response.data.synced_at).filter((value): value is string => !!value).sort().at(-1) || null,
    unsynced_account_ids: [...new Set(responses.flatMap(response => response.data.unsynced_account_ids))],
  } }
}

export const metaTrackingAssetsApi = {
  list: listTrackingAssets,
  health: () => request.get<{ items: TrackingAssetHealthItem[]; summary: Record<string, number> }>('/api/v1/meta-tracking-assets/health'),
  sync: (accountPk: string) => request.post<{ status: string; task_id?: string; account_pk: string }>(`/api/v1/meta-tracking-assets/${accountPk}/sync`),
}

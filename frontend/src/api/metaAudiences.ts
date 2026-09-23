import request from '@/utils/request'

export interface MetaAudienceAsset {
  id: string
  ad_account_id: string
  meta_ad_account_id: string
  meta_audience_id: string
  name: string
  subtype?: string | null
  delivery_status?: string | null
  sharing_status?: string | null
  source: string
  is_required_exclusion: boolean
  last_synced_at?: string | null
  last_seen_at?: string | null
  sync_status?: string | null
  meta_time_updated?: string | null
  last_sync_error?: string | null
  policy_reason_code?: string | null
  policy_reason_note?: string | null
  policy_version?: number | null
  policy_effective_from?: string | null
  policy_effective_until?: string | null
}

export const metaAudiencesApi = {
  list: (accountPk: string, params?: { q?: string; required_only?: boolean }) =>
    request.get<MetaAudienceAsset[]>('/api/v1/meta-audiences', { params: { account_pk: accountPk, ...params } }),
  sync: (accountPk: string) => request.post<{ status: string; task_id: string; account_pk: string; account_id: string }>(`/api/v1/meta-audiences/${accountPk}/sync`),
  taskStatus: (taskId: string) => request.get<{ task_id: string; state: string; result?: Record<string, any>; error?: string }>(`/api/v1/tasks/${taskId}`),
  setRequiredExclusions: (accountPk: string, payload: { audience_ids: string[]; reason_code?: string; reason_note?: string; effective_from?: string; effective_until?: string }) =>
    request.put(`/api/v1/meta-audiences/${accountPk}/required-exclusions`, payload),
}

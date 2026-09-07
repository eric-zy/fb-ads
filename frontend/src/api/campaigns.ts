import request from '@/utils/request'
export interface MetaCampaign { id: string; ad_account_id: string; meta_campaign_id: string; name: string; status: string; meta_status?: string; objective?: string; updated_at?: string }
export interface MetaAdSet { id: string; campaign_id: string; meta_adset_id: string; name: string; status: string; optimization_goal?: string; daily_budget?: number }
export interface MetaAd { id: string; adset_id: string; meta_ad_id: string; name: string; status: string; effective_status?: string }
export interface AsyncActionResult { job_id?: string; task_ids?: string[]; account_ids?: string[]; status: string }
export interface AsyncTaskStatus { task_id: string; state: string; result?: Record<string, any>; error?: string }
export const campaignsApi = {
  list: (params?: { ad_account_id?: string; status?: string }) => request.get<MetaCampaign[]>('/api/v1/campaigns', { params }),
  adsets: (id: string) => request.get<MetaAdSet[]>('/api/v1/campaigns/' + id + '/adsets'),
  ads: (id: string) => request.get<MetaAd[]>('/api/v1/adsets/' + id + '/ads'),
  sync: (ids?: string[]) => request.post<AsyncActionResult>('/api/v1/campaigns/actions', { action: 'SYNC', ad_account_ids: ids }),
  action: (data: { action: string; ids: string[]; budget?: number }) => request.post<AsyncActionResult>('/api/v1/campaigns/actions', data),
  taskStatus: (id: string) => request.get<AsyncTaskStatus>('/api/v1/tasks/' + id),
  taskRecords: (limit = 50) => request.get('/api/v1/tasks', { params: { limit } }),
}

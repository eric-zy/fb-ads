import request from '@/utils/request'
export interface MetaCampaign { id: string; ad_account_id: string; account_name?: string; meta_campaign_id: string; name: string; status: string; meta_status?: string; desired_status?: string; last_error?: string | null; deleted_at?: string | null; objective?: string; template_name?: string; updated_at?: string; publisher?: { id: string; username: string; email?: string | null } | null }
export interface MetaAdSet { id: string; campaign_id: string; meta_adset_id: string; name: string; status: string; meta_status?: string; desired_status?: string; last_error?: string | null; deleted_at?: string | null; optimization_goal?: string; daily_budget?: number }
export interface MetaAd { id: string; adset_id: string; meta_ad_id: string; name: string; status: string; meta_status?: string; desired_status?: string; last_error?: string | null; deleted_at?: string | null; effective_status?: string }
export interface AsyncActionResult { job_id?: string; task_ids?: string[]; action_ids?: string[]; account_ids?: string[]; status: string }
export interface AsyncTaskStatus { task_id: string; state: string; result?: Record<string, any>; error?: string }
export interface DeliveryAction { id: string; object_type: string; object_id: string; account_id: string; action: string; status: string; desired_status?: string; remote_status?: string; task_id?: string; error_message?: string; created_at?: string; finished_at?: string }
export interface SyncAlert { id: string; ad_account_id?: string; alert_type: string; title: string; message: string; is_resolved: boolean; created_at?: string }
export interface DeliveryObjectDetail { object_type: string; object: MetaCampaign | MetaAdSet | MetaAd; account?: Record<string, any> | null; ancestors: Record<string, any>; children: any[]; recent_actions: DeliveryAction[] }
export const campaignsApi = {
  list: (params?: { ad_account_id?: string; status?: string; keyword?: string }) => request.get<MetaCampaign[]>('/api/v1/campaigns', { params }),
  detail: (id: string) => request.get<any>('/api/v1/campaigns/' + id + '/detail'),
  objectDetail: (objectType: string, id: string) => request.get<DeliveryObjectDetail>('/api/v1/delivery-objects/' + objectType + '/' + id),
  adsets: (id: string, status?: string) => request.get<MetaAdSet[]>('/api/v1/campaigns/' + id + '/adsets', { params: { status } }),
  ads: (id: string, status?: string) => request.get<MetaAd[]>('/api/v1/adsets/' + id + '/ads', { params: { status } }),
  sync: (ids?: string[], objectType = 'CAMPAIGN') => request.post<AsyncActionResult & { object_type?: string; object_ids?: string[] }>('/api/v1/campaigns/actions', { action: 'SYNC', ids, object_type: objectType }),
  action: (data: { action: string; ids: string[]; budget?: number; idempotency_key?: string }) => request.post<AsyncActionResult>('/api/v1/campaigns/actions', data),
  taskStatus: (id: string) => request.get<AsyncTaskStatus>('/api/v1/tasks/' + id),
  taskRecords: (limit = 50) => request.get('/api/v1/tasks', { params: { limit } }),
  deliveryActions: (limit = 50, status?: string) => request.get<DeliveryAction[]>('/api/v1/delivery-actions', { params: { limit, status } }),
  retryDeliveryAction: (id: string) => request.post<{ status: string; action_id: string; task_id: string }>('/api/v1/delivery-actions/' + id + '/retry'),
  alerts: (limit = 30) => request.get<SyncAlert[]>('/api/v1/sync-alerts', { params: { limit } }),
  resolveAlert: (id: string) => request.post<SyncAlert>('/api/v1/sync-alerts/' + id + '/resolve'),
}

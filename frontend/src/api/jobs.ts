// Job Center 接口封装
// 批量投放全部异步化：提交后立刻返回 job_id，前端轮询进度。
import request from '@/utils/request'

export interface CampaignJobItem {
  id: string
  job_id: string
  ad_account_id: string
  access_business_id?: string | null
  status: string
  meta_campaign_id: string | null
  adset_ids: string[] | null
  ad_ids: string[] | null
  error_code: string | null
  error_message: string | null
  error_category: string | null
  retry_count: number
  connector_task_id?: string | null
  response_payload?: { cleanup_failed?: boolean; cleanup_object_ids?: string[]; cleanup_status?: string; failure_stage?: string; created_objects?: Record<string, any>; retry_mode?: string; meta_status?: string; review_status?: string; effective_status?: string; error_code?: string; error_message?: string; reconcile?: DeliveryReconcileResult; reconcile_confirmation?: DeliveryReconcileConfirmationResult; failure?: { category?: string; code?: string | null; message?: string }; [key: string]: any } | null
  created_at: string | null
  updated_at: string | null
}

export interface CampaignJob {
  id: string
  template_id: string | null
  action_type: string
  status: string
  total_accounts: number
  success_count: number
  failed_count: number
  params: Record<string, any> | null
  created_by: string | null
  preview_id?: string | null
  submitted_by?: string | null
  submitted_at?: string | null
  idempotency_key?: string | null
  publisher?: { id: string; username: string; email?: string | null } | null
  error_message: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  parent_job_id?: string | null
  revision_no?: number
  edit_mode?: string | null
  items?: CampaignJobItem[]
}

export interface DeliveryReconcileCandidate {
  id?: string
  name?: string
  created_time?: string
  status?: string
  effective_status?: string
}

export interface DeliveryReconcileItem {
  group: string
  client_key?: string | null
  name?: string | null
  parent_id?: string | null
  submitted_at?: string | null
  can_auto_reconcile: boolean
  candidates: DeliveryReconcileCandidate[]
}

export interface DeliveryReconcileResult {
  status: string
  connector_task_id?: string
  campaign_id?: string | null
  pending: DeliveryReconcileItem[]
  message?: string
}

export interface DeliveryReconcileConfirmationResult {
  status: string
  connector_task_id?: string
  confirmed: string[]
  remaining_pending: DeliveryReconcileItem[]
  message?: string
}

export interface JobSubmitResult {
  job_id: string
  status: string
  template_id?: string | null
  source?: 'TEMPLATE' | 'DIRECT' | string
  total_accounts: number
  preview_id?: string | null
}
export interface CampaignPreflightResult {
  passed: boolean
  template_id?: string | null
  source?: 'TEMPLATE' | 'DIRECT' | string
  template?: { id: string; name: string; objective?: string; creative_count: number }
  errors: Array<{ code: string; message: string }>
  warnings: Array<{ code: string; message: string; items?: any[] }>
  accounts: Array<{ account_id: string; status: string; reason?: string }>
  ready_account_ids: string[]
  preview_id?: string | null
  snapshot_hash?: string | null
  expires_at?: string | null
}

export interface CreateCampaignPayload {
  template_id?: string
  inline_config?: Record<string, any>
  save_as_template?: boolean
  template_name?: string
  source?: 'TEMPLATE' | 'DIRECT'
  ad_account_ids: string[]
  budget_override?: number
  status?: string
  sinan_promotion_id?: string
  access_business_ids?: Record<string, string>
  ad_group_mode?: 'NEW' | 'EXISTING' | 'COPY'
  ad_group_selections?: Record<string, { mode?: 'NEW' | 'EXISTING' | 'COPY'; ad_group_id: string; ad_group_external_id?: string }>
  preview_id?: string
  snapshot_hash?: string
  idempotency_key?: string
  source_job_id?: string
  revision_id?: string
}

export interface JobEditSource {
  source_job_id: string
  revision_no: number
  source: 'TEMPLATE' | 'DIRECT' | string
  template_id?: string | null
  inline_config?: Record<string, any> | null
  budget_override?: number | null
  status?: string
  sinan_promotion_id?: string | null
  access_business_ids?: Record<string, string>
  ad_group_mode?: 'NEW' | 'EXISTING' | 'COPY' | string
  ad_group_selections?: Record<string, any>
  ad_account_ids: string[]
  failed_account_ids: string[]
  revision_id?: string | null
  errors: Array<{ account_id: string; code?: string | null; message?: string | null; category?: string | null }>
}

export interface CampaignJobRevision {
  id: string
  base_job_id: string
  published_job_id?: string | null
  template_id?: string | null
  version: number
  status: string
  source?: string | null
  account_ids: string[]
  snapshot?: Record<string, any> | null
  diff: Array<{ path: string; before: any; after: any }>
  validation_result?: Record<string, any> | null
  edit_reason?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface TemplateActionPayload {
  template_id: string
  ad_account_ids?: string[]
}

export interface ScheduleCampaignPayload {
  template_id: string
  ad_account_ids: string[]
  budget_override?: number
  status?: string
  /** 计划执行时间，ISO 8601（如 2026-08-30T10:00:00Z 或 2026-08-30T18:00:00+08:00） */
  scheduled_at: string
  access_business_ids?: Record<string, string>
  preview_id?: string
  snapshot_hash?: string
  idempotency_key?: string
}

export const jobsApi = {
  preflightCampaign: (data: CreateCampaignPayload) =>
    request.post<CampaignPreflightResult>('/api/v1/jobs/campaign-preflight', data),
  createCampaign: (data: CreateCampaignPayload) =>
    request.post<JobSubmitResult>('/api/v1/jobs/campaign-create', data),

  /** 定时投放：Job 先以 QUEUED 落库，由 Celery 在指定时间触发 */
  scheduleCampaign: (data: ScheduleCampaignPayload) =>
    request.post<JobSubmitResult>('/api/v1/jobs/schedule', data),

  /** 待执行的定时任务列表（按计划执行时间升序） */
  listScheduled: (limit?: number) =>
    request.get<CampaignJob[]>('/api/v1/jobs/scheduled', { params: { limit } }),

  /** 把定时任务提前为立即执行 */
  dispatchNow: (id: string) =>
    request.post<CampaignJob>(`/api/v1/jobs/${id}/dispatch-now`),

  updateBudget: (data: TemplateActionPayload & { budget_override: number }) =>
    request.post<JobSubmitResult>('/api/v1/jobs/budget-update', data),

  pause: (data: TemplateActionPayload) =>
    request.post<JobSubmitResult>('/api/v1/jobs/pause', data),

  enable: (data: TemplateActionPayload) =>
    request.post<JobSubmitResult>('/api/v1/jobs/enable', data),

  list: (params?: { status?: string; limit?: number }) =>
    request.get<CampaignJob[]>('/api/v1/jobs', { params }),

  get: (id: string) => request.get<CampaignJob>(`/api/v1/jobs/${id}`),
  getEditSource: (id: string) => request.get<JobEditSource>(`/api/v1/jobs/${id}/edit-source`),
  listRevisions: (id: string) => request.get<CampaignJobRevision[]>(`/api/v1/jobs/${id}/revisions`),
  createRevision: (id: string, data?: { account_ids?: string[]; edit_reason?: string }) =>
    request.post<CampaignJobRevision>(`/api/v1/jobs/${id}/revisions`, data || {}),
  getRevision: (id: string) => request.get<CampaignJobRevision>(`/api/v1/jobs/revisions/${id}`),
  updateRevision: (id: string, data: { snapshot: Record<string, any>; account_ids?: string[]; edit_reason?: string }) =>
    request.patch<CampaignJobRevision>(`/api/v1/jobs/revisions/${id}`, data),
  discardRevision: (id: string) =>
    request.post<CampaignJobRevision>(`/api/v1/jobs/revisions/${id}/discard`),

  retry: (id: string, data?: { item_ids?: string[]; mode?: 'CONTINUE' }) =>
    request.post(`/api/v1/jobs/${id}/retry`, data || {}),
  continueItem: (jobId: string, itemId: string) =>
    request.post(`/api/v1/jobs/${jobId}/items/${itemId}/continue`),
  reconcileItem: (jobId: string, itemId: string) =>
    request.post<{ job_id: string; item_id: string; result: DeliveryReconcileResult }>(`/api/v1/jobs/${jobId}/items/${itemId}/reconcile`),
  confirmReconcileItem: (jobId: string, itemId: string, confirmations: Array<{ group: string; client_key?: string | null; object_id: string }>) =>
    request.post<{ job_id: string; item_id: string; result: DeliveryReconcileConfirmationResult }>(`/api/v1/jobs/${jobId}/items/${itemId}/reconcile/confirm`, { confirmations }),
  cleanupItem: (jobId: string, itemId: string) =>
    request.post(`/api/v1/jobs/${jobId}/items/${itemId}/cleanup`),

  cancel: (id: string) => request.post(`/api/v1/jobs/${id}/cancel`),
}

// 任务是否已到达终态（无需继续轮询）
export const FINAL_STATUSES = ['SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED']

export const isFinalStatus = (status: string) => FINAL_STATUSES.includes(status)

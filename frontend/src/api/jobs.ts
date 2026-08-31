// Job Center 接口封装
// 批量投放全部异步化：提交后立刻返回 job_id，前端轮询进度。
import request from '@/utils/request'

export interface CampaignJobItem {
  id: string
  job_id: string
  ad_account_id: string
  status: string
  meta_campaign_id: string | null
  adset_ids: string[] | null
  ad_ids: string[] | null
  error_code: string | null
  error_message: string | null
  error_category: string | null
  retry_count: number
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
  error_message: string | null
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  items?: CampaignJobItem[]
}

export interface JobSubmitResult {
  job_id: string
  status: string
  total_accounts: number
}

export interface CreateCampaignPayload {
  template_id: string
  ad_account_ids: string[]
  budget_override?: number
  status?: string
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
}

export const jobsApi = {
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

  retry: (id: string) => request.post(`/api/v1/jobs/${id}/retry`),

  cancel: (id: string) => request.post(`/api/v1/jobs/${id}/cancel`),
}

// 任务是否已到达终态（无需继续轮询）
export const FINAL_STATUSES = ['SUCCESS', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED']

export const isFinalStatus = (status: string) => FINAL_STATUSES.includes(status)

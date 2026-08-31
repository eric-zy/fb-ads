// 投放模板接口封装
// Campaign Template 是系统最核心的业务对象：配置一次，批量部署到多个广告账户。
import request from '@/utils/request'

export interface CampaignTemplate {
  id: string
  name: string
  objective: string | null
  buying_type: string | null
  budget_type: string | null
  daily_budget: number | null
  lifetime_budget: number | null
  bid_strategy: string | null
  optimization_goal: string | null
  billing_event: string | null
  targeting_json: Record<string, any> | null
  placement_json: Record<string, any> | null
  creative_config_json: Record<string, any> | null
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface TemplatePayload {
  name: string
  objective?: string
  buying_type?: string
  special_ad_categories?: string[]
  budget_type?: string
  daily_budget?: number
  lifetime_budget?: number
  bid_strategy?: string
  optimization_goal?: string
  billing_event?: string
  targeting_json?: Record<string, any>
  placement_json?: Record<string, any>
  creative_config_json?: Record<string, any>
}

export const templatesApi = {
  list: (status?: string) =>
    request.get<CampaignTemplate[]>('/api/v1/templates', { params: { status } }),
  get: (id: string) => request.get<CampaignTemplate>(`/api/v1/templates/${id}`),
  create: (data: TemplatePayload) =>
    request.post<CampaignTemplate>('/api/v1/templates', data),
  update: (id: string, data: Partial<TemplatePayload>) =>
    request.patch<CampaignTemplate>(`/api/v1/templates/${id}`, data),
  clone: (id: string) =>
    request.post<CampaignTemplate>(`/api/v1/templates/${id}/clone`),
  remove: (id: string) => request.delete(`/api/v1/templates/${id}`),
}

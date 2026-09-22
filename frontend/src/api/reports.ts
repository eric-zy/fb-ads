import request from '@/utils/request'
import type { AxiosRequestConfig } from 'axios'

export const reportsApi = {
  accountOverview: (params?: { start_date?: string; end_date?: string }) =>
    request.get('/api/v1/reports/account-overview', { params }),
  breakdown: (params: { dimension: string; days: number; parent_id?: string }) =>
    request.get('/api/v1/reports/breakdown', { params }),
  trend: (params: { dimension: string; days: number; entity_id?: string }) =>
    request.get('/api/v1/reports/trend', { params }),
  sync: (params?: { account_id?: string; days?: number }) =>
    request.post('/api/v1/reports/sync', undefined, { params }),
  taskStatus: (id: string) => request.get<{ task_id: string; state: string; result?: { status?: string; error_count?: number }; error?: string }>('/api/v1/tasks/' + id),
}

export interface WorkbenchCurrencyTotal {
  currency: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  conversion_value: number
  ctr: number | null
  conversion_rate: number | null
  cpc: number | null
  cpm: number | null
  cpa: number | null
  roas: number | null
}

export interface WorkbenchSummary {
  scope: {
    tenant_id?: string | null
    role: string
    selected_account_id?: string | null
    account_count: number
    accounts: Array<{
      id: string
      name: string
      currency: string
      system_status: string
      freshness: { status: 'FRESH' | 'STALE' | 'NEVER'; latest_synced_at?: string | null; age_hours?: number | null }
    }>
  }
  range: { start_date: string; end_date: string }
  freshness: {
    status: 'FRESH' | 'STALE' | 'NEVER'
    latest_synced_at?: string | null
    age_hours?: number | null
    account_count: number
    stale_account_count: number
    never_synced_account_count: number
  }
  kpis: {
    active_campaigns: number
    total_campaigns: number
    average_ctr: number
    pending_jobs: number
    failed_jobs: number
    open_alerts: number
    status_drift: number
    highest_risk_score: number
  }
  delivery_health: { status_counts: Record<string, number>; status_drift: number }
  job_status: Record<string, number>
  currency_totals: WorkbenchCurrencyTotal[]
  trend: Array<{
    date: string
    currency: string
    spend: number
    impressions: number
    clicks: number
    conversions: number
    conversion_value: number
    ctr: number | null
    conversion_rate: number | null
    cpc: number | null
    cpm: number | null
    cpa: number | null
    roas: number | null
  }>
  recent_tasks: Array<{ id: string; action_type: string; status: string; total_accounts: number; success_count: number; failed_count: number; created_by?: string; created_at?: string | null }>
  alerts: Array<{ id: string; ad_account_id?: string; alert_type: string; title: string; message: string; created_at?: string }>
}

export interface WorkbenchNotifications {
  alerts: number
  failed_jobs: number
  total: number
}

export const workbenchApi = {
  summary: (
    params?: { account_id?: string; start_date?: string; end_date?: string },
    config?: Pick<AxiosRequestConfig, 'signal' | 'skipErrorMessage'>,
  ) => request.get<WorkbenchSummary>('/api/v1/workbench/summary', { params, ...config }),
  notifications: (
    params?: { account_id?: string },
    config?: Pick<AxiosRequestConfig, 'signal' | 'skipErrorMessage'>,
  ) => request.get<WorkbenchNotifications>('/api/v1/workbench/notifications', { params, ...config }),
}

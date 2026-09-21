import request from '@/utils/request'

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type RiskFrequencyStatus = 'safe' | 'warning' | 'danger' | 'unknown'

export interface RiskFrequencyReport {
  frequency_status: RiskFrequencyStatus
  count: number
  hours: number
  threshold_warning: number
  threshold_danger: number
}

export interface RateLimitHourStatus {
  usage_ratio: number
  count: number
  limit: number
}

export interface RiskEventItem {
  id: string
  source?: 'RISK_EVENT' | 'SYNC_ALERT'
  ad_account_id?: string | null
  event_type: string | null
  risk_level: RiskLevel | null
  risk_score: number | null
  title: string
  description: string | null
  related_campaign_id: string | null
  related_ad_id: string | null
  is_resolved: boolean
  resolution: string | null
  resolved_at: string | null
  auto_action_taken: string | null
  requires_manual_review: boolean
  created_at: string | null
  updated_at: string | null
  notification_status?: 'PENDING' | 'SENT' | 'FAILED' | 'SKIPPED' | null
  notification_attempts?: number
  notification_sent_at?: string | null
  notification_error?: string | null
}

export interface RiskRuleItem {
  id: string
  name: string
  description: string | null
  rule_type: string
  is_active: boolean
  is_builtin: boolean
  scope: Record<string, unknown>
  conditions: Array<Record<string, unknown>>
  logic: 'AND' | 'OR'
  min_spend: number
  min_runtime: number
  cooldown_seconds: number
  max_actions_per_run: number
  dry_run: boolean
  whitelist: unknown[]
  priority: number
  version: number
  action_on_trigger?: string | null
  alert_channels?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface RiskPage<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export const riskControlApi = {
  overview: () => request.get('/api/v1/risk-control/overview'),
  accounts: (params?: Record<string, unknown>) => request.get('/api/v1/risk-control/accounts', { params }),
  allEvents: (params?: Record<string, unknown>) => request.get<RiskPage<RiskEventItem>>('/api/v1/risk-control/events', { params }),
  event: (eventId: string) => request.get<RiskEventItem>(`/api/v1/risk-control/events/${eventId}`),
  resolveEvent: (eventId: string, resolution: string) => request.post(
    `/api/v1/risk-control/events/${eventId}/resolve`,
    { resolution },
  ),
  rules: (params?: Record<string, unknown>) => request.get<{ items: RiskRuleItem[] }>('/api/v1/risk-control/rules', { params }),
  createRule: (payload: Partial<RiskRuleItem>) => request.post('/api/v1/risk-control/rules', payload),
  updateRule: (ruleId: string, payload: Partial<RiskRuleItem>) => request.put(`/api/v1/risk-control/rules/${ruleId}`, payload),
  toggleRule: (ruleId: string, isActive: boolean) => request.post(`/api/v1/risk-control/rules/${ruleId}/toggle`, { is_active: isActive }),
  dryRunRule: (ruleId: string, accountIds: string[] = []) => request.post(`/api/v1/risk-control/rules/${ruleId}/dry-run`, { account_ids: accountIds }),
  executions: (params?: Record<string, unknown>) => request.get<RiskPage<any>>('/api/v1/risk-control/executions', { params }),
  execution: (executionId: string) => request.get(`/api/v1/risk-control/executions/${executionId}`),
  recheckAccount: (accountId: string) => request.post(`/api/v1/risk-control/accounts/${accountId}/recheck`),
  retryExecution: (executionId: string) => request.post(`/api/v1/risk-control/executions/${executionId}/retry`),
  accountHealth: (accountId: string) => request.get(`/api/v1/accounts/${accountId}/account-health-check`),
  fraudScore: (accountId: string) => request.get(`/api/v1/accounts/${accountId}/fraud-score`),
  events: (accountId: string) => request.get<{ events: RiskEventItem[] }>(`/api/v1/accounts/${accountId}/risk-events`),
  recommendations: (accountId: string) => request.get(`/api/v1/accounts/${accountId}/safety-recommendations`),
  frequency: (accountId: string, hours = 24) => request.get<{ frequency_report: RiskFrequencyReport }>(
    `/api/v1/accounts/${accountId}/publish-frequency-check`,
    { params: { hours } },
  ),
  rateLimit: (accountId: string) => request.get<{ rate_limits: { hour: RateLimitHourStatus } }>(
    `/api/v1/accounts/${accountId}/rate-limit-status`,
  ),
}

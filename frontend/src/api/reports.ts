import request from '@/utils/request'

export const reportsApi = {
  accountOverview: (params?: { start_date?: string; end_date?: string }) =>
    request.get('/api/v1/reports/account-overview', { params }),
  breakdown: (params: { dimension: string; days: number; parent_id?: string }) =>
    request.get('/api/v1/reports/breakdown', { params }),
  trend: (params: { dimension: string; days: number; entity_id?: string }) =>
    request.get('/api/v1/reports/trend', { params }),
  sync: (params?: { account_id?: string; days?: number }) =>
    request.post('/api/v1/reports/sync', undefined, { params }),
}

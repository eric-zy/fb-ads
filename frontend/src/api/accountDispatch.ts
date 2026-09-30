import request from '@/utils/request'

export const accountDispatchApi = {
  pool: () => request.get('/api/v1/account-pool'),
  rules: () => request.get('/api/v1/account-dispatch/rules'),
  createRule: (data: any) => request.post('/api/v1/account-dispatch/rules', data),
  dispatch: (id: string, lease_token: string) => request.post(`/api/v1/account-dispatch/accounts/${id}/dispatch`, { lease_token }),
  dispatchUnassigned: (operation_leases: Record<string, string>) => request.post('/api/v1/account-dispatch/dispatch-unassigned', { operation_leases }),
  release: (id: string, lease_token: string) => request.post(`/api/v1/account-dispatch/accounts/${id}/release`, { lease_token }),
}

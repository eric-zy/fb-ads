import request from '@/utils/request'

export const accountDispatchApi = {
  pool: () => request.get('/api/v1/account-pool'),
  rules: () => request.get('/api/v1/account-dispatch/rules'),
  createRule: (data: any) => request.post('/api/v1/account-dispatch/rules', data),
  dispatchUnassigned: () => request.post('/api/v1/account-dispatch/dispatch-unassigned'),
  release: (id: string) => request.post(`/api/v1/account-dispatch/accounts/${id}/release`),
}

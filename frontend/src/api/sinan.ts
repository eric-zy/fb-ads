import request from '@/utils/request'

export interface SinanStatus { configured: boolean; verified: boolean; account_masked?: string; app_id?: string; last_verified_at?: string | null; last_error?: string | null }
export const sinanApi = {
  status: () => request.get<SinanStatus>('/api/v1/integrations/sinan/status'),
  save: (data: { base_url: string; app_id: string; account: string; password: string; menu_id: string }) => request.post('/api/v1/integrations/sinan/config', data),
  testLogin: () => request.post('/api/v1/integrations/sinan/test-login'),
}

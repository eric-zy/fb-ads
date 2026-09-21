import request from '@/utils/request'

export interface MetaLanguageOption {
  id: string
  code: string
  name: string
  name_en: string
}

export const metaTargetingApi = {
  languages: (q = '') => request.get<{ items: MetaLanguageOption[] }>('/api/v1/meta-targeting/languages', { params: { q, limit: 50 } }),
  validate: (targeting: Record<string, any>) => request.post('/api/v1/meta-targeting/validate', { targeting }),
}

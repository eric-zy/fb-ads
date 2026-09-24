import request from '@/utils/request'

export interface MetaLanguageOption {
  id: string
  code: string
  name: string
  name_en: string
}

export interface MetaTargetingOption {
  id: string
  key?: string
  name: string
  search_type?: string
  [key: string]: any
}

export const metaTargetingApi = {
  languages: (q = '') => request.get<{ items: MetaLanguageOption[] }>('/api/v1/meta-targeting/languages', { params: { q, limit: 50 } }),
  search: (params: { account_pk: string; type: string; q?: string; locale?: string; country_code?: string; location_type?: string; limit?: number }) =>
    request.get<{ items: MetaTargetingOption[]; type: string }>('/api/v1/meta-targeting/search', { params }),
  validate: (targeting: Record<string, any>) => request.post('/api/v1/meta-targeting/validate', { targeting }),
}

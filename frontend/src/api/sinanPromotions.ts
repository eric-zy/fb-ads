import request from '@/utils/request'
export interface SinanPromotion { promotion_id: string; promotion_name: string; drama_id?: string; drama_title?: string; chapter_id?: string; chapter_title?: string; landing_url?: string; ad_group?: string; [key: string]: any }
export const sinanPromotionsApi = {
  list: (page=1, page_size=20) => request.post<any>('/api/v1/integrations/sinan/promotions/query', { page, page_size }),
  detail: (id: string) => request.get<SinanPromotion>('/api/v1/integrations/sinan/promotions/' + id),
  contentList: (data: any) => request.post('/api/v1/integrations/sinan/content/search', data),
}

// 素材库接口封装
import request from '@/utils/request'
import type { AxiosProgressEvent } from 'axios'

export interface MediaItem {
  id: string
  name: string
  asset_type: 'image' | 'video'
  meta_account_id: string | null
  account_id: string | null
  url: string | null
  fb_hash: string | null
  fb_video_id: string | null
  width: number | null
  height: number | null
  size: number | null
  mime_type: string | null
  duration: number | null
  status: string
  error: string | null
  created_at: string | null
}

export const mediaApi = {
  list: (params?: { meta_account_id?: string; account_id?: string; asset_type?: string }) =>
    request.get<MediaItem[]>('/api/v1/media', { params }),
  upload: (
    file: File,
    extra?: { meta_account_id?: string; account_id?: string },
    onProgress?: (e: AxiosProgressEvent) => void
  ) => {
    const form = new FormData()
    form.append('file', file)
    if (extra?.meta_account_id) form.append('meta_account_id', extra.meta_account_id)
    if (extra?.account_id) form.append('account_id', extra.account_id)
    return request.post<MediaItem>('/api/v1/media/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress,
    })
  },
  remove: (id: string) => request.delete('/api/v1/media/' + id),
}

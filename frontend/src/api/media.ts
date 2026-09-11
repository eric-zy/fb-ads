// 素材库接口封装
import request from '@/utils/request'
import type { AxiosProgressEvent } from 'axios'

export interface MediaItem {
  id: string
  name: string
  created_by?: string | null
  visibility?: 'PRIVATE' | 'ACCOUNT' | 'TENANT' | string
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
  retry_count?: number
  created_at: string | null
  group_id?: string | null
  tag_ids?: string[]
}

export interface CreativeAssetGroup {
  id: string
  name: string
  description?: string | null
  owner_id?: string | null
  visibility: 'PRIVATE' | 'TENANT' | string
}
export interface CreativeAssetTag { id: string; name: string; color?: string | null }

export interface MetaAssetBinding {
  id: string
  asset_id: string
  ad_account_id: string
  account_name?: string | null
  meta_asset_id: string | null
  meta_asset_type: string
  status: 'PENDING' | 'UPLOADING' | 'PROCESSING' | 'READY' | 'FAILED' | 'EXPIRED' | string
  error_message: string | null
  uploaded_at: string | null
  last_verified_at: string | null
}

export const mediaApi = {
  list: (params?: { meta_account_id?: string; account_id?: string; asset_type?: string; group_id?: string; tag_id?: string }) =>
    request.get<MediaItem[]>('/api/v1/media', { params }),
  upload: (
    file: File,
    extra?: { meta_account_id?: string; account_id?: string; group_id?: string },
    onProgress?: (e: AxiosProgressEvent) => void
  ) => {
    const form = new FormData()
    form.append('file', file)
    if (extra?.meta_account_id) form.append('meta_account_id', extra.meta_account_id)
    if (extra?.account_id) form.append('account_id', extra.account_id)
    if (extra?.group_id) form.append('group_id', extra.group_id)
    return request.post<MediaItem>('/api/v1/media/upload', form, {
      // 不要手动设置 Content-Type；浏览器需要自动补 multipart boundary。
      onUploadProgress: onProgress,
    })
  },
  groups: {
    list: () => request.get<CreativeAssetGroup[]>('/api/v1/creative-asset-groups'),
    create: (data: { name: string; description?: string; visibility?: string }) =>
      request.post<CreativeAssetGroup>('/api/v1/creative-asset-groups', data),
    moveAssets: (asset_ids: string[], group_id?: string) =>
      request.post('/api/v1/creative-asset-groups/move-assets', { asset_ids, group_id: group_id || null }),
    members: (groupId: string) => request.get<{ group_id: string; user_id: string; can_edit: boolean }[]>(`/api/v1/creative-asset-groups/${groupId}/members`),
    upsertMember: (groupId: string, user_id: string, can_edit: boolean) =>
      request.put(`/api/v1/creative-asset-groups/${groupId}/members`, { user_id, can_edit }),
    removeMember: (groupId: string, userId: string) =>
      request.delete(`/api/v1/creative-asset-groups/${groupId}/members/${userId}`),
  },
  tags: {
    list: () => request.get<CreativeAssetTag[]>('/api/v1/creative-asset-tags'),
    create: (data: { name: string; color?: string }) => request.post<CreativeAssetTag>('/api/v1/creative-asset-tags', data),
    setAssetTags: (assetId: string, tag_ids: string[]) => request.put(`/api/v1/creative-asset-tags/assets/${assetId}`, { tag_ids }),
  },
  remove: (id: string) => request.delete('/api/v1/media/' + id),
  refreshMetadata: (id: string) => request.post<MediaItem>(`/api/v1/media/${id}/refresh-metadata`),
  bindings: (assetId: string) =>
    request.get<MetaAssetBinding[]>(`/api/v1/media/${assetId}/bindings`),
  prepare: (assetId: string, adAccountIds: string[]) =>
    request.post<{ asset_id: string; status: string; bindings: MetaAssetBinding[] }>(
      `/api/v1/media/${assetId}/prepare`,
      { ad_account_ids: adAccountIds },
    ),
  syncToAccounts: (assetId: string, adAccountIds: string[]) =>
    request.post<{ asset_id: string; status: string; bindings: MetaAssetBinding[] }>(
      `/api/v1/media/${assetId}/prepare`, { ad_account_ids: adAccountIds },
    ),
  retryBinding: (assetId: string, bindingId: string) =>
    request.post<{ status: string; binding_id: string; task_id: string }>(
      `/api/v1/media/${assetId}/bindings/${bindingId}/retry`,
    ),
}

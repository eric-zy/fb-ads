// 素材库接口封装
import request from '@/utils/request'
import axios from 'axios'
import type { AxiosProgressEvent } from 'axios'
import { md5ArrayBuffer } from '@/utils/md5'

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
  original_name?: string | null
  object_key?: string | null
  thumbnail_key?: string | null
  cover_key?: string | null
  storage_status?: string | null
  processing_status?: string | null
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
  connector_task_id?: string | null
  meta_asset_type: string
  status: 'PENDING' | 'UPLOADING' | 'PROCESSING' | 'READY' | 'FAILED' | 'EXPIRED' | string
  error_message: string | null
  uploaded_at: string | null
  last_verified_at: string | null
}

export interface UploadSessionResponse {
  duplicate: boolean
  asset_id: string
  asset?: MediaItem
  upload_session_id?: string
  object_key?: string
  upload?: { url: string; method: 'PUT'; headers?: Record<string, string> }
  binding_id?: string
  binding?: MetaAssetBinding
  task_id?: string | null
}

export interface UploadResult {
  data: MediaItem
  duplicate?: boolean
  binding_id?: string
  task_id?: string | null
}

export const mediaApi = {
  get: (id: string) => request.get<MediaItem>(`/api/v1/media/${id}`),
  getDownloadUrl: (id: string, kind: 'original' | 'thumbnail' | 'cover' = 'original') =>
    request.get<{ asset_id: string; url: string; expires_in: number }>(
      `/api/v1/media/${id}/download-url`,
      { params: { kind }, skipErrorMessage: true },
    ),
  list: (params?: { meta_account_id?: string; account_id?: string; asset_type?: string; group_id?: string; tag_id?: string }) =>
    request.get<MediaItem[]>('/api/v1/media', { params }),
  upload: (
    file: File,
    extra?: { meta_account_id?: string; account_id?: string; group_id?: string },
    onProgress?: (e: AxiosProgressEvent) => void
  ): Promise<UploadResult> => {
    return file.arrayBuffer().then(async (buffer) => {
      const hashBuffer = await crypto.subtle.digest('SHA-256', buffer)
      const sha256 = Array.from(new Uint8Array(hashBuffer)).map((value) => value.toString(16).padStart(2, '0')).join('')
      const md5 = md5ArrayBuffer(buffer)
      const assetType = file.type.startsWith('video/') ? 'video' : 'image'
      const session = await request.post<UploadSessionResponse>('/api/v1/media/upload-sessions', {
        name: file.name,
        asset_type: assetType,
        mime_type: file.type,
        size: file.size,
        md5,
        sha256,
        account_id: extra?.account_id,
        meta_account_id: extra?.meta_account_id,
        group_id: extra?.group_id,
      })
      if (session.data.duplicate) {
        if (!session.data.asset) throw new Error('重复素材响应缺少素材信息')
        return {
          data: session.data.asset,
          duplicate: true,
          binding_id: session.data.binding_id,
          task_id: session.data.task_id,
        }
      }
      const upload = session.data.upload
      if (!upload?.url) throw new Error('OSS 上传签名缺失')
      await axios.put(upload.url, file, {
        headers: upload.headers || { 'Content-Type': file.type },
        onUploadProgress: onProgress,
        skipErrorMessage: true,
      })
      const completed = await request.post<{ asset: MediaItem; task_id?: string }>(
        `/api/v1/media/upload-sessions/${session.data.upload_session_id}/complete`,
      )
      return { data: completed.data.asset }
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
  refreshMetadata: (id: string) => request.post<MediaItem | { asset: MediaItem; status: string; task_id?: string }>(`/api/v1/media/${id}/refresh-metadata`),
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

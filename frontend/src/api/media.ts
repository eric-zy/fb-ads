// 素材库接口封装
import request from '@/utils/request'
import axios from 'axios'
import type { AxiosProgressEvent } from 'axios'
import { fingerprintFile } from '@/utils/mediaFingerprint'

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
  uploader_name?: string | null
  uploader_email?: string | null
  uploaded_at?: string | null
  can_edit?: boolean
  binding_count?: number
  ready_binding_count?: number
  failed_binding_count?: number
  publish_count?: number
  successful_publish_count?: number
  last_published_at?: string | null
  usage_count?: number
  successful_usage_count?: number
  failed_usage_count?: number
  last_used_at?: string | null
}

export interface CreativeAssetGroup {
  id: string
  name: string
  description?: string | null
  owner_id?: string | null
  visibility: 'PRIVATE' | 'TENANT' | string
}
export interface CreativeAssetTag { id: string; name: string; color?: string | null }

export interface MediaUsageStats {
  asset_id: string
  range_start: string | null
  range_end: string | null
  usage_count: number
  successful_usage_count: number
  failed_usage_count: number
  last_used_at: string | null
  daily: Array<{
    date: string
    usage_count: number
    successful_usage_count: number
    failed_usage_count: number
  }>
  by_account: Array<{
    ad_account_id: string
    account_name: string
    usage_count: number
    successful_usage_count: number
    failed_usage_count: number
    last_used_at: string | null
  }>
}

export interface MediaOverviewStats {
  range_start: string | null
  range_end: string | null
  asset_count: number
  ready_asset_count: number
  binding_count: number
  ready_binding_count: number
  usage_count: number
  successful_usage_count: number
  failed_usage_count: number
  success_rate: number
  top_assets: Array<{
    asset_id: string
    name: string
    asset_type: string
    usage_count: number
    successful_usage_count: number
  }>
}

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
  multipart?: {
    upload_id: string
    part_size: number
    part_count: number
    uploaded_parts?: Array<{ part_number: number; etag: string; size?: number }>
    parts: Array<{
      part_number: number
      url: string
      method: 'PUT'
      headers?: Record<string, string>
    }>
  }
  binding_id?: string | null
  binding?: MetaAssetBinding
  task_id?: string | null
  resumed?: boolean
}

export interface UploadResult {
  data: MediaItem
  duplicate?: boolean
  binding_id?: string | null
  task_id?: string | null
}

export const mediaApi = {
  get: (id: string) => request.get<MediaItem>(`/api/v1/media/${id}`),
  stats: (id: string, params?: { start_date?: string; end_date?: string }) =>
    request.get<MediaUsageStats>(`/api/v1/media/${id}/stats`, { params }),
  statsOverview: (params?: { start_date?: string; end_date?: string; asset_type?: string; account_id?: string }) =>
    request.get<MediaOverviewStats>('/api/v1/media/stats/overview', { params }),
  getDownloadUrl: (id: string, kind: 'original' | 'thumbnail' | 'cover' = 'original') =>
    request.get<{ asset_id: string; url: string; expires_in: number }>(
      `/api/v1/media/${id}/download-url`,
      { params: { kind }, skipErrorMessage: true },
    ),
  list: (params?: { meta_account_id?: string; account_id?: string; asset_type?: string; group_id?: string; tag_id?: string }) =>
    request.get<MediaItem[]>('/api/v1/media', { params }),
  upload: (
    file: File,
    extra?: { meta_account_id?: string; account_id?: string; group_id?: string; asset_id?: string },
    onProgress?: (e: AxiosProgressEvent) => void,
    onHashProgress?: (loaded: number, total: number) => void,
  ): Promise<UploadResult> => {
    return fingerprintFile(file, onHashProgress).then(async ({ md5, sha256 }) => {
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
        asset_id: extra?.asset_id,
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
      if (session.data.multipart) {
        const multipart = session.data.multipart
        const loadedByPart = new Map<number, number>()
        for (const uploaded of multipart.uploaded_parts || []) {
          const size = uploaded.size ?? Math.min(
            multipart.part_size,
            Math.max(0, file.size - (uploaded.part_number - 1) * multipart.part_size),
          )
          loadedByPart.set(uploaded.part_number, size)
        }
        const pendingParts = multipart.parts.filter(
          (part) => !(multipart.uploaded_parts || []).some((uploaded) => uploaded.part_number === part.part_number),
        )
        let nextIndex = 0
        const concurrency = Math.min(4, pendingParts.length)
        const safeHeaders = (headers?: Record<string, string>) => {
          if (!headers) return {}
          // Host/Content-Length are browser-controlled and cannot be set by XHR.
          return Object.fromEntries(
            Object.entries(headers).filter(([name]) => !['host', 'content-length'].includes(name.toLowerCase())),
          )
        }
        const reportProgress = () => {
          if (!onProgress) return
          const loaded = Array.from(loadedByPart.values()).reduce((sum, value) => sum + value, 0)
          onProgress({ loaded, total: file.size, progress: file.size ? loaded / file.size : 0 } as AxiosProgressEvent)
        }
        const uploadPart = async (part: typeof multipart.parts[number]) => {
          const start = (part.part_number - 1) * multipart.part_size
          const chunk = file.slice(start, Math.min(start + multipart.part_size, file.size))
          let lastError: unknown
          for (let attempt = 1; attempt <= 3; attempt += 1) {
            try {
              await axios.put(part.url, chunk, {
                headers: safeHeaders(part.headers),
                onUploadProgress: (event) => {
                  loadedByPart.set(part.part_number, Math.min(event.loaded, chunk.size))
                  reportProgress()
                },
                skipErrorMessage: true,
              })
              loadedByPart.set(part.part_number, chunk.size)
              reportProgress()
              return
            } catch (error) {
              lastError = error
              loadedByPart.delete(part.part_number)
              if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, attempt * 1000))
            }
          }
          throw lastError || new Error(`OSS 分片 ${part.part_number} 上传失败`)
        }
        const worker = async () => {
          while (nextIndex < pendingParts.length) {
            const index = nextIndex
            nextIndex += 1
            await uploadPart(pendingParts[index])
          }
        }
        await Promise.all(Array.from({ length: concurrency }, () => worker()))
      } else {
        const upload = session.data.upload
        if (!upload?.url) throw new Error('OSS 上传签名缺失')
        await axios.put(upload.url, file, {
          headers: upload.headers || { 'Content-Type': file.type },
          onUploadProgress: onProgress,
          skipErrorMessage: true,
        })
      }
      const completed = await request.post<{ asset: MediaItem; task_id?: string }>(
        `/api/v1/media/upload-sessions/${session.data.upload_session_id}/complete`,
      )
      return { data: completed.data.asset }
    })
  },
  getUploadSession: (sessionId: string) =>
    request.get<UploadSessionResponse & {
      status: string
      upload_mode?: string
      uploaded_parts?: Array<{ part_number: number; etag: string; size?: number }>
    }>(`/api/v1/media/upload-sessions/${sessionId}`),
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

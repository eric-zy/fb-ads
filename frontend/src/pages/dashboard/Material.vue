<template>
  <div class="material">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">素材库</h2>
            <p class="page-desc">上传图片 / 视频素材，批量发布广告时可直接引用（支持图文、视频文字）。</p>
          </div>
          <el-upload
            :auto-upload="false"
            :show-file-list="false"
            :on-change="onSelect"
            :disabled="!filterAccount || uploading"
            accept="image/*,video/*"
          >
            <el-button type="primary" :icon="UploadFilled" :loading="uploading" :disabled="!filterAccount">
              {{ filterAccount ? '上传素材' : '请先选择广告账户' }}
            </el-button>
          </el-upload>
        </div>
      </template>

      <div class="filters">
        <el-select v-model="filterType" placeholder="类型" clearable style="width: 120px" @change="load">
          <el-option label="全部" value="" />
          <el-option label="图片" value="image" />
          <el-option label="视频" value="video" />
        </el-select>
        <el-select v-model="filterAccount" placeholder="选择广告账户" clearable filterable style="width: 260px" @change="load">
          <el-option v-for="account in accounts" :key="account.id" :label="`${account.account_name || account.account_id} (${account.account_id})`" :value="account.id" />
        </el-select>
      </div>

      <div v-loading="loading" class="grid">
        <el-empty v-if="!list.length" description="暂无素材，点击右上角上传" />
        <div v-for="item in list" :key="item.id" class="card">
          <div class="thumb">
            <img v-if="item.asset_type === 'image' && item.url" :src="item.url" alt="" />
            <video v-else-if="item.asset_type === 'video' && item.url" :src="item.url" controls />
            <el-icon v-else class="thumb-icon"><Picture /></el-icon>
          </div>
          <div class="info">
            <div class="name" :title="item.name">{{ item.name }}</div>
            <div class="meta">
              <el-tag size="small" :type="item.asset_type === 'image' ? 'success' : 'warning'">
                {{ item.asset_type === 'image' ? '图片' : '视频' }}
              </el-tag>
              <span class="size">{{ formatSize(item.size) }}</span>
            </div>
            <div class="status">
              <el-tag v-if="['ready', 'READY'].includes(item.status)" size="small" type="success">就绪</el-tag>
              <el-tag v-else-if="['uploading', 'UPLOADING', 'PENDING', 'PROCESSING'].includes(item.status)" size="small" type="info">上传中</el-tag>
              <el-tooltip v-else-if="item.status === 'FAILED' || item.status === 'failed'" :content="item.error || '点击查看失败原因'" placement="top">
                <el-tag size="small" type="danger" class="clickable" @click="openFailure(item)">失败</el-tag>
              </el-tooltip>
              <el-tag v-else size="small" type="danger">失败</el-tag>
              <span v-if="item.fb_hash || item.fb_video_id" class="fb-ok">✓ 已同步FB</span>
            </div>
          </div>
          <div class="actions">
            <el-popconfirm title="确定删除该素材？" @confirm="remove(item)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
            <el-button link type="primary" size="small" @click="openBindings(item)">映射</el-button>
          </div>
        </div>
      </div>
    </el-card>
    <el-dialog v-model="bindingVisible" title="账号素材映射" width="720px" @closed="stopBindingPolling">
      <el-table :data="bindings" v-loading="bindingLoading" size="small">
        <el-table-column prop="account_name" label="账号" min-width="180" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="meta_asset_id" label="Meta 素材 ID" min-width="180" show-overflow-tooltip />
        <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'FAILED'" link type="primary" @click="retryBinding(row)">重试</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
    <el-dialog v-model="failureVisible" title="素材上传失败原因" width="620px">
      <el-descriptions v-if="failureAsset" :column="1" border size="small">
        <el-descriptions-item label="素材">{{ failureAsset.name }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ failureAsset.status }}</el-descriptions-item>
        <el-descriptions-item label="重试次数">{{ failureAsset.retry_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="错误信息">
          <pre class="error-detail">{{ failureAsset.error || '未记录具体错误，请查看 Worker 日志' }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { UploadFilled, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { mediaApi, type MediaItem } from '@/api/media'
import { accountApi, type AdAccountItem } from '@/api/admin'

const list = ref<MediaItem[]>([])
const loading = ref(false)
const filterType = ref('')
const filterAccount = ref('')
const accounts = ref<AdAccountItem[]>([])
const uploading = ref(false)
const bindingVisible = ref(false)
const bindingLoading = ref(false)
const bindings = ref<any[]>([])
const bindingAssetId = ref('')
const failureVisible = ref(false)
const failureAsset = ref<MediaItem | null>(null)
let bindingTimer: number | null = null

const load = async () => {
  loading.value = true
  try {
    const { data } = await mediaApi.list({
      asset_type: filterType.value || undefined,
      account_id: filterAccount.value || undefined,
    })
    list.value = data
  } finally {
    loading.value = false
  }
}

const onSelect = async (file: any) => {
  const raw: File = file.raw
  if (!raw) return
  if (!filterAccount.value) {
    ElMessage.warning('请先选择归属广告账户，再上传素材')
    return
  }
  if (uploading.value) return
  uploading.value = true
  try {
    const res = await mediaApi.upload(raw, { account_id: filterAccount.value })
    ElMessage.success(`已上传：${res.data.name}`)
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '素材上传失败'
    ElMessage.error(String(detail))
  } finally {
    uploading.value = false
  }
}

const remove = async (item: MediaItem) => {
  try {
    await mediaApi.remove(item.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const refreshBindings = async () => { if (!bindingAssetId.value) return; const { data } = await mediaApi.bindings(bindingAssetId.value); bindings.value = data }
const openBindings = async (item: MediaItem) => { bindingAssetId.value = item.id; bindingVisible.value = true; bindingLoading.value = true; try { await refreshBindings(); if (bindingTimer !== null) window.clearInterval(bindingTimer); bindingTimer = window.setInterval(refreshBindings, 2000) } finally { bindingLoading.value = false } }
const retryBinding = async (row: any) => { try { await mediaApi.retryBinding(bindingAssetId.value, row.id); row.status = 'PENDING'; row.error_message = null; ElMessage.success('已提交素材重试任务') } catch { /* 全局拦截器提示错误 */ } }
const stopBindingPolling = () => { if (bindingTimer !== null) { window.clearInterval(bindingTimer); bindingTimer = null } }
const openFailure = (item: MediaItem) => { failureAsset.value = item; failureVisible.value = true }
onBeforeUnmount(() => { if (bindingTimer !== null) window.clearInterval(bindingTimer) })

const formatSize = (n?: number | null) => {
  if (!n) return '-'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

onMounted(async () => {
  try {
    const { data } = await accountApi.list({ page: 1, page_size: 100 })
    accounts.value = data || []
  } catch {
    accounts.value = []
  }
  await load()
})
</script>

<style scoped lang="scss">
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; }
}
.clickable { cursor: pointer; }
.error-detail { white-space: pre-wrap; word-break: break-word; margin: 0; font-family: inherit; color: #f56c6c; }
.filters {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  .thumb {
    height: 140px;
    background: #f5f7fa;
    display: flex;
    align-items: center;
    justify-content: center;
    img, video { width: 100%; height: 100%; object-fit: cover; }
    .thumb-icon { font-size: 40px; color: #c0c4cc; }
  }
  .info { padding: 8px 10px; flex: 1; }
  .name {
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta { margin-top: 6px; display: flex; align-items: center; gap: 8px; }
  .size { font-size: 12px; color: #909399; }
  .status { margin-top: 6px; display: flex; align-items: center; gap: 8px; }
  .fb-ok { font-size: 12px; color: #67c23a; }
  .actions { padding: 6px 10px; border-top: 1px solid #f0f0f0; text-align: right; }
}
</style>

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
            accept="image/*,video/*"
            multiple
          >
            <el-button type="primary" :icon="UploadFilled">上传素材</el-button>
          </el-upload>
        </div>
      </template>

      <div class="filters">
        <el-select v-model="filterType" placeholder="类型" clearable style="width: 120px" @change="load">
          <el-option label="全部" value="" />
          <el-option label="图片" value="image" />
          <el-option label="视频" value="video" />
        </el-select>
        <el-select v-model="filterMeta" placeholder="归属主账号" clearable filterable style="width: 220px" @change="load">
          <el-option v-for="m in metaAccounts" :key="m.id" :label="m.name" :value="m.id" />
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
              <el-tag v-if="item.status === 'ready'" size="small" type="success">就绪</el-tag>
              <el-tag v-else-if="item.status === 'uploading'" size="small" type="info">上传中</el-tag>
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
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { UploadFilled, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { mediaApi, type MediaItem } from '@/api/media'
import { metaAccountApi, type MetaAccountItem } from '@/api/admin'

const list = ref<MediaItem[]>([])
const loading = ref(false)
const filterType = ref('')
const filterMeta = ref('')
const metaAccounts = ref<MetaAccountItem[]>([])

const load = async () => {
  loading.value = true
  try {
    const { data } = await mediaApi.list({
      asset_type: filterType.value || undefined,
      meta_account_id: filterMeta.value || undefined,
    })
    list.value = data
  } finally {
    loading.value = false
  }
}

const onSelect = async (file: any) => {
  const raw: File = file.raw
  if (!raw) return
  try {
    const res = await mediaApi.upload(raw, { meta_account_id: filterMeta.value || undefined })
    ElMessage.success(`已上传：${res.data.name}`)
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
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

const formatSize = (n?: number | null) => {
  if (!n) return '-'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

onMounted(async () => {
  await load()
  try {
    metaAccounts.value = await metaAccountApi.list()
  } catch {
    metaAccounts.value = []
  }
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

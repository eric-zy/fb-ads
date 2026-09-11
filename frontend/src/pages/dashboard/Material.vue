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
          <el-button text type="primary" @click="createGroupVisible = true">新建分组</el-button>
          <el-button text type="primary" :disabled="!groups.length" @click="openMembers">成员管理</el-button>
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
        <el-select v-model="filterGroup" placeholder="素材分组" clearable filterable style="width: 180px" @change="load">
          <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
        </el-select>
        <el-select v-model="filterTag" placeholder="素材标签" clearable filterable style="width: 160px" @change="load">
          <el-option v-for="tag in tags" :key="tag.id" :label="tag.name" :value="tag.id" />
        </el-select>
        <el-button @click="createTagVisible = true">新建标签</el-button>
      </div>

      <div v-if="selectedIds.length" class="bulk-bar">
        <span>已选择 {{ selectedIds.length }} 个素材</span>
        <el-select v-model="moveTargetGroup" placeholder="移动到分组" clearable style="width: 180px">
          <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
        </el-select>
        <el-button type="primary" size="small" @click="moveSelected">移动</el-button>
        <el-button size="small" @click="selectedIds = []">取消选择</el-button>
      </div>
      <div v-loading="loading" class="grid">
        <el-empty v-if="!list.length" description="暂无素材，点击右上角上传" />
        <div v-for="item in list" :key="item.id" class="card">
          <el-checkbox v-model="selectedIds" :label="item.id" class="asset-check"><span /></el-checkbox>
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
              <span v-if="item.width && item.height" class="size">{{ item.width }}×{{ item.height }}</span>
              <span v-if="item.duration" class="size">{{ formatDuration(item.duration) }}</span>
            </div>
            <div v-if="item.tag_ids?.length" class="tags">
              <el-tag v-for="tagId in item.tag_ids" :key="tagId" size="small" effect="plain">{{ tagName(tagId) }}</el-tag>
            </div>
            <div v-if="placementAdvice(item)" class="placement-tip">{{ placementAdvice(item) }}</div>
            <div class="status">
              <el-tag v-if="['ready', 'READY'].includes(item.status)" size="small" type="success">本地就绪</el-tag>
              <el-tag v-else-if="['uploading', 'UPLOADING', 'PENDING', 'PROCESSING'].includes(item.status)" size="small" type="info">上传中</el-tag>
              <el-tooltip v-else-if="item.status === 'FAILED' || item.status === 'failed'" :content="item.error || '点击查看失败原因'" placement="top">
                <el-tag size="small" type="danger" class="clickable" @click="openFailure(item)">失败</el-tag>
              </el-tooltip>
              <el-tag v-else size="small" type="danger">失败</el-tag>
              <span v-if="item.fb_hash || item.fb_video_id" class="fb-ok">✓ 已同步 Meta</span>
            </div>
          </div>
          <div class="actions">
            <el-popconfirm title="确定删除该素材？" @confirm="remove(item)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
            <el-button link type="primary" size="small" @click="openBindings(item)">映射</el-button>
            <el-button link type="success" size="small" @click="syncAllAccounts(item)">同步账户</el-button>
            <el-button link size="small" @click="refreshMetadata(item)">刷新信息</el-button>
          </div>
        </div>
      </div>
    </el-card>
    <el-dialog v-model="createGroupVisible" title="新建素材分组" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="newGroupName" maxlength="128" /></el-form-item>
        <el-form-item label="可见性"><el-radio-group v-model="newGroupVisibility"><el-radio value="PRIVATE">私有</el-radio><el-radio value="TENANT">租户共享</el-radio></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="createGroupVisible = false">取消</el-button><el-button type="primary" @click="createGroup">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="createTagVisible" title="新建素材标签" width="420px">
      <el-input v-model="newTagName" maxlength="64" placeholder="例如：US、UGC、V2" />
      <template #footer><el-button @click="createTagVisible = false">取消</el-button><el-button type="primary" @click="createTag">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="membersVisible" title="分组成员管理" width="620px">
      <el-select v-model="memberGroupId" placeholder="选择分组" style="width:100%;margin-bottom:12px" @change="loadMembers">
        <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
      </el-select>
      <div class="member-add">
        <el-input v-model="memberUserId" placeholder="输入用户 ID" />
        <el-checkbox v-model="memberCanEdit">允许编辑</el-checkbox>
        <el-button type="primary" @click="addMember">添加</el-button>
      </div>
      <el-table :data="members" size="small" v-loading="membersLoading">
        <el-table-column prop="user_id" label="用户 ID" />
        <el-table-column label="权限"><template #default="{ row }">{{ row.can_edit ? '可编辑' : '只读' }}</template></el-table-column>
        <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="danger" @click="removeMember(row.user_id)">移除</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
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
import { mediaApi, type MediaItem, type CreativeAssetGroup, type CreativeAssetTag } from '@/api/media'
import { accountApi, type AdAccountItem } from '@/api/admin'

const list = ref<MediaItem[]>([])
const loading = ref(false)
const filterType = ref('')
const filterAccount = ref('')
const filterGroup = ref('')
const filterTag = ref('')
const groups = ref<CreativeAssetGroup[]>([])
const tags = ref<CreativeAssetTag[]>([])
const selectedIds = ref<string[]>([])
const moveTargetGroup = ref('')
const createGroupVisible = ref(false)
const createTagVisible = ref(false)
const newTagName = ref('')
const membersVisible = ref(false)
const memberGroupId = ref('')
const memberUserId = ref('')
const memberCanEdit = ref(false)
const members = ref<any[]>([])
const membersLoading = ref(false)
const newGroupName = ref('')
const newGroupVisibility = ref('PRIVATE')
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
      group_id: filterGroup.value || undefined,
      tag_id: filterTag.value || undefined,
    })
    list.value = data
  } finally {
    loading.value = false
  }
}

const onSelect = async (file: any) => {
  const raw: File = file.raw
  if (!raw) return
  const validation = await validateMediaFile(raw)
  if (validation) {
    ElMessage.warning(validation)
    return
  }
  if (!filterAccount.value) {
    ElMessage.warning('请先选择归属广告账户，再上传素材')
    return
  }
  if (uploading.value) return
  uploading.value = true
  try {
    const res = await mediaApi.upload(raw, { account_id: filterAccount.value, group_id: filterGroup.value || undefined })
    ElMessage.success(`已上传：${res.data.name}`)
    await load()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '素材上传失败'
    ElMessage.error(String(detail))
  } finally {
    uploading.value = false
  }
}

const validateMediaFile = (file: File): Promise<string | null> => new Promise(resolve => {
  const isImage = file.type.startsWith('image/')
  const isVideo = file.type.startsWith('video/')
  if (!isImage && !isVideo) return resolve('仅支持图片或视频文件')
  const maxBytes = isImage ? 30 * 1024 * 1024 : 200 * 1024 * 1024
  if (file.size > maxBytes) return resolve(`文件不能超过 ${isImage ? '30MB' : '200MB'}`)

  if (isImage) {
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(image.src)
      if (image.width < 600 || image.height < 600) resolve('图片尺寸不能小于 600 × 600')
      else if (image.width / image.height < 0.5 || image.width / image.height > 2.2) resolve('图片比例不适合常用 Meta 广告版位')
      else resolve(null)
    }
    image.onerror = () => resolve('图片文件无法解析')
    image.src = URL.createObjectURL(file)
    return
  }

  const video = document.createElement('video')
  video.preload = 'metadata'
  video.onloadedmetadata = () => {
    URL.revokeObjectURL(video.src)
    if (!video.videoWidth || !video.videoHeight) resolve('视频尺寸无法识别')
    else if (video.duration > 241) resolve('视频时长不能超过 241 秒')
    else if (video.videoWidth < 600 || video.videoHeight < 600) resolve('视频尺寸不能小于 600 × 600')
    else resolve(null)
  }
  video.onerror = () => resolve('视频文件无法解析')
  video.src = URL.createObjectURL(file)
})

const createGroup = async () => {
  if (!newGroupName.value.trim()) { ElMessage.warning('请输入分组名称'); return }
  try {
    const { data } = await mediaApi.groups.create({ name: newGroupName.value.trim(), visibility: newGroupVisibility.value })
    groups.value.unshift(data)
    filterGroup.value = data.id
    newGroupName.value = ''
    createGroupVisible.value = false
    ElMessage.success('分组已创建')
  } catch { /* 全局拦截器提示错误 */ }
}

const tagName = (id: string) => tags.value.find(tag => tag.id === id)?.name || id
const placementAdvice = (item: MediaItem) => {
  if (!item.width || !item.height) return ''
  const ratio = item.width / item.height
  if (ratio >= 0.9 && ratio <= 1.1) return '建议：Feed / 方图版位'
  if (ratio >= 0.52 && ratio <= 0.58) return '建议：Stories / Reels / 9:16'
  if (ratio >= 1.7 && ratio <= 2.0) return '建议：Feed 横版版位'
  return '建议：发布前确认版位裁剪'
}
const createTag = async () => {
  if (!newTagName.value.trim()) { ElMessage.warning('请输入标签名称'); return }
  try {
    const { data } = await mediaApi.tags.create({ name: newTagName.value.trim() })
    tags.value.push(data)
    newTagName.value = ''
    createTagVisible.value = false
    ElMessage.success('标签已创建')
  } catch { /* 全局拦截器提示错误 */ }
}

const openMembers = () => {
  memberGroupId.value = groups.value[0]?.id || ''
  membersVisible.value = true
  loadMembers()
}
const loadMembers = async () => {
  if (!memberGroupId.value) return
  membersLoading.value = true
  try { members.value = (await mediaApi.groups.members(memberGroupId.value)).data || [] } finally { membersLoading.value = false }
}
const addMember = async () => {
  if (!memberGroupId.value || !memberUserId.value.trim()) { ElMessage.warning('请选择分组并输入用户 ID'); return }
  try {
    await mediaApi.groups.upsertMember(memberGroupId.value, memberUserId.value.trim(), memberCanEdit.value)
    memberUserId.value = ''
    await loadMembers()
    ElMessage.success('成员已更新')
  } catch { /* 全局拦截器提示错误 */ }
}
const removeMember = async (userId: string) => {
  try { await mediaApi.groups.removeMember(memberGroupId.value, userId); await loadMembers(); ElMessage.success('成员已移除') } catch { /* 全局拦截器提示错误 */ }
}

const moveSelected = async () => {
  if (!moveTargetGroup.value) { ElMessage.warning('请选择目标分组'); return }
  try {
    await mediaApi.groups.moveAssets(selectedIds.value, moveTargetGroup.value)
    ElMessage.success('素材已移动')
    selectedIds.value = []
    moveTargetGroup.value = ''
    await load()
  } catch { /* 全局拦截器提示错误 */ }
}

const syncAllAccounts = async (item: MediaItem) => {
  if (!accounts.value.length) { ElMessage.warning('暂无可用广告账户'); return }
  try {
    await mediaApi.syncToAccounts(item.id, accounts.value.map(account => account.id))
    ElMessage.success('已提交全部可见广告账户同步任务')
    await openBindings(item)
  } catch { /* 全局拦截器提示错误 */ }
}

const refreshMetadata = async (item: MediaItem) => {
  try {
    const { data } = await mediaApi.refreshMetadata(item.id)
    Object.assign(item, data)
    ElMessage.success('素材信息已刷新')
  } catch { /* 全局拦截器提示错误 */ }
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
const formatDuration = (seconds?: number | null) => {
  if (!seconds) return ''
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

onMounted(async () => {
  try {
    const { data } = await accountApi.list({ page: 1, page_size: 100 })
    accounts.value = data || []
  } catch {
    accounts.value = []
  }
  try {
    const { data } = await mediaApi.groups.list()
    groups.value = data || []
  } catch {
    groups.value = []
  }
  try {
    const { data } = await mediaApi.tags.list()
    tags.value = data || []
  } catch {
    tags.value = []
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
.bulk-bar { display:flex; align-items:center; gap:10px; margin-bottom:12px; color:#606266; font-size:13px; }
.member-add { display:flex; align-items:center; gap:12px; margin-bottom:12px; }
.card {
  position: relative;
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
  .asset-check { position:absolute; left:8px; top:8px; z-index:2; background:rgba(255,255,255,.9); padding:2px 4px; border-radius:4px; }
  .info { padding: 8px 10px; flex: 1; }
  .name {
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meta { margin-top: 6px; display: flex; align-items: center; gap: 8px; }
  .tags { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px; }
  .placement-tip { margin-top: 6px; color: #909399; font-size: 11px; line-height: 1.4; }
  .size { font-size: 12px; color: #909399; }
  .status { margin-top: 6px; display: flex; align-items: center; gap: 8px; }
  .fb-ok { font-size: 12px; color: #67c23a; }
  .actions { padding: 6px 10px; border-top: 1px solid #f0f0f0; text-align: right; }
}
</style>

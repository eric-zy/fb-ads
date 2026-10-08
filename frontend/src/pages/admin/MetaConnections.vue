<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">{{ adminView ? 'Meta 个人授权管理' : '我的 Meta 授权' }}</h2>
        <p class="page-subtitle">每位投手使用自己的 Meta 个号授权。平台分配账户后，还需该个号具有对应资产权限。</p>
      </div>
      <div class="head-actions">
        <el-button v-if="adminView" @click="router.push('/admin/accounts')">交接 / 分配账户</el-button>
        <el-button type="primary" @click="authorize()">接入我的 Meta 个号</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="connectorMode" type="info" :closable="false" show-icon class="mb12">
      当前使用海外 Connector OAuth。本页展示海外授权的状态、权限和有效期，可同步资产或重新授权。
      使用 Instagram 身份时，还需授权专业账户及其关联 Page；权限缺失时，请管理员更新 Meta 应用的授权配置后重新授权。
    </el-alert>
    <el-alert v-else type="info" :closable="false" show-icon class="mb12">
      连接页只负责授权和连接健康检查；BM、广告账户和投放权限请在对应资产页面管理。Access Token 仅在服务端加密保存。
    </el-alert>

    <el-card shadow="never" class="card-shadow">
      <el-select v-if="adminView" v-model="scope" style="width:180px;margin-bottom:16px" @change="load"><el-option label="全部投手授权" value="tenant" /><el-option label="我的个人授权" value="mine" /></el-select>
      <el-table :data="connections" v-loading="loading" stripe>
        <el-table-column type="expand" width="45"><template #default="{ row }"><el-descriptions :column="2" border style="padding:16px"><el-descriptions-item label="应用 ID">{{ row.app_id }}</el-descriptions-item><el-descriptions-item label="授权版本">V{{ row.version || 1 }}</el-descriptions-item><el-descriptions-item label="权限">{{ row.scopes?.join(', ') || '-' }}</el-descriptions-item><el-descriptions-item label="最近同步">{{ formatTime(row.last_synced_at) }}</el-descriptions-item><el-descriptions-item label="最近错误" :span="2">{{ row.last_error || '-' }}</el-descriptions-item><el-descriptions-item v-if="adminView && row.status !== 'OWNER_UNKNOWN' && row.executable_account_ids?.length" label="系统同步" :span="2"><el-button :disabled="!['ACTIVE','EXPIRING','EXPIRING_1_DAY'].includes(row.health || row.status)" @click="chooseReportingDefault(row as TableRow<typeof connections>)">设为系统同步授权</el-button></el-descriptions-item></el-descriptions></template></el-table-column>
        <el-table-column v-if="adminView" prop="authorized_by_username" label="所属投手" min-width="130" />
        <el-table-column label="Meta 用户" min-width="150">
          <template #default="{ row }">{{ row.meta_user_id }}</template>
        </el-table-column>
        <el-table-column label="授权状态" width="110">
          <template #default="{ row }">
            <el-tag :type="connectionType(row.health || row.status)">{{ connectionLabel(row.health || row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="已同步资产" width="155"><template #default="{ row }">账户 {{ row.account_count }} · Page {{ row.page_count }}<div>BM {{ row.business_count }}</div></template></el-table-column>
        <el-table-column label="账户名称" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.account_names?.join('、') || '-' }}</template></el-table-column>
        <el-table-column label="到期时间" width="230"><template #default="{ row }"><div>Token：{{ formatTime(row.expires_at) }}</div><div>数据访问：{{ formatTime(row.data_access_expires_at) }}</div></template></el-table-column>
        <el-table-column label="操作" width="310" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status !== 'OWNER_UNKNOWN'">
              <el-button link type="primary" :disabled="!['ACTIVE','EXPIRING','EXPIRING_1_DAY'].includes(row.health || row.status)" :loading="syncingId === row.id" @click="sync(row as TableRow<typeof connections>)">同步资产</el-button>
              <el-button v-if="row.is_owner" link type="warning" @click="authorize(row.id)">重新授权</el-button>
              <el-button v-if="row.is_owner && row.executable_account_ids?.length" link type="primary" @click="chooseDefault(row as TableRow<typeof connections>)">执行授权</el-button>
              <el-button link type="danger" @click="disconnect(row as TableRow<typeof connections>)">解除授权</el-button>
              <span v-if="!row.is_owner">请原投手重新授权</span>
            </template>
            <span v-else>请原投手重新接入确认归属</span>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无 Meta 授权，请先完成 OAuth" /></template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { formatDateTime as displayDateTime } from '@/utils/dateTime'
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { metaConnectionsApi, type MetaConnection } from '@/api/metaConnections'
import { credentialApi } from '@/api/admin'

const connections = ref<MetaConnection[]>([])
const route = useRoute()
const router = useRouter()
const adminView = computed(() => route.path.startsWith('/admin/'))
const scope = ref<'mine' | 'tenant'>(adminView.value ? 'tenant' : 'mine')
const loading = ref(false)
const syncingId = ref<string | null>(null)
const connectorMode = ref(false)
const formatTime = displayDateTime
const connectionLabel = (status: string) => ({ ACTIVE: '正常', EXPIRED: '已过期', REVOKED: '已解除', SUSPENDED: '用户已停用', OWNER_UNKNOWN: '归属待确认', INVALID: '授权失效', DISABLED: '已停用', EXPIRING: '7 天内到期', EXPIRING_1_DAY: '1 天内到期', PERMISSION_MISSING: '缺少权限', UNAVAILABLE: '暂不可用', MISSING: '未找到' } as Record<string, string>)[status] || status
const connectionType = (status: string): 'success' | 'danger' | 'warning' | 'info' => status === 'ACTIVE' ? 'success' : (status === 'EXPIRED' || status === 'REVOKED' ? 'danger' : 'warning')

async function load() {
  loading.value = true
  try {
    const mode = await credentialApi.accessMode()
    connectorMode.value = mode.data?.access_mode === 'connector'
    connections.value = (await metaConnectionsApi.list(scope.value)).data
  } finally { loading.value = false }
}

async function authorize(connectionId?: string) {
  const { data } = await credentialApi.oauthAuthorizeFirst(connectionId)
  window.location.assign(data.authorization_url)
}
async function disconnect(row: MetaConnection) {
  try {
    await ElMessageBox.confirm('解除后将阻断该身份的后续操作，并取消尚未开始的投放任务。账户、历史任务和报表保留；交接请在广告账户分配中选择接手人，由接手人使用自己的 Meta 个号授权。', '解除个人 Meta 授权', { type: 'warning' })
    const { data } = await metaConnectionsApi.disconnect(row.id)
    ElMessage.success(`授权已解除，取消 ${data.cancelled_jobs} 个待执行任务`)
    await load()
  } catch { /* cancelled or handled by the request interceptor */ }
}
async function chooseDefault(row: MetaConnection) {
  try {
    await ElMessageBox.confirm(`后续新任务将使用这个 Meta 个号执行其已分配账户：${row.account_names?.join('、') || ''}。已经提交的任务保留原授权身份。`, '选择执行授权', { type: 'info' })
    await metaConnectionsApi.chooseDefault(row.id, row.executable_account_ids || [])
    ElMessage.success('执行授权已设置')
  } catch { /* cancelled or handled by the request interceptor */ }
}
async function chooseReportingDefault(row: MetaConnection) {
  try {
    await ElMessageBox.confirm(`系统定时同步将明确使用投手 ${row.authorized_by_username} 的 Meta 个号 ${row.meta_user_id}，目标账户：${row.account_names?.join('、') || ''}。该身份失效后会停止同步，请完成账户交接后再指定接手人的授权。`, '指定系统同步授权', { type: 'warning' })
    await metaConnectionsApi.chooseReportingDefault(row.id, row.executable_account_ids || [])
    ElMessage.success('系统同步授权已指定')
  } catch { /* cancelled or handled by the request interceptor */ }
}

async function sync(row: MetaConnection) {
  syncingId.value = row.id
  try { await metaConnectionsApi.sync(row.id); ElMessage.success('同步任务已提交') } finally { syncingId.value = null }
}

onMounted(load)
</script>

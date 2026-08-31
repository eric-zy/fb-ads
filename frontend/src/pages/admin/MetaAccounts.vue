<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">主账号管理（Business Manager）</h2>
        <p class="page-subtitle">
          BM 只保存主数据，Access Token 由
          <el-link type="primary" @click="goCredentials()">凭据管理</el-link>
          单独加密存储，二者解耦
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增 BM</el-button>
    </div>

    <el-card class="card-shadow" shadow="never">
      <el-table :data="list" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="BM 名称" min-width="150" />
        <el-table-column prop="business_id" label="Business ID" min-width="150" />
        <el-table-column label="广告账户" width="100" align="center">
          <template #default="{ row }">
            <el-link type="primary" @click="goAccounts(row)">{{ row.account_count }}</el-link>
          </template>
        </el-table-column>

        <el-table-column label="凭据状态" width="180">
          <template #default="{ row }">
            <div class="cred-cell">
              <el-tag :type="credType(row)" effect="light" round>{{ credLabel(row) }}</el-tag>
              <span v-if="row.credential_masked" class="cred-mask">{{ row.credential_masked }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="同步状态" width="150">
          <template #default="{ row }">
            <el-tooltip v-if="row.last_sync_error" :content="row.last_sync_error" placement="top">
              <el-tag :type="syncType(row)" effect="plain" size="small">{{ syncLabel(row) }}</el-tag>
            </el-tooltip>
            <el-tag v-else :type="syncType(row)" effect="plain" size="small">{{ syncLabel(row) }}</el-tag>
            <div v-if="row.last_synced_at" class="sync-time">{{ formatTime(row.last_synced_at) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="默认" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" type="success">当前</el-tag>
            <el-button v-else link type="primary" size="small" @click="setDefault(row)">设为默认</el-button>
          </template>
        </el-table-column>

        <el-table-column label="BM 状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row)" effect="light">{{ statusLabel(row) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="goDetail(row)">查看</el-button>
            <el-button link type="primary" size="small" @click="syncAccounts(row)">同步</el-button>
            <el-button link type="info" size="small" @click="openLogs(row)">日志</el-button>
            <el-button link type="info" size="small" @click="verifyConnection(row)">验证</el-button>
            <el-button link type="warning" size="small" @click="openRotate(row)">换 Token</el-button>
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => onMoreCommand(cmd, row)">
              <el-button link type="danger" size="small">
                更多<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="disable" :disabled="row.status !== 'ACTIVE'">禁用</el-dropdown-item>
                  <el-dropdown-item command="archive" :disabled="row.status === 'ARCHIVED'">归档</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无主账号" />
        </template>
      </el-table>
    </el-card>

    <!-- 新增 / 编辑 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑 BM' : '新增 BM'" width="540px" destroy-on-close>
      <el-form :model="form" label-width="120px">
        <el-form-item label="BM 名称" required>
          <el-input v-model="form.name" placeholder="如：公司主 BM" />
        </el-form-item>
        <el-form-item label="Business ID" required>
          <el-input v-model="form.business_id" placeholder="如：1234567890" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="Access Token">
          <el-input
            v-model="form.access_token"
            type="textarea"
            :rows="2"
            :placeholder="isEdit ? '留空表示不更换 Token（Token 由「换 Token」维护）' : 'BM 访问令牌，加密存入凭据表'"
            show-password
          />
        </el-form-item>
        <el-form-item label="App ID">
          <el-input v-model="form.app_id" placeholder="可选" />
        </el-form-item>
        <el-form-item label="时区">
          <el-input v-model="form.timezone" placeholder="可选，同步可自动回填" />
        </el-form-item>
        <el-form-item label="货币">
          <el-input v-model="form.currency" placeholder="可选，如 USD" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 轮换 Token -->
    <el-dialog v-model="rotateVisible" :title="`更换 Token - ${rotateTarget?.name || ''}`" width="540px" destroy-on-close>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="旧凭据会保留为「已停用」以便回溯，新凭据立即生效"
        class="mb12"
      />
      <el-form :model="rotateForm" label-width="120px">
        <el-form-item label="新 Token" required>
          <el-input v-model="rotateForm.access_token" type="textarea" :rows="3" show-password />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="rotateForm.token_type" style="width: 100%">
            <el-option label="USER（用户令牌）" value="USER" />
            <el-option label="SYSTEM_USER（系统用户）" value="SYSTEM_USER" />
            <el-option label="PAGE（主页令牌）" value="PAGE" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rotateVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitRotate">确认更换</el-button>
      </template>
    </el-dialog>

    <!-- 同步日志 -->
    <el-dialog v-model="logsVisible" :title="`同步日志 - ${logsTarget?.name || ''}`" width="760px" destroy-on-close>
      <el-table :data="syncLogs" v-loading="logsLoading" size="small" max-height="420">
        <el-table-column prop="sync_type" label="类型" width="120" />
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <el-tag :type="logStatusType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="120">
          <template #default="{ row }">{{ row.success_count }} / {{ row.total_count }}</template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="200" show-overflow-tooltip />
        <el-table-column label="开始时间" width="170">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <template #empty><el-empty description="暂无同步记录" /></template>
      </el-table>
      <template #footer>
        <el-button @click="openLogs(logsTarget!)">刷新</el-button>
        <el-button type="primary" @click="logsVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, ArrowDown } from '@element-plus/icons-vue'
import {
  metaAccountApi,
  type MetaAccountItem,
  type SyncLogItem,
} from '@/api/admin'

const router = useRouter()
const list = ref<MetaAccountItem[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const editingId = ref<string | null>(null)
const form = ref(emptyForm())

const rotateVisible = ref(false)
const rotateTarget = ref<MetaAccountItem | null>(null)
const rotateForm = ref({ access_token: '', token_type: 'USER' })

const logsVisible = ref(false)
const logsLoading = ref(false)
const logsTarget = ref<MetaAccountItem | null>(null)
const syncLogs = ref<SyncLogItem[]>([])

function emptyForm() {
  return {
    name: '',
    business_id: '',
    access_token: '',
    app_id: '',
    timezone: '',
    currency: '',
    description: '',
    is_default: false,
  }
}

function formatTime(v: string | null) {
  if (!v) return '-'
  return v.replace('T', ' ').slice(0, 19)
}

// ---- 凭据状态 ----
function credLabel(row: MetaAccountItem) {
  if (row.credential_source === 'NONE') return '无凭据'
  if (row.credential_is_expired || row.credential_status === 'EXPIRED') return '已过期'
  return (
    { ACTIVE: '正常', INVALID: '权限异常', DISABLED: '已停用', VERIFYING: '校验中' }[
      row.credential_status
    ] || row.credential_status
  )
}
function credType(row: MetaAccountItem): 'success' | 'danger' | 'warning' | 'info' {
  if (row.credential_source === 'NONE') return 'info'
  if (row.credential_is_expired || row.credential_status === 'EXPIRED') return 'danger'
  if (row.credential_status === 'ACTIVE') return 'success'
  return 'warning'
}

// ---- 同步状态（与业务状态分离） ----
function syncLabel(row: MetaAccountItem) {
  return (
    { PENDING: '待同步', SYNCING: '同步中', SUCCESS: '已同步', FAILED: '同步失败' }[
      row.sync_status
    ] || row.sync_status
  )
}
function syncType(row: MetaAccountItem): 'success' | 'danger' | 'warning' | 'info' {
  if (row.sync_status === 'SUCCESS') return 'success'
  if (row.sync_status === 'FAILED') return 'danger'
  if (row.sync_status === 'SYNCING') return 'warning'
  return 'info'
}

// ---- 业务状态 ----
function statusLabel(row: MetaAccountItem) {
  return { ACTIVE: '启用', DISABLED: '已禁用', ARCHIVED: '已归档' }[row.status] || row.status
}
function statusType(row: MetaAccountItem): 'success' | 'danger' | 'info' {
  if (row.status === 'ACTIVE') return 'success'
  if (row.status === 'DISABLED') return 'danger'
  return 'info'
}

function logStatusType(status: string): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'PARTIAL_SUCCESS') return 'warning'
  return 'info'
}

async function load() {
  loading.value = true
  try {
    const { data } = await metaAccountApi.list()
    list.value = data
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  editingId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row: MetaAccountItem) {
  isEdit.value = true
  editingId.value = row.id
  form.value = {
    name: row.name,
    business_id: row.business_id,
    access_token: '',
    app_id: row.app_id || '',
    timezone: row.timezone || '',
    currency: row.currency || '',
    description: row.description || '',
    is_default: row.is_default,
  }
  dialogVisible.value = true
}

async function save() {
  if (!form.value.name || !form.value.business_id) {
    ElMessage.warning('请填写 BM 名称和 Business ID')
    return
  }
  if (!isEdit.value && !form.value.access_token) {
    ElMessage.warning('新增 BM 时必须提供 Access Token')
    return
  }
  saving.value = true
  try {
    if (isEdit.value && editingId.value) {
      const payload: Record<string, unknown> = { ...form.value }
      // 留空表示不更换 Token
      if (!payload.access_token) delete payload.access_token
      await metaAccountApi.update(editingId.value, payload)
      ElMessage.success('已更新')
    } else {
      await metaAccountApi.create({ ...form.value })
      ElMessage.success('已新增 BM')
    }
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

async function setDefault(row: MetaAccountItem) {
  try {
    await metaAccountApi.setDefault(row.id)
    ElMessage.success('已切换默认 BM')
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

/** 异步同步：HTTP 不等待 Meta API，返回 job_id */
async function syncAccounts(row: MetaAccountItem) {
  try {
    const { data } = await metaAccountApi.syncAccounts(row.id)
    ElMessage.success({
      message: `同步任务已提交（${data.job_id.slice(0, 8)}…），稍后可在「日志」中查看结果`,
      duration: 4000,
    })
    // 同步是异步的，延迟刷新以观察 sync_status 变化
    setTimeout(load, 3000)
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function openLogs(row: MetaAccountItem) {
  logsTarget.value = row
  logsVisible.value = true
  logsLoading.value = true
  try {
    const { data } = await metaAccountApi.syncLogs(row.id, { limit: 30 })
    syncLogs.value = data
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    logsLoading.value = false
  }
}

async function verifyConnection(row: MetaAccountItem) {
  try {
    const { data } = await metaAccountApi.verifyConnection(row.id)
    if (data.dev_mode) ElMessage.warning('开发模式：未配置 FB 凭据，未做真实校验')
    else if (data.ok) ElMessage.success('连接正常，Business ID 校验通过')
    else ElMessage.error('校验失败：' + (data.error || '未知错误'))
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

function openRotate(row: MetaAccountItem) {
  rotateTarget.value = row
  rotateForm.value = { access_token: '', token_type: 'USER' }
  rotateVisible.value = true
}

async function submitRotate() {
  if (!rotateTarget.value || !rotateForm.value.access_token) {
    ElMessage.warning('请填写新的 Access Token')
    return
  }
  saving.value = true
  try {
    await metaAccountApi.rotateToken(rotateTarget.value.id, {
      access_token: rotateForm.value.access_token,
      token_type: rotateForm.value.token_type,
    })
    ElMessage.success('Token 已更换')
    rotateVisible.value = false
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

async function onMoreCommand(cmd: string, row: MetaAccountItem) {
  if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm(
        `确认删除 BM「${row.name}」？其名下凭据会一并清理。`,
        '警告',
        { type: 'error' }
      )
    } catch {
      return
    }
    try {
      await metaAccountApi.remove(row.id)
      ElMessage.success('已删除')
      await load()
    } catch (e: any) {
      // 错误已由 utils/request.ts 全局拦截器弹框提示
    }
    return
  }

  const label = cmd === 'disable' ? '禁用' : '归档'
  try {
    await ElMessageBox.confirm(`确认${label} BM「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    if (cmd === 'disable') await metaAccountApi.disable(row.id)
    else await metaAccountApi.archive(row.id)
    ElMessage.success(`已${label}`)
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

/** 跳到广告账户页并按该 BM 过滤 */
function goAccounts(row: MetaAccountItem) {
  router.push({ name: 'AdminAccounts', query: { business_id: row.id } })
}
/** 跳到凭据页，可带 BM 过滤 */
function goCredentials(row?: MetaAccountItem) {
  router.push({
    name: 'AdminCredentials',
    query: row ? { meta_account_id: row.id } : {},
  })
}
/** BM 详情页 */
function goDetail(row: MetaAccountItem) {
  router.push({ name: 'AdminBusinessDetail', params: { id: row.id } })
}

onMounted(load)
</script>

<style scoped>
.cred-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cred-mask {
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  color: #909399;
}
.sync-time {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.mb12 {
  margin-bottom: 12px;
}
</style>

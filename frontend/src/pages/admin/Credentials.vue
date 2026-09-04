<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">凭据与 Meta 授权</h2>
        <p class="page-subtitle">管理 BM 的 Meta Access Token，并通过 Meta OAuth 完成授权、权限校验和自动同步广告账户</p>
      </div>
      <div class="head-actions">
        <el-button type="success" :loading="authorizing" @click="startMetaAuth">Meta OAuth 授权</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">手工新增 Token</el-button>
      </div>
    </div>

    <el-alert v-if="authResult" :type="authResult.type" :closable="true" show-icon class="tip-alert" @close="clearAuthResult">
      <template #title>
        {{ authResult.message }}
        <span v-if="authResult.type === 'success'"> 授权成功后系统会自动异步同步该 BM 下的广告账户。</span>
      </template>
    </el-alert>

    <el-card class="card-shadow" shadow="never">
      <div class="toolbar">
        <el-select v-model="metaFilter" placeholder="选择授权/筛选 BM" clearable filterable style="width: 280px" @change="loadList">
          <el-option v-for="m in metas" :key="m.id" :label="`${m.name}（${m.business_id}）`" :value="m.id" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="凭据状态" clearable style="width: 150px" @change="loadList">
          <el-option label="生效" value="ACTIVE" />
          <el-option label="校验中" value="VERIFYING" />
          <el-option label="已过期" value="EXPIRED" />
          <el-option label="权限异常" value="INVALID" />
          <el-option label="已停用" value="DISABLED" />
        </el-select>
        <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
      </div>

      <el-table :data="list" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="凭据名称" min-width="170">
          <template #default="{ row }"><span>{{ row.name || '未命名凭据' }}</span></template>
        </el-table-column>
        <el-table-column label="所属 BM" min-width="190">
          <template #default="{ row }">
            <div>{{ row.meta_account_name || '-' }}</div>
            <div class="sub-text">{{ row.business_id || row.meta_account_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Token" min-width="180">
          <template #default="{ row }"><code class="token-mask">{{ row.access_token_masked || '***' }}</code></template>
        </el-table-column>
        <el-table-column label="来源 / 类型" width="170">
          <template #default="{ row }">
            <div><el-tag size="small" effect="plain">{{ row.token_type }}</el-tag></div>
            <div class="sub-text">{{ sourceLabel(row) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="125">
          <template #default="{ row }">
            <el-tooltip v-if="row.last_error" :content="row.last_error" placement="top">
              <el-tag :type="statusType(row)" effect="light" round>{{ statusLabel(row) }}</el-tag>
            </el-tooltip>
            <el-tag v-else :type="statusType(row)" effect="light" round>{{ statusLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="过期时间" width="170">
          <template #default="{ row }">
            <span v-if="!row.expires_at" class="sub-text">长期有效</span>
            <span v-else :class="{ 'text-danger': row.is_expired }">{{ formatTime(row.expires_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最近校验" width="170">
          <template #default="{ row }">{{ row.last_verified_at ? formatTime(row.last_verified_at) : '未校验' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <el-button link type="success" size="small" @click="reauthorize(row)">重新授权</el-button>
            <el-button link type="primary" size="small" :loading="verifyingId === row.id" @click="verifyOne(row)">校验</el-button>
            <el-button link type="warning" size="small" @click="openRotate(row)">轮换</el-button>
            <el-button link type="info" size="small" @click="revealOne(row)">明文</el-button>
            <el-button link :type="row.status === 'ACTIVE' ? 'danger' : 'success'" size="small" @click="toggleStatus(row)">
              {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无凭据，请先选择 BM 发起 Meta OAuth 授权" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="手工新增 Meta 凭据" width="560px" destroy-on-close>
      <el-alert type="info" :closable="false" show-icon class="mb12" title="推荐优先使用 Meta OAuth。手工 Token 仅用于系统用户等已有 Token 的场景。" />
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="所属 BM" required>
          <el-select v-model="createForm.meta_account_id" placeholder="选择 BM" filterable style="width:100%">
            <el-option v-for="m in metas" :key="m.id" :label="`${m.name}（${m.business_id}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="凭据名称"><el-input v-model="createForm.name" placeholder="例如：BM-A 系统用户" /></el-form-item>
        <el-form-item label="App ID"><el-input v-model="createForm.app_id" placeholder="可选" /></el-form-item>
        <el-form-item label="Access Token" required>
          <el-input v-model="createForm.access_token" type="textarea" :rows="3" show-password placeholder="服务端会加密存储" />
        </el-form-item>
        <el-form-item label="Token 类型">
          <el-select v-model="createForm.token_type" style="width:100%">
            <el-option label="USER（用户令牌）" value="USER" />
            <el-option label="SYSTEM_USER（系统用户）" value="SYSTEM_USER" />
            <el-option label="PAGE（主页令牌）" value="PAGE" />
          </el-select>
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker v-model="createForm.expires_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="留空表示长期有效" style="width:100%" />
        </el-form-item>
        <el-form-item label="停用旧凭据"><el-switch v-model="createForm.replace_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRotate" :title="`轮换 Token - ${current?.meta_account_name || ''}`" width="560px" destroy-on-close>
      <el-form :model="rotateForm" label-width="120px">
        <el-form-item label="凭据名称"><el-input v-model="rotateForm.name" placeholder="留空沿用原名称" /></el-form-item>
        <el-form-item label="新 Token" required><el-input v-model="rotateForm.access_token" type="textarea" :rows="3" show-password /></el-form-item>
        <el-form-item label="Token 类型">
          <el-select v-model="rotateForm.token_type" style="width:100%">
            <el-option label="USER（用户令牌）" value="USER" />
            <el-option label="SYSTEM_USER（系统用户）" value="SYSTEM_USER" />
            <el-option label="PAGE（主页令牌）" value="PAGE" />
          </el-select>
        </el-form-item>
        <el-form-item label="过期时间"><el-date-picker v-model="rotateForm.expires_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="留空表示长期有效" style="width:100%" /></el-form-item>
        <el-form-item label="保留旧凭据"><el-switch v-model="rotateForm.keep_old" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRotate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitRotate">确认轮换</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showReveal" title="查看明文 Token" width="560px">
      <el-alert type="warning" :closable="false" show-icon title="此操作会记录审计日志，请勿外传。" />
      <el-input :model-value="revealedToken" type="textarea" :rows="4" readonly class="reveal-box" />
      <template #footer><el-button @click="copyToken">复制</el-button><el-button type="primary" @click="showReveal = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { credentialApi, metaAccountApi, type CredentialItem, type MetaAccountItem } from '@/api/admin'

const route = useRoute()
const router = useRouter()
const list = ref<CredentialItem[]>([])
const metas = ref<MetaAccountItem[]>([])
const loading = ref(false)
const saving = ref(false)
const authorizing = ref(false)
const verifyingId = ref<string | null>(null)
const metaFilter = ref('')
const statusFilter = ref('')
const showCreate = ref(false)
const showRotate = ref(false)
const showReveal = ref(false)
const current = ref<CredentialItem | null>(null)
const revealedToken = ref('')
const authResult = ref<{ type: 'success' | 'error' | 'warning'; message: string } | null>(null)

const createForm = ref({ meta_account_id: '', access_token: '', name: '', app_id: '', token_type: 'USER', expires_at: '' as string | null, replace_active: true })
const rotateForm = ref({ access_token: '', name: '', token_type: 'USER', expires_at: '' as string | null, keep_old: true })

function formatTime(v: string | null) { return v ? v.replace('T', ' ').slice(0, 19) : '-' }
function sourceLabel(row: CredentialItem) { return row.name?.startsWith('Meta OAuth') ? 'Meta OAuth' : '手工/Token' }
function statusLabel(row: CredentialItem) {
  if (row.is_expired) return '已过期'
  return ({ ACTIVE: '生效', VERIFYING: '校验中', EXPIRED: '已过期', INVALID: '权限异常', DISABLED: '已停用' } as Record<string, string>)[row.status] || row.status
}
function statusType(row: CredentialItem): 'success' | 'danger' | 'warning' | 'info' {
  if (row.is_expired || row.status === 'EXPIRED') return 'danger'
  if (row.status === 'INVALID') return 'warning'
  if (row.status === 'ACTIVE') return 'success'
  return 'info'
}
function clearAuthResult() { authResult.value = null; router.replace({ path: route.path, query: {} }) }

function handleOAuthCallback() {
  const result = route.query.meta_auth
  const message = route.query.message
  if (result === 'success') authResult.value = { type: 'success', message: 'Meta OAuth 授权完成' }
  else if (result === 'error') authResult.value = { type: 'error', message: String(message || 'Meta OAuth 授权失败') }
  if (result) {
    window.setTimeout(() => router.replace({ path: route.path, query: {} }), 300)
  }
}

async function loadMetas() {
  try { const { data } = await metaAccountApi.list(); metas.value = data } catch { metas.value = [] }
}
async function loadList() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: 1, page_size: 100 }
    if (metaFilter.value) params.meta_account_id = metaFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const { data } = await credentialApi.list(params)
    list.value = data
  } finally { loading.value = false }
}
async function refreshAll() { await Promise.all([loadMetas(), loadList()]) }

async function startMetaAuth(metaId = metaFilter.value) {
  if (!metaId) { ElMessage.warning('请先选择要授权的 BM'); return }
  authorizing.value = true
  try {
    const { data } = await credentialApi.oauthAuthorize(metaId)
    if (!data?.authorization_url) throw new Error('后端未返回 Meta 授权地址')
    window.location.assign(data.authorization_url)
  } catch (e: any) {
    ElMessage.error(e?.message || '无法发起 Meta OAuth 授权')
  } finally { authorizing.value = false }
}
async function reauthorize(row: CredentialItem) { await startMetaAuth(row.meta_account_id || '') }

function openCreate() {
  createForm.value = { meta_account_id: metaFilter.value, access_token: '', name: '', app_id: '', token_type: 'USER', expires_at: null, replace_active: true }
  showCreate.value = true
}
async function submitCreate() {
  if (!createForm.value.meta_account_id || !createForm.value.access_token.trim()) { ElMessage.warning('请选择 BM 并填写 Access Token'); return }
  saving.value = true
  try { await credentialApi.create({ ...createForm.value }); ElMessage.success('凭据已创建'); showCreate.value = false; await refreshAll() } finally { saving.value = false }
}
function openRotate(row: CredentialItem) {
  current.value = row
  rotateForm.value = { access_token: '', name: row.name || '', token_type: row.token_type || 'USER', expires_at: row.expires_at, keep_old: true }
  showRotate.value = true
}
async function submitRotate() {
  if (!current.value || !rotateForm.value.access_token.trim()) { ElMessage.warning('请输入新的 Access Token'); return }
  saving.value = true
  try { await credentialApi.rotate(current.value.id, { ...rotateForm.value }); ElMessage.success('Token 已轮换'); showRotate.value = false; await loadList() } finally { saving.value = false }
}
async function verifyOne(row: CredentialItem) {
  verifyingId.value = row.id
  try {
    const { data } = await credentialApi.verify(row.id)
    if (data.valid) ElMessage.success('Meta 凭据校验通过')
    else ElMessage.error(data.error || '凭据校验失败')
    await loadList()
  } finally { verifyingId.value = null }
}
async function toggleStatus(row: CredentialItem) {
  const enable = row.status !== 'ACTIVE'
  await ElMessageBox.confirm(enable ? '确认启用该凭据？' : '确认停用该凭据？', enable ? '启用凭据' : '停用凭据', { type: enable ? 'info' : 'warning' })
  if (enable) await credentialApi.enable(row.id); else await credentialApi.disable(row.id)
  ElMessage.success(enable ? '凭据已启用' : '凭据已停用')
  await loadList()
}
async function remove(row: CredentialItem) {
  await ElMessageBox.confirm(`确认删除凭据「${row.name || row.id}」？删除后不可恢复。`, '删除凭据', { type: 'warning' })
  await credentialApi.remove(row.id); ElMessage.success('已删除'); await refreshAll()
}
async function revealOne(row: CredentialItem) {
  await ElMessageBox.confirm('明文 Token 属于高敏感凭据，此操作会记录审计日志。确认继续？', '安全确认', { type: 'warning', confirmButtonText: '继续查看' })
  const { data } = await credentialApi.reveal(row.id)
  revealedToken.value = data?.access_token || data?.token || ''
  if (!revealedToken.value) { ElMessage.warning('服务端未返回明文 Token'); return }
  showReveal.value = true
}
async function copyToken() {
  if (!revealedToken.value) return
  await navigator.clipboard.writeText(revealedToken.value)
  ElMessage.success('已复制')
}

onMounted(async () => { handleOAuthCallback(); await refreshAll() })
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.sub-text { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 3px; }
.token-mask { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.text-danger { color: var(--el-color-danger); }
.reveal-box { margin-top: 16px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.head-actions { display: flex; gap: 10px; }
.tip-alert { margin-bottom: 16px; }
</style>

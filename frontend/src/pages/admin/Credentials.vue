<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">凭据管理</h2>
        <p class="page-subtitle">
          Access Token 加密存储于凭据表，与 BM 主账号、广告账户分离管理；更换 Token 不影响账户主数据
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增凭据</el-button>
    </div>

    <el-alert type="info" :closable="false" show-icon class="tip-alert">
      <template #title>
        三层分离：BM 主账号（meta_accounts）→ 凭据（credentials，加密）→ 广告账户（ad_accounts）。
        列表默认只显示脱敏 Token，查看明文需二次确认并会记录审计日志。
      </template>
    </el-alert>

    <el-card class="card-shadow" shadow="never">
      <div class="toolbar">
        <el-select
          v-model="metaFilter"
          placeholder="按 BM 主账号筛选"
          clearable
          filterable
          style="width: 240px"
          @change="loadList"
        >
          <el-option v-for="m in metas" :key="m.id" :label="`${m.name}（${m.business_id}）`" :value="m.id" />
        </el-select>
        <el-select v-model="statusFilter" placeholder="状态" clearable style="width: 150px" @change="loadList">
          <el-option label="生效" value="ACTIVE" />
          <el-option label="已过期" value="EXPIRED" />
          <el-option label="权限异常" value="INVALID" />
          <el-option label="已停用" value="DISABLED" />
        </el-select>
        <el-button :icon="Refresh" @click="loadList">刷新</el-button>
      </div>

      <el-table :data="list" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="凭据名称" min-width="150">
          <template #default="{ row }">
            <span v-if="row.name">{{ row.name }}</span>
            <span v-else class="sub-text">未命名</span>
          </template>
        </el-table-column>
        <el-table-column label="所属 BM" min-width="180">
          <template #default="{ row }">
            <div>{{ row.meta_account_name || '-' }}</div>
            <div class="sub-text">{{ row.business_id || row.meta_account_id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="Token（脱敏）" min-width="160">
          <template #default="{ row }">
            <code class="token-mask">{{ row.access_token_masked || '***' }}</code>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="130">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.token_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
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
            <span v-else :class="{ 'text-danger': row.is_expired }">
              {{ formatTime(row.expires_at) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最近校验" width="170">
          <template #default="{ row }">
            <span v-if="!row.last_verified_at" class="sub-text">未校验</span>
            <span v-else>{{ formatTime(row.last_verified_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="verifyOne(row)">校验</el-button>
            <el-button link type="warning" size="small" @click="openRotate(row)">轮换</el-button>
            <el-button link type="info" size="small" @click="revealOne(row)">明文</el-button>
            <el-button
              link
              :type="row.status === 'ACTIVE' ? 'danger' : 'success'"
              size="small"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'ACTIVE' ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无凭据" />
        </template>
      </el-table>
    </el-card>

    <!-- 新增凭据 -->
    <el-dialog v-model="showCreate" title="新增凭据" width="560px" destroy-on-close>
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="所属 BM" required>
          <el-select v-model="createForm.meta_account_id" placeholder="选择 BM 主账号" filterable style="width: 100%">
            <el-option v-for="m in metas" :key="m.id" :label="`${m.name}（${m.business_id}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="凭据名称">
          <el-input v-model="createForm.name" placeholder="便于运维识别，如：主投凭据-BM-A" />
        </el-form-item>
        <el-form-item label="App ID">
          <el-input v-model="createForm.app_id" placeholder="可选，Meta App ID" />
        </el-form-item>
        <el-form-item label="Access Token" required>
          <el-input
            v-model="createForm.access_token"
            type="textarea"
            :rows="3"
            placeholder="粘贴 BM 的 Access Token，服务端加密后存储"
            show-password
          />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.token_type" style="width: 100%">
            <el-option label="USER（用户令牌）" value="USER" />
            <el-option label="SYSTEM_USER（系统用户）" value="SYSTEM_USER" />
            <el-option label="PAGE（主页令牌）" value="PAGE" />
          </el-select>
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker
            v-model="createForm.expires_at"
            type="datetime"
            placeholder="留空表示长期有效"
            style="width: 100%"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
        </el-form-item>
        <el-form-item label="停用旧凭据">
          <el-switch v-model="createForm.replace_active" />
          <span class="form-hint">开启后该 BM 现有的生效凭据会被置为「已停用」</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">保存</el-button>
      </template>
    </el-dialog>

    <!-- 轮换 Token -->
    <el-dialog v-model="showRotate" :title="`轮换 Token - ${current?.meta_account_name || ''}`" width="560px" destroy-on-close>
      <el-form :model="rotateForm" label-width="120px">
        <el-form-item label="凭据名称">
          <el-input
            v-model="rotateForm.name"
            :placeholder="current?.name ? `留空则沿用「${current.name}」` : '可选，便于运维识别'"
          />
        </el-form-item>
        <el-form-item label="新 Access Token" required>
          <el-input
            v-model="rotateForm.access_token"
            type="textarea"
            :rows="3"
            placeholder="粘贴新的 Access Token"
            show-password
          />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="rotateForm.token_type" style="width: 100%">
            <el-option label="USER（用户令牌）" value="USER" />
            <el-option label="SYSTEM_USER（系统用户）" value="SYSTEM_USER" />
            <el-option label="PAGE（主页令牌）" value="PAGE" />
          </el-select>
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker
            v-model="rotateForm.expires_at"
            type="datetime"
            placeholder="留空表示长期有效"
            style="width: 100%"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
        </el-form-item>
        <el-form-item label="保留旧凭据">
          <el-switch v-model="rotateForm.keep_old" />
          <span class="form-hint">保留为「已停用」，便于回溯</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRotate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitRotate">确认轮换</el-button>
      </template>
    </el-dialog>

    <!-- 明文查看 -->
    <el-dialog v-model="showReveal" title="查看明文 Token" width="560px">
      <el-alert type="warning" :closable="false" show-icon title="此操作已记录审计日志，请勿外传" />
      <el-input :model-value="revealedToken" type="textarea" :rows="4" readonly class="reveal-box" />
      <template #footer>
        <el-button @click="copyToken">复制</el-button>
        <el-button type="primary" @click="showReveal = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  credentialApi,
  metaAccountApi,
  type CredentialItem,
  type MetaAccountItem,
} from '@/api/admin'

const route = useRoute()
const list = ref<CredentialItem[]>([])
const metas = ref<MetaAccountItem[]>([])
const loading = ref(false)
const saving = ref(false)
const metaFilter = ref<string>('')
const statusFilter = ref<string>('')

const showCreate = ref(false)
const showRotate = ref(false)
const showReveal = ref(false)
const current = ref<CredentialItem | null>(null)
const revealedToken = ref('')

const createForm = ref({
  meta_account_id: '',
  access_token: '',
  name: '',
  app_id: '',
  token_type: 'USER',
  expires_at: '' as string | null,
  replace_active: true,
})
const rotateForm = ref({
  access_token: '',
  name: '',
  token_type: 'USER',
  expires_at: '' as string | null,
  keep_old: true,
})

function statusLabel(row: CredentialItem) {
  // 过期优先展示，避免"生效"与"已过期"同时命中造成误判
  if (row.is_expired) return '已过期'
  return (
    { ACTIVE: '生效', VERIFYING: '校验中', EXPIRED: '已过期', INVALID: '权限异常', DISABLED: '已停用' }[
      row.status
    ] || row.status
  )
}
function statusType(row: CredentialItem): 'success' | 'danger' | 'warning' | 'info' {
  if (row.is_expired || row.status === 'EXPIRED') return 'danger'
  if (row.status === 'INVALID') return 'warning'
  if (row.status === 'ACTIVE') return 'success'
  return 'info'
}
function formatTime(v: string | null) {
  if (!v) return '-'
  return v.replace('T', ' ').slice(0, 19)
}

async function loadMetas() {
  try {
    const { data } = await metaAccountApi.list()
    metas.value = data
  } catch {
    metas.value = []
  }
}

async function loadList() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: 1, page_size: 100 }
    if (metaFilter.value) params.meta_account_id = metaFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const { data } = await credentialApi.list(params)
    list.value = data
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    loading.value = false
  }
}

function openCreate() {
  createForm.value = {
    meta_account_id: '',
    access_token: '',
    name: '',
    app_id: '',
    token_type: 'USER',
    expires_at: null,
    replace_active: true,
  }
  showCreate.value = true
}

async function submitCreate() {
  if (!createForm.value.meta_account_id || !createForm.value.access_token) {
    ElMessage.warning('请选择 BM 并填写 Access Token')
    return
  }
  saving.value = true
  try {
    await credentialApi.create({
      meta_account_id: createForm.value.meta_account_id,
      access_token: createForm.value.access_token,
      name: createForm.value.name || undefined,
      app_id: createForm.value.app_id || undefined,
      token_type: createForm.value.token_type,
      expires_at: createForm.value.expires_at || null,
      replace_active: createForm.value.replace_active,
    })
    ElMessage.success('凭据已创建')
    showCreate.value = false
    await loadList()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

function openRotate(row: CredentialItem) {
  current.value = row
  rotateForm.value = {
    access_token: '',
    name: '', // 留空则沿用旧凭据名称（后端会继承）
    token_type: row.token_type,
    expires_at: row.expires_at,
    keep_old: true,
  }
  showRotate.value = true
}

async function submitRotate() {
  if (!current.value || !rotateForm.value.access_token) {
    ElMessage.warning('请填写新的 Access Token')
    return
  }
  saving.value = true
  try {
    await credentialApi.rotate(current.value.id, {
      access_token: rotateForm.value.access_token,
      name: rotateForm.value.name || undefined, // 留空则后端继承旧凭据名称
      token_type: rotateForm.value.token_type,
      expires_at: rotateForm.value.expires_at || null,
      keep_old: rotateForm.value.keep_old,
    })
    ElMessage.success('轮换成功')
    showRotate.value = false
    await loadList()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

async function verifyOne(row: CredentialItem) {
  try {
    const { data } = await credentialApi.verify(row.id)
    if (data.dev_mode) {
      ElMessage.warning('开发模式：未配置真实 FB 凭据，未做真实校验')
    } else if (data.valid) {
      ElMessage.success('校验通过，Token 有效')
    } else {
      ElMessage.error('校验失败：' + (data.error || 'Token 无效'))
    }
    await loadList()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function toggleStatus(row: CredentialItem) {
  const enabling = row.status !== 'ACTIVE'
  if (enabling && row.is_expired) {
    ElMessage.warning('凭据已过期，请改用「轮换」更换 Token')
    return
  }
  try {
    await ElMessageBox.confirm(`确认${enabling ? '启用' : '停用'}该凭据？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    if (enabling) await credentialApi.enable(row.id)
    else await credentialApi.disable(row.id)
    ElMessage.success('已' + (enabling ? '启用' : '停用'))
    await loadList()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function revealOne(row: CredentialItem) {
  try {
    await ElMessageBox.confirm(
      '查看明文 Token 会被记录到审计日志，确认继续？',
      '高危操作',
      { type: 'warning', confirmButtonText: '确认查看', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const { data } = await credentialApi.reveal(row.id)
    revealedToken.value = data.access_token
    showReveal.value = true
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(revealedToken.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}

async function remove(row: CredentialItem) {
  try {
    await ElMessageBox.confirm('确认删除该凭据？删除后该 BM 将无法调用 Meta API。', '警告', { type: 'error' })
  } catch {
    return
  }
  try {
    await credentialApi.remove(row.id)
    ElMessage.success('已删除')
    await loadList()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

onMounted(async () => {
  // 支持从主账号页跳转过来时按 BM 预筛选
  const q = route.query.meta_account_id
  if (typeof q === 'string' && q) metaFilter.value = q
  await loadMetas()
  await loadList()
})
</script>

<style scoped>
.tip-alert {
  margin-bottom: 16px;
}
.sub-text {
  font-size: 12px;
  color: #909399;
}
.token-mask {
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  color: #606266;
}
.text-danger {
  color: var(--el-color-danger);
}
.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}
.reveal-box {
  margin-top: 12px;
}
</style>

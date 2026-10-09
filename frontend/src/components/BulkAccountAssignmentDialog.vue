<template>
  <el-dialog v-model="visible" :title="`${title}（${config.account_ids.length} 个账户）`" width="min(1100px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @closed="reset">
    <div v-loading="loading">
      <template v-if="!results.length">
        <el-form label-width="120px" class="bulk-assignment-form" :disabled="saving || loading || previewing">
          <el-form-item label="目标投手" required>
            <el-select v-model="config.user_ids" multiple filterable placeholder="搜索并选择投手" style="width:100%">
              <el-option v-for="user in users" :key="user.id" :label="user.username" :value="user.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="action === 'PRIMARY'" label="新负责人" required>
            <el-select v-model="config.primary_user_id" placeholder="选择一名负责人" style="width:100%">
              <el-option v-for="user in users.filter(u => config.user_ids.includes(u.id))" :key="user.id" :label="user.username" :value="user.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="执行授权">
            <el-radio-group v-model="config.execution_mode">
              <el-radio v-if="action !== 'EXECUTION'" value="KEEP">保留现有设置</el-radio>
              <el-radio value="PERSONAL">本人 Meta 授权</el-radio>
              <el-radio value="DELEGATED">管理员委派</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="config.execution_mode === 'DELEGATED'">
            <el-form-item label="统一委派授权">
              <el-select v-model="config.execution_connection_id" clearable filterable placeholder="统一设置，或在下面按账户选择" style="width:100%">
                <el-option v-for="item in commonCandidates" :key="item.connection_id" :label="authorizationLabel(item)" :value="item.connection_id" />
              </el-select>
              <div class="hint">{{ commonCandidates.length ? '只展示能操作全部所选账户的授权；下方可为个别账户调整。' : '没有能覆盖全部账户的共同授权，请在下方逐账户选择。' }}</div>
            </el-form-item>
            <el-form-item label="已有有效委派"><el-switch v-model="config.preserve_existing_execution" active-text="保留" inactive-text="覆盖" /></el-form-item>
          </template>
        </el-form>
        <el-alert :title="action === 'COLLABORATOR' ? '添加协作者，保留原负责人和其他用户；账户没有有效负责人时，将在预览中指定一名目标投手。' : action === 'PRIMARY' ? '将所选账户交给新负责人，原负责人转为协作者，其他用户保留。' : '只更新目标投手已有分配的执行授权；尚未分配或只有只读权限的账户需先添加协作者。'" type="info" :closable="false" show-icon />
        <el-table :data="context" class="assignment-table" max-height="300">
          <el-table-column prop="account_name" label="账户" min-width="170" show-overflow-tooltip />
          <el-table-column label="当前负责人" width="140"><template #default="{ row }">{{ row.assignments.find((a: any) => a.effective && a.assignment_role === 'PRIMARY')?.username || '未分配' }}</template></el-table-column>
          <el-table-column v-if="config.execution_mode === 'DELEGATED'" label="账户授权例外" min-width="310">
            <template #default="{ row }">
              <el-select v-model="config.execution_overrides[row.account_id]" clearable filterable :disabled="!!row.error || saving || previewing || loading" :placeholder="config.execution_connection_id ? '使用统一授权' : '选择有效执行授权'" style="width:100%">
                <el-option v-for="item in row.candidates" :key="item.connection_id" :label="authorizationLabel(item)" :value="item.connection_id" />
              </el-select>
              <span v-if="!row.candidates.length" class="error">无有效候选，请先接入并同步账户</span>
            </template>
          </el-table-column>
          <el-table-column label="提示" min-width="200"><template #default="{ row }"><span v-if="row.error" class="error">{{ row.error }}</span><span v-else>{{ row.assignments.filter((a: any) => a.effective).length }} 名已分配用户</span></template></el-table-column>
        </el-table>
        <el-alert v-if="preview.length" :title="`可保存 ${ready.length} 个，需处理 ${preview.length - ready.length} 个；仅保存通过账户，其他账户保持原设置。`" :type="ready.length === preview.length ? 'success' : 'warning'" :closable="false" show-icon />
        <el-table v-if="preview.length" :data="preview" class="assignment-table" max-height="320">
          <el-table-column prop="account_name" label="变更预览 / 账户" min-width="160" />
          <el-table-column label="负责人" width="140"><template #default="{ row }">{{ row.primary_label || '-' }}<el-tag v-if="row.primary_changed" size="small" type="warning">变更</el-tag></template></el-table-column>
          <el-table-column label="目标投手 / 执行授权" min-width="280"><template #default="{ row }"><div v-for="item in row.assignments" :key="item.user_id">{{ item.username }}：{{ item.execution_label }}</div></template></el-table-column>
          <el-table-column label="校验结果" min-width="220"><template #default="{ row }"><span v-if="row.error" class="error">{{ row.error }}</span><template v-else><el-tag type="success" size="small">可保存</el-tag><div v-for="warning in row.warnings" :key="warning" class="hint">{{ warning }}</div></template></template></el-table-column>
        </el-table>
      </template>
      <template v-else>
        <el-alert :title="`成功 ${results.filter(x => x.status === 'SUCCESS').length} 个，失败 ${failed.length} 个`" :type="failed.length ? 'warning' : 'success'" :closable="false" show-icon />
        <el-table :data="results" class="assignment-table" max-height="450">
          <el-table-column prop="account_name" label="账户" min-width="170" />
          <el-table-column label="结果" width="100"><template #default="{ row }"><el-tag :type="row.status === 'SUCCESS' ? 'success' : 'danger'">{{ row.status === 'SUCCESS' ? '成功' : '失败' }}</el-tag></template></el-table-column>
          <el-table-column label="说明" min-width="320"><template #default="{ row }">{{ row.error || `负责人：${row.primary_label || '-'}；分配已保存` }}</template></el-table-column>
        </el-table>
      </template>
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="visible = false">{{ results.length ? '完成' : '取消' }}</el-button>
      <template v-if="!results.length">
        <el-button :disabled="loading || saving" :loading="previewing" @click="makePreview">预览分配</el-button>
        <el-button type="primary" :disabled="!ready.length || loading || previewing" :loading="saving" @click="submit">{{ ready.length < preview.length ? `仅保存通过账户（${ready.length}）` : `保存分配（${ready.length}）` }}</el-button>
      </template>
      <template v-else-if="failed.length">
        <el-button :disabled="saving" @click="editFailed">修改失败项</el-button>
        <el-button type="primary" :loading="saving" @click="retryFailed">重试失败项（{{ failed.length }}）</el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { accountApi, type AdAccountItem, type BulkAssignmentAction, type BulkAssignmentConfig, type AssignmentContextItem, type BulkAssignmentResult, type ExecutionAuthorization } from '@/api/admin'

const props = defineProps<{ modelValue: boolean; accounts: AdAccountItem[]; action: BulkAssignmentAction }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const visible = computed({ get: () => props.modelValue, set: value => emit('update:modelValue', value) })
const title = computed(() => ({ COLLABORATOR: '批量添加协作者', PRIMARY: '批量变更负责人', EXECUTION: '批量设置执行授权' })[props.action])
const loading = ref(false)
const previewing = ref(false)
const saving = ref(false)
const users = ref<Array<{ id: string; username: string }>>([])
const context = ref<AssignmentContextItem[]>([])
const preview = ref<BulkAssignmentResult[]>([])
const results = ref<BulkAssignmentResult[]>([])
const ready = computed(() => preview.value.filter(x => x.status === 'READY'))
const failed = computed(() => results.value.filter(x => x.status === 'FAILED'))
const config = reactive<BulkAssignmentConfig>({ account_ids: [], user_ids: [], action: 'COLLABORATOR', execution_mode: 'KEEP', execution_overrides: {}, preserve_existing_execution: true })
const commonCandidates = computed(() => context.value.length ? context.value[0].candidates.filter(c => context.value.every(row => row.candidates.some(x => x.connection_id === c.connection_id))) : [])
const authorizationLabel = (c: ExecutionAuthorization) => `${c.authorized_by_username} · Meta ${c.meta_user_id} · ${c.page_count} 个 Page`
let key = ''
let approved: BulkAssignmentConfig | null = null
let loadNo = 0
const newKey = () => window.crypto?.randomUUID?.() || `assignment-${Date.now()}-${Math.random().toString(36).slice(2)}`
const cloneConfig = (): BulkAssignmentConfig => {
  const copy = JSON.parse(JSON.stringify(config))
  copy.execution_overrides = Object.fromEntries(Object.entries(copy.execution_overrides).filter(([, value]) => value))
  return copy
}
function reset() { ++loadNo; preview.value = []; results.value = []; approved = null; previewing.value = false }
watch(config, () => { preview.value = []; approved = null }, { deep: true })
watch(() => config.user_ids, ids => {
  if (!ids.includes(config.primary_user_id || '')) config.primary_user_id = props.action === 'PRIMARY' && ids.length === 1 ? ids[0] : undefined
}, { deep: true })
watch(() => config.execution_mode, mode => {
  if (mode === 'DELEGATED' && !config.execution_connection_id) {
    const common = commonCandidates.value
    if (common.length === 1) config.execution_connection_id = common[0].connection_id
    else for (const row of context.value) if (row.candidates.length === 1 && !config.execution_overrides[row.account_id]) config.execution_overrides[row.account_id] = row.candidates[0].connection_id
  }
})
watch(() => props.modelValue, async show => {
  if (!show) return
  const current = ++loadNo
  Object.assign(config, { account_ids: props.accounts.map(a => a.id), user_ids: [], action: props.action,
    primary_user_id: undefined, execution_mode: props.action === 'EXECUTION' ? 'DELEGATED' : 'KEEP', execution_connection_id: undefined, execution_overrides: {}, preserve_existing_execution: true })
  preview.value = []; results.value = []; context.value = []; users.value = []; approved = null
  key = newKey()
  loading.value = true
  try {
    const { data } = await accountApi.assignmentContext(config.account_ids)
    if (current !== loadNo) return
    context.value = data.items; users.value = data.users
    if (props.action === 'EXECUTION') {
      if (commonCandidates.value.length === 1) config.execution_connection_id = commonCandidates.value[0].connection_id
      else for (const row of context.value) if (row.candidates.length === 1) config.execution_overrides[row.account_id] = row.candidates[0].connection_id
    }
  } catch { ElMessage.error('无法读取账户分配信息，请关闭后重试') }
  finally { if (current === loadNo) loading.value = false }
})

function valid() {
  if (!config.user_ids.length) { ElMessage.warning('请选择目标投手'); return false }
  if (props.action === 'PRIMARY' && !config.user_ids.includes(config.primary_user_id || '')) { ElMessage.warning('请选择一名新负责人'); return false }
  return true
}
async function makePreview() {
  if (!valid()) return
  const current = loadNo
  const payload = cloneConfig()
  previewing.value = true
  try {
    const { data } = await accountApi.previewAssignment(payload)
    if (!visible.value || current !== loadNo || JSON.stringify(payload) !== JSON.stringify(cloneConfig())) return
    preview.value = data.items; approved = payload
    key = newKey()
  } finally { if (current === loadNo) previewing.value = false }
}
async function send(payload: BulkAssignmentConfig, rows: BulkAssignmentResult[]) {
  return accountApi.submitAssignment({ ...payload, account_ids: rows.map(x => x.account_id),
    execution_overrides: Object.fromEntries(Object.entries(payload.execution_overrides).filter(([id]) => rows.some(x => x.account_id === id))),
    idempotency_key: key, preview_hashes: Object.fromEntries(rows.map(x => [x.account_id, x.preview_hash || preview.value.find(p => p.account_id === x.account_id)?.preview_hash || ''])) })
}
async function submit() {
  if (!approved || !ready.value.length) return
  saving.value = true
  try {
    const { data } = await send(approved, ready.value)
    results.value = [...data.items, ...preview.value.filter(x => x.status === 'BLOCKED').map(x => ({ ...x, status: 'FAILED' as const }))]
    if (data.success_count) emit('saved')
  } finally { saving.value = false }
}
async function retryFailed() {
  if (!approved || !failed.value.length) return
  saving.value = true
  try {
    const { data } = await send(approved, failed.value)
    const changed = new Map(data.items.map(x => [x.account_id, x]))
    results.value = results.value.map(x => changed.get(x.account_id) || x)
    if (data.success_count) emit('saved')
  } finally { saving.value = false }
}
function editFailed() {
  const ids = failed.value.map(x => x.account_id)
  config.account_ids = ids
  config.execution_overrides = Object.fromEntries(Object.entries(config.execution_overrides).filter(([id]) => ids.includes(id)))
  context.value = context.value.filter(x => ids.includes(x.account_id))
  results.value = []; preview.value = []; approved = null
}
</script>

<style scoped>
.bulk-assignment-form { margin-bottom: 16px; }
.assignment-table { margin: 16px 0; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
.error { color: var(--el-color-danger); }
</style>

<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">广告账户</h2>
        <p class="page-subtitle">
          维护 BM 下的广告账户资源池。Meta 状态由同步覆盖，系统状态决定是否参与批量投放
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建账户</el-button>
    </div>

    <el-card class="card-shadow" shadow="never">
      <div class="toolbar">
        <el-input
          v-model="search"
          placeholder="搜索账户名 / ID"
          clearable
          style="width: 220px"
          :prefix-icon="Search"
          @input="debouncedLoad"
        />
        <el-select v-model="systemStatusFilter" placeholder="系统状态" clearable style="width: 140px" @change="loadAccounts">
          <el-option label="可投放" value="ACTIVE" />
          <el-option label="已停用" value="DISABLED" />
        </el-select>
        <el-select v-model="accountStatusFilter" placeholder="Meta 状态" clearable style="width: 140px" @change="loadAccounts">
          <el-option label="正常" value="1" />
          <el-option label="已禁用" value="2" />
          <el-option label="未结算" value="3" />
        </el-select>
        <el-select v-model="businessFilter" placeholder="归属 BM" clearable filterable style="width: 230px" @change="loadAccounts">
          <el-option v-for="m in businesses" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-button :icon="Refresh" @click="loadAccounts">刷新</el-button>
      </div>

      <div v-if="selected.length" class="bulk-bar">
        <span class="bulk-tip">已选 {{ selected.length }} 个账户</span>
        <el-button size="small" type="warning" @click="bulkAction('freeze')">批量停用</el-button>
        <el-button size="small" type="success" @click="bulkAction('unfreeze')">批量启用</el-button>
        <el-button size="small" type="primary" @click="openBulkTransfer">批量转移归属</el-button>
        <el-button size="small" type="danger" @click="bulkAction('delete')">批量删除</el-button>
        <el-button size="small" link @click="clearSelection">取消选择</el-button>
      </div>

      <el-table
        :data="accounts"
        v-loading="loading"
        stripe
        style="width: 100%"
        ref="tableRef"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="46" />
        <el-table-column prop="account_name" label="账户名" min-width="140" />
        <el-table-column prop="account_id" label="账户 ID" min-width="140" />
        <el-table-column label="归属 BM" min-width="150">
          <template #default="{ row }">
            <span v-if="row.business_name">{{ row.business_name }}</span>
            <el-tag v-else type="info" size="small" effect="plain">未归属</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="系统状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.system_status === 'ACTIVE' ? 'success' : 'danger'" effect="light" round>
              <span class="status-dot" :class="row.system_status === 'ACTIVE' ? 'on' : 'off'"></span>
              {{ row.system_status === 'ACTIVE' ? '可投放' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Meta 状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.account_status" :type="metaStatusType(row.account_status)" effect="plain" size="small">
              {{ metaStatusLabel(row.account_status) }}
            </el-tag>
            <span v-else class="sub-text">未同步</span>
          </template>
        </el-table-column>
        <el-table-column label="风险分" width="100">
          <template #default="{ row }">
            <el-tag :type="riskType(row.risk_score)" effect="light">{{ row.risk_score }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="日限额" min-width="120">
          <template #default="{ row }">{{ formatMoney(row.daily_spend_limit, row.currency) }}</template>
        </el-table-column>
        <el-table-column label="月限额" min-width="120">
          <template #default="{ row }">{{ formatMoney(row.monthly_spend_limit, row.currency) }}</template>
        </el-table-column>
        <el-table-column label="已消费" min-width="120">
          <template #default="{ row }">{{ formatMoney(row.amount_spent, row.currency) }}</template>
        </el-table-column>
        <el-table-column label="分配用户" width="90">
          <template #default="{ row }">{{ userCount[row.id] ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="330" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openTransfer(row)">转移归属</el-button>
            <el-button link type="primary" size="small" @click="openAssign(row)">分配</el-button>
            <el-button link type="info" size="small" @click="openUsers(row)">用户</el-button>
            <el-button link type="warning" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link :type="row.system_status === 'ACTIVE' ? 'danger' : 'success'" size="small" @click="toggleStatus(row)">
              {{ row.system_status === 'ACTIVE' ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无账户" />
        </template>
      </el-table>
    </el-card>

    <!-- 新建/编辑 -->
    <el-dialog v-model="showForm" :title="form.id ? '编辑账户' : '新建账户'" width="480px" destroy-on-close>
      <el-form :model="form" label-width="100px">
        <el-form-item label="归属 BM" required>
          <el-select v-model="form.business_id" placeholder="选择归属 BM" filterable style="width: 100%">
            <el-option v-for="m in businesses" :key="m.id" :label="`${m.name}（${m.business_id}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="账户 ID" required>
          <el-input v-model="form.account_id" placeholder="act_123456" :disabled="!!form.id" />
        </el-form-item>
        <el-form-item label="账户名称">
          <el-input v-model="form.account_name" />
        </el-form-item>
        <el-form-item label="系统状态">
          <el-select v-model="form.system_status" style="width: 100%">
            <el-option label="可投放" value="ACTIVE" />
            <el-option label="已停用" value="DISABLED" />
          </el-select>
        </el-form-item>
        <el-form-item label="币种">
          <el-input v-model="form.currency" placeholder="USD" />
        </el-form-item>
        <el-form-item label="日限额">
          <el-input-number v-model="dailyLimitMajor" :min="0" :step="10" style="width: 100%" />
          <span class="form-hint">{{ form.currency || 'USD' }}（主单位，提交时自动换算为分）</span>
        </el-form-item>
        <el-form-item label="月限额">
          <el-input-number v-model="monthlyLimitMajor" :min="0" :step="100" style="width: 100%" />
          <span class="form-hint">{{ form.currency || 'USD' }}（主单位，提交时自动换算为分）</span>
        </el-form-item>
        <el-form-item label="风险分">
          <el-slider v-model="form.risk_score" :min="0" :max="1" :step="0.01" show-input />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 转移归属 -->
    <el-dialog
      v-model="showTransfer"
      :title="transferBulk ? `批量转移归属（${selected.length} 个账户）` : `转移归属 - ${transferRow?.account_id || ''}`"
      width="480px"
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="默认会调用 Meta 校验账户确实在目标 BM 下，避免挂错 BM 导致用错 Token"
        class="mb12"
      />
      <el-form label-width="90px">
        <el-form-item label="目标 BM" required>
          <el-select v-model="transferTarget" placeholder="选择目标 BM" filterable style="width: 100%">
            <el-option v-for="m in businesses" :key="m.id" :label="`${m.name}（${m.business_id}）`" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="跳过校验">
          <el-switch v-model="transferSkipVerify" />
          <span class="form-hint">仅在 BM 凭据失效无法调用 Meta 时开启</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showTransfer = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitTransfer">确认转移</el-button>
      </template>
    </el-dialog>

    <!-- 分配用户 -->
    <el-dialog v-model="showAssign" :title="`分配用户 - ${assignAccount?.account_name || assignAccount?.account_id}`" width="420px" destroy-on-close>
      <el-checkbox-group v-model="selectedUsers" class="user-group">
        <el-checkbox v-for="u in allUsers" :key="u.id" :value="u.id" border class="user-check">
          {{ u.username }} ({{ u.email }})
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="showAssign = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAssign">保存分配</el-button>
      </template>
    </el-dialog>

    <!-- 已分配用户 -->
    <el-dialog v-model="showUsers" :title="`已分配用户 - ${userAccount?.account_name || userAccount?.account_id}`" width="420px" destroy-on-close>
      <el-table :data="assignedList" style="width: 100%">
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="email" label="邮箱" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="removeUser(row)">移除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无分配用户" /></template>
      </el-table>
      <template #footer>
        <el-button @click="showUsers = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import {
  accountApi,
  metaAccountApi,
  userApi,
  type AdAccountItem,
  type AdminUser,
  type AccountUser,
  type MetaAccountItem,
} from '@/api/admin'
import { formatMoney, toMajor, toMinor } from '@/utils/money'

const route = useRoute()

const accounts = ref<AdAccountItem[]>([])
const loading = ref(false)
const search = ref('')
const systemStatusFilter = ref('')
const accountStatusFilter = ref('')
const businessFilter = ref('')
const businesses = ref<MetaAccountItem[]>([])
const userCount = ref<Record<string, number>>({})
const tableRef = ref<any>(null)
const selected = ref<AdAccountItem[]>([])

const showForm = ref(false)
const saving = ref(false)
const form = ref<Partial<AdAccountItem>>({
  account_id: '', currency: 'USD', system_status: 'ACTIVE',
  daily_spend_limit: 0, monthly_spend_limit: 0, risk_score: 0,
})
// 表单按主单位（元）编辑，提交时换算为分
const dailyLimitMajor = ref(0)
const monthlyLimitMajor = ref(0)

const showTransfer = ref(false)
const transferRow = ref<AdAccountItem | null>(null)
const transferBulk = ref(false)
const transferTarget = ref<string>('')
const transferSkipVerify = ref(false)

const showAssign = ref(false)
const assignAccount = ref<AdAccountItem | null>(null)
const allUsers = ref<AdminUser[]>([])
const selectedUsers = ref<string[]>([])

const showUsers = ref(false)
const userAccount = ref<AdAccountItem | null>(null)
const assignedList = ref<AccountUser[]>([])

let timer: number | undefined
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(loadAccounts, 300) as unknown as number
}

/** Meta account_status：Graph API 返回数字，也可能返回枚举名 */
function metaStatusLabel(v: string) {
  return (
    {
      '1': '正常', '2': '已禁用', '3': '未结算', '7': '风险审核中',
      '8': '待结算', '9': '宽限期', '100': '待关闭', '101': '已关闭',
      ACTIVE: '正常', DISABLED: '已禁用', UNSETTLED: '未结算',
    }[v] || v
  )
}
function metaStatusType(v: string): 'success' | 'danger' | 'warning' | 'info' {
  if (v === '1' || v === 'ACTIVE') return 'success'
  if (v === '2' || v === 'DISABLED' || v === '101') return 'danger'
  if (v === '3' || v === '7' || v === '8' || v === '100') return 'warning'
  return 'info'
}
function riskType(score?: number): 'success' | 'warning' | 'danger' {
  const s = score ?? 0
  if (s >= 0.7) return 'danger'
  if (s >= 0.4) return 'warning'
  return 'success'
}

async function loadBusinesses() {
  try {
    const { data } = await metaAccountApi.list()
    businesses.value = data
  } catch {
    businesses.value = []
  }
}

async function loadAccounts() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: 1, page_size: 100 }
    if (search.value) params.search = search.value
    if (systemStatusFilter.value) params.system_status = systemStatusFilter.value
    if (accountStatusFilter.value) params.account_status = accountStatusFilter.value
    if (businessFilter.value) params.business_id = businessFilter.value

    const { data } = await accountApi.list(params)
    accounts.value = data

    const counts: Record<string, number> = {}
    await Promise.all(
      data.map(async (a) => {
        try {
          const r = await accountApi.users(a.id)
          counts[a.id] = r.data.length
        } catch {
          counts[a.id] = 0
        }
      })
    )
    userCount.value = counts
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    loading.value = false
  }
}

function onSelectionChange(rows: AdAccountItem[]) {
  selected.value = rows
}
function clearSelection() {
  tableRef.value?.clearSelection()
}

function openCreate() {
  form.value = {
    account_id: '', currency: 'USD', system_status: 'ACTIVE',
    daily_spend_limit: 0, monthly_spend_limit: 0, risk_score: 0, business_id: '',
  }
  dailyLimitMajor.value = 0
  monthlyLimitMajor.value = 0
  showForm.value = true
}
function openEdit(a: AdAccountItem) {
  form.value = { ...a }
  dailyLimitMajor.value = toMajor(a.daily_spend_limit, a.currency)
  monthlyLimitMajor.value = toMajor(a.monthly_spend_limit, a.currency)
  showForm.value = true
}
async function save() {
  if (!form.value.business_id) {
    ElMessage.warning('请选择归属 BM')
    return
  }
  if (!form.value.account_id) {
    ElMessage.warning('请填写账户 ID')
    return
  }
  saving.value = true
  try {
    const payload = {
      ...form.value,
      // 表单是主单位，接口要最小单位
      daily_spend_limit: toMinor(dailyLimitMajor.value, form.value.currency),
      monthly_spend_limit: toMinor(monthlyLimitMajor.value, form.value.currency),
    }
    if (form.value.id) {
      const { id, ...rest } = payload as any
      await accountApi.update(id, rest)
    } else {
      await accountApi.create(payload as any)
    }
    showForm.value = false
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

// ---------- 转移归属 ----------
function openTransfer(a: AdAccountItem) {
  transferBulk.value = false
  transferRow.value = a
  transferTarget.value = ''
  transferSkipVerify.value = false
  showTransfer.value = true
}
function openBulkTransfer() {
  if (!selected.value.length) return
  transferBulk.value = true
  transferRow.value = null
  transferTarget.value = ''
  transferSkipVerify.value = false
  showTransfer.value = true
}
async function submitTransfer() {
  if (!transferTarget.value) {
    ElMessage.warning('请选择目标 BM')
    return
  }
  saving.value = true
  try {
    if (transferBulk.value) {
      const { data } = await accountApi.bulk({
        action: 'transfer',
        account_ids: selected.value.map((a) => a.id),
        business_id: transferTarget.value,
        skip_verification: transferSkipVerify.value,
      })
      if (data.failed_count) {
        ElMessage.warning(`成功 ${data.success_count} 个，失败 ${data.failed_count} 个：${data.errors?.[0]?.error || ''}`)
      } else {
        ElMessage.success(`已转移 ${data.success_count} 个账户`)
      }
      clearSelection()
    } else if (transferRow.value) {
      await accountApi.transfer(transferRow.value.id, {
        business_id: transferTarget.value,
        skip_verification: transferSkipVerify.value,
      })
      ElMessage.success('归属已更新')
    }
    showTransfer.value = false
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

// ---------- 批量操作 ----------
async function bulkAction(action: 'freeze' | 'unfreeze' | 'delete') {
  if (!selected.value.length) return
  const label = { freeze: '停用', unfreeze: '启用', delete: '删除' }[action]
  if (action === 'delete') {
    try {
      await ElMessageBox.confirm(`确认删除选中的 ${selected.value.length} 个账户？`, '警告', { type: 'error' })
    } catch {
      return
    }
  }
  try {
    const { data } = await accountApi.bulk({
      action,
      account_ids: selected.value.map((a) => a.id),
      reason: action === 'freeze' ? '批量停用' : undefined,
    })
    if (data.failed_count) {
      ElMessage.warning(`成功 ${data.success_count} 个，失败 ${data.failed_count} 个：${data.errors?.[0]?.error || ''}`)
    } else {
      ElMessage.success(`已${label} ${data.success_count} 个账户`)
    }
    clearSelection()
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function toggleStatus(a: AdAccountItem) {
  const disabling = a.system_status === 'ACTIVE'
  try {
    await ElMessageBox.confirm(`确认${disabling ? '停用' : '启用'}账户 ${a.account_id}？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    if (disabling) await accountApi.freeze(a.id, '管理员停用')
    else await accountApi.unfreeze(a.id)
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}
async function remove(a: AdAccountItem) {
  try {
    await ElMessageBox.confirm(`确认删除账户 ${a.account_id}？`, '警告', { type: 'error' })
  } catch {
    return
  }
  try {
    await accountApi.delete(a.id)
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function openAssign(a: AdAccountItem) {
  assignAccount.value = a
  selectedUsers.value = []
  try {
    const { data } = await userApi.list({ page: 1, page_size: 100 })
    allUsers.value = data
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
    return
  }
  showAssign.value = true
}
async function saveAssign() {
  if (!assignAccount.value || selectedUsers.value.length === 0) {
    ElMessage.warning('请选择至少一个用户')
    return
  }
  saving.value = true
  try {
    await accountApi.assign(assignAccount.value.id, selectedUsers.value)
    showAssign.value = false
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

async function openUsers(a: AdAccountItem) {
  userAccount.value = a
  try {
    const { data } = await accountApi.users(a.id)
    assignedList.value = data
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
    return
  }
  showUsers.value = true
}
async function removeUser(u: AccountUser) {
  if (!userAccount.value) return
  try {
    await accountApi.unassign(userAccount.value.id, [u.user_id])
    assignedList.value = assignedList.value.filter((x) => x.user_id !== u.user_id)
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

onMounted(async () => {
  // 支持从 BM 详情页跳转过来时按 BM 预筛选
  const q = route.query.business_id
  if (typeof q === 'string' && q) businessFilter.value = q
  await loadBusinesses()
  await nextTick()
  await loadAccounts()
})
</script>

<style scoped>
.bulk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--el-color-primary-light-9);
  border-radius: 8px;
}
.bulk-tip {
  font-size: 13px;
  color: var(--el-color-primary);
  margin-right: 4px;
}
.sub-text {
  color: #9ca3af;
  font-size: 12px;
}
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.status-dot.on {
  background: var(--success);
}
.status-dot.off {
  background: var(--danger);
}
.user-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.user-check {
  width: 100%;
  margin-right: 0;
}
.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}
.mb12 {
  margin-bottom: 12px;
}
</style>

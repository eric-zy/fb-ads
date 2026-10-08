<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">广告账户管理与分配</h2>
        <p class="page-subtitle">
          维护 BM 下的广告账户资源池。Meta 状态由同步覆盖，系统状态决定是否参与批量投放
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建账户</el-button>
    </div>

    <el-card class="card-shadow" shadow="never">
      <el-alert class="assignment-guide" title="分配给投手：找到广告账户，点击右侧「分配给投手」，勾选用户并指定主投手后保存。查看或移除协作者请点击「已分配用户」。待导入账户需先从 BM 导入。" type="info" :closable="false" show-icon />
      <el-alert v-if="pendingScanErrors.length" class="assignment-guide" type="warning" :closable="false" show-icon title="部分 BM 扫描失败，当前待导入列表不完整">
        <div v-for="(item, index) in pendingScanErrors" :key="index">{{ item.business_name }}：{{ item.error }}</div>
      </el-alert>
      <div class="toolbar">
        <el-radio-group v-model="assetFilter" size="small" @change="resetAccountPage">
          <el-radio-button label="ALL">全部</el-radio-button>
          <el-radio-button label="OWNED">自有账户</el-radio-button>
          <el-radio-button label="CLIENT">客户账户</el-radio-button>
          <el-radio-button label="PENDING">待导入</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="search"
          placeholder="搜索账户名 / ID"
          clearable
          style="width: 220px"
          :prefix-icon="Search"
          @input="debouncedLoad"
        />
        <el-select v-model="systemStatusFilter" placeholder="系统状态" clearable style="width: 140px" @change="resetAccountPage">
          <el-option label="可投放" value="ACTIVE" />
          <el-option label="已停用" value="DISABLED" />
        </el-select>
        <el-select v-model="accountStatusFilter" placeholder="Meta 状态" clearable style="width: 140px" @change="resetAccountPage">
          <el-option label="正常" value="1" />
          <el-option label="已禁用" value="2" />
          <el-option label="未结算" value="3" />
        </el-select>
        <el-select v-model="businessFilter" placeholder="归属 BM" clearable filterable style="width: 230px" @change="resetAccountPage">
          <el-option v-for="m in businesses" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <el-button :icon="Refresh" @click="loadAccounts">刷新</el-button>
      </div>

      <div v-if="selected.length" class="bulk-bar">
        <span class="bulk-tip">已选 {{ selected.length }} 个账户</span>
        <el-button size="small" type="warning" @click="bulkAction('freeze')">批量停用</el-button>
        <el-button size="small" type="success" @click="bulkAction('unfreeze')">批量启用</el-button>
        <el-button size="small" type="primary" @click="openBulkTransfer">批量转移归属</el-button>
        <el-button size="small" type="primary" :loading="syncing" @click="bulkSync">批量同步</el-button>
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
        <el-table-column v-if="assetFilter !== 'PENDING'" type="selection" width="46" />
        <el-table-column prop="account_name" label="账户名" min-width="140" />
        <el-table-column prop="account_id" label="账户 ID" min-width="140" />
        <el-table-column label="归属 BM" min-width="150">
          <template #default="{ row }">
            <span v-if="row.business_name">{{ row.business_name }}</span>
            <el-tag v-else type="info" size="small" effect="plain">未归属</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="资产类型" width="110">
          <template #default="{ row }">
            <el-tag v-if="assetType(row as TableRow<typeof accounts>) === 'OWNED'" type="success" effect="plain" size="small">自有</el-tag>
            <el-tag v-else type="warning" effect="plain" size="small">客户</el-tag>
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
          <template #default="{ row }">{{ formatMoney(row.daily_spend_limit,row.currency) }}</template>
        </el-table-column>
        <el-table-column label="月限额" min-width="120">
          <template #default="{ row }">{{ formatMoney(row.monthly_spend_limit,row.currency) }}</template>
        </el-table-column>
        <el-table-column label="已消费" min-width="120">
          <template #default="{ row }">{{ formatMoney(row.amount_spent,row.currency) }}</template>
        </el-table-column>
        <el-table-column label="分配用户" width="90">
          <template #default="{ row }">{{ userCount[row.id] ?? '-' }}</template>
        </el-table-column>
        <el-table-column v-if="assetFilter !== 'PENDING'" label="操作" width="470" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" plain size="small" @click="openAssign(row as TableRow<typeof accounts>)">分配给投手</el-button>
            <el-button link type="primary" size="small" @click="goDetail(row as TableRow<typeof accounts>)">详情</el-button>
            <el-button link type="primary" size="small" @click="openTransfer(row as TableRow<typeof accounts>)">转移归属</el-button>
            <el-button link type="info" size="small" @click="openUsers(row as TableRow<typeof accounts>)">已分配用户</el-button>
            <el-button link type="warning" size="small" @click="openEdit(row as TableRow<typeof accounts>)">编辑</el-button>
            <el-button link :type="row.system_status === 'ACTIVE' ? 'danger' : 'success'" size="small" @click="toggleStatus(row as TableRow<typeof accounts>)">
              {{ row.system_status === 'ACTIVE' ? '停用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row as TableRow<typeof accounts>)">删除</el-button>
          </template>
        </el-table-column>
        <el-table-column v-else label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openPendingBm(row as TableRow<typeof accounts>)">去 BM 导入</el-button>
          </template>
        </el-table-column>
        <template #empty>
        <el-empty :description="assetFilter === 'PENDING' ? '暂无待导入账户' : '暂无账户'">
            <el-button v-if="assetFilter === 'PENDING'" type="primary" :loading="loading" @click="loadAccounts">重新扫描 Meta</el-button>
            <el-button v-if="assetFilter === 'PENDING'" @click="goMetaAccounts">打开 BM 管理</el-button>
          </el-empty>
        </template>
      </el-table>
      <el-pagination v-if="assetFilter !== 'PENDING' && accountTotal > accountPageSize" v-model:current-page="accountPage" :page-size="accountPageSize" :total="accountTotal" layout="total, prev, pager, next" style="justify-content:flex-end;margin-top:16px" @current-change="loadAccounts" />
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
    <el-dialog v-model="showAssign" :title="`分配给投手 - ${assignAccount?.account_name || assignAccount?.account_id}`" width="620px" destroy-on-close>
      <p class="assignment-hint">勾选需要使用此账户的用户，再选择一名主投手。</p>
      <el-checkbox-group v-model="selectedUsers" class="user-group">
        <el-checkbox v-for="u in allUsers" :key="u.id" :value="u.id" border class="user-check">
          {{ u.username }}<span v-if="u.email"> ({{ u.email }})</span>
        </el-checkbox>
      </el-checkbox-group>
      <el-form label-width="128px" class="primary-form">
        <el-form-item label="主投手">
          <el-select v-model="primaryUserId" placeholder="选择主投手" style="width: 100%" :disabled="!selectedUsers.length">
            <el-option v-for="u in allUsers.filter((item) => selectedUsers.includes(item.id))" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-form label-width="128px">
        <el-form-item label="执行方式">
          <el-select v-model="executionMode" style="width:100%">
            <el-option label="保留当前设置" value="KEEP" />
            <el-option label="本人 Meta 授权" value="PERSONAL" />
            <el-option label="管理员委派授权" value="DELEGATED" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="executionMode === 'DELEGATED'" label="执行 Meta 授权" required>
          <el-select v-model="executionConnectionId" style="width:100%" placeholder="选择可操作此账户的有效 Meta 授权">
            <el-option v-for="item in executionAuthorizations" :key="item.connection_id" :value="item.connection_id" :label="`${item.authorized_by_username} · Meta ${item.meta_user_id} · ${item.page_count} 个可投放 Page`" />
          </el-select>
          <p v-if="!executionAuthorizations.length" class="assignment-hint">暂无有效授权，请先接入 Meta 并同步此账户。</p>
          <p v-else-if="executionAuthorizations.find(item => item.connection_id === executionConnectionId)?.page_count === 0" class="assignment-hint">此授权暂无可投放 Page，新建广告前需由授权人补充 Page 权限并同步。</p>
        </el-form-item>
      </el-form>
      <el-alert class="mb12" :title="executionMode === 'KEEP' ? '保留勾选用户的执行设置；新分配或已失效分配默认要求本人 Meta 授权。' : executionMode === 'PERSONAL' ? '本次勾选用户改为使用本人 Meta 授权，并撤销其在此账户上的委派执行权限。' : '指定授权仅供本次勾选用户操作此广告账户；投手无需重复 OAuth，授权人和原始凭据归属保持不变。'" type="info" :closable="false" show-icon />
      <el-alert
        title="主投手负责账户操作；其它已分配用户保留协作权限。保存不会移除未勾选的历史用户。"
        type="info"
        :closable="false"
        show-icon
      />
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
        <el-table-column label="执行方式" width="105"><template #default="{ row }"><el-tag :type="row.execution_connection_id ? 'success' : 'info'">{{ row.execution_connection_id ? '委派授权' : '本人授权' }}</el-tag></template></el-table-column>
        <el-table-column label="分工" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.is_primary" type="primary" size="small">主投手</el-tag>
            <el-tag v-else type="info" size="small">协作者</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button v-if="!row.is_primary && row.assignment_status === 'ACTIVE'" link type="primary" size="small" @click="setPrimaryUser(row as TableRow<typeof assignedList>)">设主投手</el-button>
            <el-button v-if="row.assignment_status === 'ACTIVE'" link type="danger" size="small" @click="removeUser(row as TableRow<typeof assignedList>)">移除</el-button>
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
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
const router = useRouter()

const accounts = ref<AdAccountItem[]>([])
const accountPage = ref(1)
const accountPageSize = 20
const accountTotal = ref(0)
const loading = ref(false)
const syncing = ref(false)
const search = ref('')
const systemStatusFilter = ref('')
const accountStatusFilter = ref('')
const businessFilter = ref('')
const assetFilter = ref('ALL')
const pendingScanErrors = ref<Array<{ business_name: string; error: string }>>([])
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
const primaryUserId = ref('')
const executionMode = ref<'KEEP' | 'PERSONAL' | 'DELEGATED'>('KEEP')
const executionConnectionId = ref('')
const executionAuthorizations = ref<Array<{ connection_id: string; meta_user_id: string; authorized_by_username: string; page_count: number }>>([])
watch(selectedUsers, (ids) => {
  if (!ids.includes(primaryUserId.value)) primaryUserId.value = ids[0] || ''
})

const showUsers = ref(false)
const userAccount = ref<AdAccountItem | null>(null)
const assignedList = ref<AccountUser[]>([])

let timer: number | undefined
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(resetAccountPage, 300) as unknown as number
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

function resetAccountPage() { accountPage.value = 1; void loadAccounts() }
let accountRequestNo = 0
async function loadAccounts() {
  const requestNo = ++accountRequestNo
  loading.value = true
  pendingScanErrors.value = []
  try {
    const params: Record<string, unknown> = { page: accountPage.value, page_size: accountPageSize }
    if (search.value) params.search = search.value
    if (systemStatusFilter.value) params.system_status = systemStatusFilter.value
    if (accountStatusFilter.value) params.account_status = accountStatusFilter.value
    if (businessFilter.value) params.business_id = businessFilter.value
    if (assetFilter.value !== 'ALL' && assetFilter.value !== 'PENDING') params.asset_type = assetFilter.value

    if (assetFilter.value === 'PENDING') {
      const { data } = await metaAccountApi.pendingAdAccounts()
      if (requestNo !== accountRequestNo) return
      pendingScanErrors.value = data.errors || []
      accounts.value = (data.accounts || []).map((row: any) => ({
        id: `pending-${row.meta_account_id}-${row.id}`,
        account_id: row.id,
        account_name: row.name || row.id,
        business_name: row.business_name,
        business_id: row.meta_account_id,
        asset_type: row.asset_type,
        account_status: row.account_status,
        system_status: 'DISABLED',
        currency: row.currency,
      })) as AdAccountItem[]
      userCount.value = {}
      accountTotal.value = accounts.value.length
      return
    }

    const { data, headers } = await accountApi.list(params)
    if (requestNo !== accountRequestNo) return
    accounts.value = data
    accountTotal.value = Number(headers['x-total-count'] ?? data.length)

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
    if (requestNo === accountRequestNo) userCount.value = counts
  } catch (e: any) {
    if (requestNo === accountRequestNo) {
      accounts.value = []
      userCount.value = {}
      accountTotal.value = 0
      clearSelection()
    }
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    if (requestNo === accountRequestNo) loading.value = false
  }
}

function assetType(row: AdAccountItem): string {
  return (row as AdAccountItem & { asset_type?: string }).asset_type || 'OWNED'
}
function goMetaAccounts() { router.push({ name: 'AdminMetaAccounts' }) }
function openPendingBm(row: AdAccountItem) { router.push({ name: 'AdminBusinessDetail', params: { id: row.business_id } }) }

function onSelectionChange(rows: AdAccountItem[]) {
  selected.value = rows
}
function clearSelection() {
  tableRef.value?.clearSelection()
}

async function withAccountLeases<T>(accountIds: string[], operationType: string, callback: (tokens: Record<string, string>) => Promise<T>): Promise<T> {
  const held: Array<{ accountId: string; token: string }> = []
  const tokens: Record<string, string> = {}
  try {
    for (const accountId of accountIds) {
      const { data } = await accountApi.acquireOperationLease(accountId, operationType, 120)
      const token = data?.lease?.lease_token
      if (!token) throw new Error('未能获取广告账户操作租约')
      held.push({ accountId, token })
      tokens[accountId] = token
    }
    return await callback(tokens)
  } finally {
    await Promise.allSettled(held.map(({ accountId, token }) => accountApi.releaseOperationLease(accountId, token)))
  }
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
      await withAccountLeases([id], 'ACCOUNT_MUTATION', async tokens => {
        await accountApi.update(id, { ...rest, lease_token: tokens[id] })
      })
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
      const ids = selected.value.map((a) => a.id)
      const { data } = await withAccountLeases(ids, 'ACCOUNT_MUTATION', tokens => accountApi.bulk({
        action: 'transfer',
        account_ids: ids,
        business_id: transferTarget.value,
        skip_verification: transferSkipVerify.value,
        operation_leases: tokens,
      })
      )
      if (data.failed_count) {
        ElMessage.warning(`成功 ${data.success_count} 个，失败 ${data.failed_count} 个：${data.errors?.[0]?.error || ''}`)
      } else {
        ElMessage.success(`已转移 ${data.success_count} 个账户`)
      }
      clearSelection()
    } else if (transferRow.value) {
      await withAccountLeases([transferRow.value.id], 'ACCOUNT_MUTATION', tokens => accountApi.transfer(transferRow.value!.id, {
        business_id: transferTarget.value,
        skip_verification: transferSkipVerify.value,
        lease_token: tokens[transferRow.value!.id],
      })
      )
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
    const ids = selected.value.map((a) => a.id)
    const { data } = await withAccountLeases(ids, 'ACCOUNT_MUTATION', tokens => accountApi.bulk({
      action,
      account_ids: ids,
      reason: action === 'freeze' ? '批量停用' : undefined,
      operation_leases: tokens,
    })
    )
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

/** 批量同步：异步任务，逐条投递后立即返回，结果查同步日志 */
async function bulkSync() {
  if (!selected.value.length) return
  syncing.value = true
  const held: Array<{ accountId: string; token: string }> = []
  const operationLeases: Record<string, string> = {}
  try {
    for (const accountId of selected.value.map((account) => account.id)) {
      const { data: leaseResult } = await accountApi.acquireOperationLease(accountId, 'ACCOUNT_SYNC', 120)
      const token = leaseResult?.lease?.lease_token
      if (!token) throw new Error('未能获取广告账户操作租约')
      held.push({ accountId, token })
      operationLeases[accountId] = token
    }
    const { data } = await accountApi.syncBatch({
      account_ids: selected.value.map((a) => a.id),
      operation_leases: operationLeases,
    })
    if (data.failed) {
      ElMessage.warning(
        `已提交 ${data.submitted} 个，${data.failed} 个失败：${data.errors?.[0]?.error || ''}`
      )
    } else {
      ElMessage.success(`已提交 ${data.submitted} 个同步任务`)
    }
    clearSelection()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    await Promise.allSettled(held.map(({ accountId, token }) => accountApi.releaseOperationLease(accountId, token)))
    syncing.value = false
  }
}

function goDetail(a: AdAccountItem) {
  router.push({ name: 'AdminAccountDetail', params: { id: a.id } })
}

async function toggleStatus(a: AdAccountItem) {
  const disabling = a.system_status === 'ACTIVE'
  try {
    await ElMessageBox.confirm(`确认${disabling ? '限制' : '恢复'}账户 ${a.account_id} 的新建投放资格？现有广告的暂停请在投放管理操作。`, '本地投放资格', { type: 'warning' })
  } catch {
    return
  }
  try {
    await withAccountLeases([a.id], 'ACCOUNT_MUTATION', async tokens => {
      if (disabling) await accountApi.freeze(a.id, '管理员停用', tokens[a.id])
      else await accountApi.unfreeze(a.id, tokens[a.id])
    })
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
    await withAccountLeases([a.id], 'ACCOUNT_MUTATION', tokens => accountApi.delete(a.id, tokens[a.id]))
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function openAssign(a: AdAccountItem) {
  assignAccount.value = a
  selectedUsers.value = []
  primaryUserId.value = ''
  executionMode.value = 'KEEP'
  executionConnectionId.value = ''
  executionAuthorizations.value = []
  try {
    const [users, { data: assigned }, { data: authorizations }] = await Promise.all([
      userApi.listAll(),
      accountApi.users(a.id),
      accountApi.executionAuthorizations(a.id),
    ])
    allUsers.value = users
    executionAuthorizations.value = authorizations.items || []
    const activeAssigned = (assigned as AccountUser[]).filter((row) => row.assignment_status === 'ACTIVE')
    selectedUsers.value = activeAssigned.map((row) => row.user_id)
    primaryUserId.value = activeAssigned.find((row) => row.is_primary)?.user_id || ''
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
  if (executionMode.value === 'DELEGATED' && !executionConnectionId.value) {
    ElMessage.warning('请选择执行 Meta 授权')
    return
  }
  saving.value = true
  try {
    await withAccountLeases([assignAccount.value.id], 'ACCOUNT_ASSIGNMENT', tokens => accountApi.assign(
      assignAccount.value!.id,
      selectedUsers.value,
      selectedUsers.value.includes(primaryUserId.value) ? primaryUserId.value : selectedUsers.value[0],
      tokens[assignAccount.value!.id],
      executionMode.value === 'KEEP' ? undefined : executionMode.value === 'PERSONAL' ? null : executionConnectionId.value,
    ))
    showAssign.value = false
    ElMessage.success('广告账户已分配给投手')
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
    await withAccountLeases([userAccount.value.id], 'ACCOUNT_ASSIGNMENT', tokens => accountApi.unassign(userAccount.value!.id, [u.user_id], tokens[userAccount.value!.id]))
    const { data } = await accountApi.users(userAccount.value.id)
    assignedList.value = data
    await loadAccounts()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

async function setPrimaryUser(u: AccountUser) {
  if (!userAccount.value) return
  try {
    await withAccountLeases([userAccount.value.id], 'ACCOUNT_ASSIGNMENT', tokens => accountApi.setPrimary(userAccount.value!.id, u.user_id, tokens[userAccount.value!.id]))
    const { data } = await accountApi.users(userAccount.value.id)
    assignedList.value = data
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
.assignment-guide { margin-bottom: 16px; }
.assignment-hint { margin: 0 0 16px; color: var(--el-text-color-secondary); }
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
.primary-form {
  margin-top: 16px;
}
.mb12 {
  margin-bottom: 12px;
}
</style>

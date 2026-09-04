<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <div class="eyebrow">账号中心 / Meta</div>
        <h2 class="page-title">BM / 广告账户</h2>
        <p class="page-subtitle">按「平台 → BM → 广告账户」管理 Meta 账号，授权入口跟随 BM，避免误授权到错误的 Business Manager。</p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="isAdmin" type="primary" :icon="OfficeBuilding" @click="goMetaAccounts">BM 管理</el-button>
      </div>
    </div>

    <div class="stats-grid">
      <el-card shadow="never" class="stat-card"><div class="stat-label">平台</div><div class="stat-value">Meta</div><div class="stat-desc">V1 已接入</div></el-card>
      <el-card shadow="never" class="stat-card"><div class="stat-label">BM</div><div class="stat-value">{{ businessNodes.length }}</div><div class="stat-desc">当前可见 BM</div></el-card>
      <el-card shadow="never" class="stat-card"><div class="stat-label">广告账户</div><div class="stat-value">{{ accounts.length }}</div><div class="stat-desc">当前可见账户</div></el-card>
      <el-card shadow="never" class="stat-card"><div class="stat-label">可投放</div><div class="stat-value">{{ activeCount }}</div><div class="stat-desc">系统状态 ACTIVE</div></el-card>
    </div>

    <el-card shadow="never" class="tree-card">
      <template #header>
        <div class="card-header">
          <div><span class="card-title">账号结构</span><span class="card-hint">点击 BM 查看详情，展开 BM 查看广告账户</span></div>
          <el-input v-model="filterText" clearable :prefix-icon="Search" placeholder="搜索 BM / Business ID / 广告账户" class="search-input" />
        </div>
      </template>

      <div v-loading="loading" class="tree-wrap">
        <el-tree
          ref="treeRef"
          :data="treeData"
          node-key="id"
          default-expand-all
          highlight-current
          :filter-node-method="filterNode"
          :props="treeProps"
          empty-text="暂无 BM 或广告账户"
          @node-click="handleNodeClick"
        >
          <template #default="{ data }">
            <div class="tree-node">
              <div class="node-main">
                <el-icon class="node-icon" :class="`node-${data.type}`">
                  <Platform v-if="data.type === 'platform'" />
                  <OfficeBuilding v-else-if="data.type === 'business'" />
                  <CreditCard v-else />
                </el-icon>
                <span class="node-name">{{ data.label }}</span>
                <el-tag v-if="data.type === 'platform'" size="small" effect="plain">{{ data.children?.length || 0 }} BM</el-tag>
                <el-tag v-else-if="data.type === 'business'" size="small" effect="plain">{{ data.accountCount || 0 }} 账户</el-tag>
              </div>

              <div v-if="data.type === 'business'" class="node-actions" @click.stop>
                <el-tag :type="credentialTagType(data.credentialStatus)" size="small">
                  {{ credentialLabel(data.credentialStatus) }}
                </el-tag>
                <el-button v-if="isAdmin" link type="primary" size="small" @click="authorizeBusiness(data)">
                  {{ data.credentialStatus === 'ACTIVE' ? '重新授权' : '授权 Meta' }}
                </el-button>
                <el-button link type="primary" size="small" @click="openBusiness(data)">查看 BM</el-button>
              </div>

              <div v-else-if="data.type === 'account'" class="node-actions" @click.stop>
                <el-tag :type="accountStatusType(data)" size="small" effect="plain">{{ accountStatusLabel(data) }}</el-tag>
                <el-button link type="primary" size="small" @click="openAccount(data)">账户详情</el-button>
              </div>
            </div>
          </template>
        </el-tree>

        <el-empty v-if="!loading && businessNodes.length === 0" description="暂无 BM">
          <el-button v-if="isAdmin" type="primary" @click="goMetaAccounts">进入 BM 管理</el-button>
        </el-empty>
      </div>
    </el-card>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="520px" destroy-on-close>
      <template v-if="selectedBusiness">
        <div class="drawer-summary">
          <div class="summary-icon"><OfficeBuilding /></div>
          <div><div class="summary-title">{{ selectedBusiness.label }}</div><div class="summary-id">Business ID：{{ selectedBusiness.metaBusinessId || '-' }}</div></div>
        </div>
        <el-descriptions :column="1" border class="detail-descriptions">
          <el-descriptions-item label="平台">Meta / Facebook</el-descriptions-item>
          <el-descriptions-item label="授权状态"><el-tag :type="credentialTagType(selectedBusiness.credentialStatus)">{{ credentialLabel(selectedBusiness.credentialStatus) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="同步状态"><el-tag :type="syncType(selectedBusiness.syncStatus)">{{ syncLabel(selectedBusiness.syncStatus) }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="广告账户">{{ selectedBusiness.accountCount || 0 }}</el-descriptions-item>
          <el-descriptions-item label="最后同步">{{ formatTime(selectedBusiness.lastSyncedAt) }}</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-actions">
          <el-button v-if="isAdmin" type="primary" @click="authorizeBusiness(selectedBusiness)">{{ selectedBusiness.credentialStatus === 'ACTIVE' ? '重新授权 Meta' : '授权 Meta' }}</el-button>
          <el-button v-if="isAdmin" @click="openBusiness(selectedBusiness)">打开 BM 详情</el-button>
        </div>
      </template>

      <template v-else-if="selectedAccount">
        <div class="drawer-summary">
          <div class="summary-icon account"><CreditCard /></div>
          <div><div class="summary-title">{{ selectedAccount.label }}</div><div class="summary-id">Account ID：{{ selectedAccount.accountId }}</div></div>
        </div>
        <el-descriptions :column="1" border class="detail-descriptions">
          <el-descriptions-item label="BM">{{ selectedAccount.businessName || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Meta 状态">{{ selectedAccount.accountStatus || '-' }}</el-descriptions-item>
          <el-descriptions-item label="系统状态"><el-tag :type="selectedAccount.systemStatus === 'ACTIVE' ? 'success' : 'danger'">{{ selectedAccount.systemStatus === 'ACTIVE' ? '可投放' : '已停用' }}</el-tag></el-descriptions-item>
          <el-descriptions-item label="已消费">{{ formatMoney(selectedAccount.amountSpent, selectedAccount.currency) }}</el-descriptions-item>
          <el-descriptions-item label="风险">{{ riskLabel(selectedAccount.riskScore) }}</el-descriptions-item>
          <el-descriptions-item label="最后同步">{{ formatTime(selectedAccount.lastSyncedAt) }}</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-actions"><el-button type="primary" @click="openAccountPage(selectedAccount.id)">打开账户详情</el-button></div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ElTree } from 'element-plus'
import { Refresh, OfficeBuilding, Search, Platform, CreditCard } from '@element-plus/icons-vue'
import { accountApi, credentialApi, metaAccountApi, type AdAccountItem, type MetaAccountItem } from '@/api/admin'
import { useUserStore } from '@/stores/userStore'
import { formatMoney } from '@/utils/money'

type TreeNode = {
  id: string
  label: string
  type: 'platform' | 'business' | 'account'
  children?: TreeNode[]
  businessId?: string
  metaBusinessId?: string
  credentialStatus?: string
  syncStatus?: string
  lastSyncedAt?: string | null
  accountCount?: number
  accountId?: string
  accountStatus?: string | null
  effectiveStatus?: string | null
  systemStatus?: string
  amountSpent?: number
  currency?: string
  riskScore?: number
  businessName?: string | null
  source?: AdAccountItem
}

const router = useRouter()
const userStore = useUserStore()
const treeRef = ref<InstanceType<typeof ElTree>>()
const loading = ref(false)
const filterText = ref('')
const accounts = ref<AdAccountItem[]>([])
const metaAccounts = ref<MetaAccountItem[]>([])
const drawerVisible = ref(false)
const selectedBusiness = ref<TreeNode | null>(null)
const selectedAccount = ref<TreeNode | null>(null)
const isAdmin = computed(() => userStore.isAdmin)
const activeCount = computed(() => accounts.value.filter((item) => item.system_status === 'ACTIVE').length)
const treeProps = { children: 'children', label: 'label' }

const businessNodes = computed<TreeNode[]>(() => {
  const map = new Map<string, TreeNode>()
  for (const meta of metaAccounts.value) {
    map.set(meta.id, {
      id: `business:${meta.id}`, label: meta.name, type: 'business', businessId: meta.id,
      metaBusinessId: meta.business_id, credentialStatus: meta.credential_status, syncStatus: meta.sync_status,
      lastSyncedAt: meta.last_synced_at, accountCount: meta.account_count, children: [],
    })
  }
  for (const account of accounts.value) {
    if (!account.business_id) continue
    let node = map.get(account.business_id)
    if (!node) {
      node = { id: `business:${account.business_id}`, label: account.business_name || `BM ${account.business_id}`, type: 'business', businessId: account.business_id, metaBusinessId: account.business_id, credentialStatus: 'NONE', syncStatus: 'PENDING', accountCount: 0, children: [] }
      map.set(account.business_id, node)
    }
    node.children!.push({
      id: `account:${account.id}`, label: account.account_name || account.account_id, type: 'account', accountId: account.account_id,
      accountStatus: account.account_status, effectiveStatus: account.effective_status, systemStatus: account.system_status,
      amountSpent: account.amount_spent, currency: account.currency, riskScore: account.risk_score,
      lastSyncedAt: account.last_synced_at, businessName: account.business_name, source: account,
    })
  }
  for (const node of map.values()) { node.children = node.children || []; node.accountCount = node.children.length || node.accountCount || 0 }
  return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
})

const treeData = computed<TreeNode[]>(() => [{ id: 'platform:meta', label: 'Meta / Facebook', type: 'platform', children: businessNodes.value }])
const drawerTitle = computed(() => selectedBusiness.value ? 'BM 详情' : '广告账户详情')
watch(filterText, (value) => treeRef.value?.filter(value))

function filterNode(value: string, data: TreeNode) {
  if (!value) return true
  const keyword = value.toLowerCase()
  return [data.label, data.metaBusinessId, data.accountId, data.businessName].some((item) => item?.toLowerCase().includes(keyword))
}
function credentialLabel(status?: string) {
  if (!status || status === 'NONE') return '未授权'
  if (status === 'ACTIVE') return '已授权'
  if (status === 'EXPIRED') return '已过期'
  if (status === 'DISABLED') return '已停用'
  return '权限异常'
}
function credentialTagType(status?: string): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'ACTIVE') return 'success'
  if (status === 'EXPIRED') return 'danger'
  if (status === 'DISABLED') return 'warning'
  return 'info'
}
function syncLabel(status?: string) { return ({ PENDING: '待同步', SYNCING: '同步中', SUCCESS: '已同步', FAILED: '同步失败' } as Record<string, string>)[status || ''] || status || '-' }
function syncType(status?: string): 'success' | 'danger' | 'warning' | 'info' { if (status === 'SUCCESS') return 'success'; if (status === 'FAILED') return 'danger'; if (status === 'SYNCING') return 'warning'; return 'info' }
function accountStatusLabel(node: TreeNode) { if (node.systemStatus !== 'ACTIVE') return '已停用'; const status = node.effectiveStatus || node.accountStatus; return status === 'ACTIVE' ? '正常' : status || '待校验' }
function accountStatusType(node: TreeNode): 'success' | 'danger' | 'warning' | 'info' { if (node.systemStatus !== 'ACTIVE') return 'danger'; const status = node.effectiveStatus || node.accountStatus; return status === 'ACTIVE' ? 'success' : status ? 'warning' : 'info' }
function riskLabel(score?: number) { const value = score ?? 0; return value >= 0.7 ? '高' : value >= 0.4 ? '中' : '低' }
function formatTime(value?: string | null) { return value ? value.replace('T', ' ').slice(0, 19) : '-' }
function handleNodeClick(node: TreeNode) { if (node.type === 'business') { selectedBusiness.value = node; selectedAccount.value = null; drawerVisible.value = true } else if (node.type === 'account') { selectedAccount.value = node; selectedBusiness.value = null; drawerVisible.value = true } }
function openBusiness(node: TreeNode) { if (node.businessId) router.push(`/admin/businesses/${node.businessId}`) }
function openAccount(node: TreeNode) { if (node.source?.id) openAccountPage(node.source.id) }
function openAccountPage(id: string) { router.push(`/admin/accounts/${id}`) }
function goMetaAccounts() { router.push('/admin/meta-accounts') }
async function authorizeBusiness(node: TreeNode | null) {
  if (!node?.businessId) { ElMessage.warning('当前 BM 缺少系统关联 ID，请先在 BM 管理中完成配置'); return }
  try { const { data } = await credentialApi.oauthAuthorize(node.businessId); window.location.assign(data.authorization_url) } catch { /* request.ts 已统一提示 */ }
}
async function load() {
  loading.value = true
  try {
    const accountResult = await accountApi.list({ page: 1, page_size: 100 })
    accounts.value = accountResult.data || []
    if (isAdmin.value) {
      try { const metaResult = await metaAccountApi.list(); metaAccounts.value = metaResult.data || [] } catch { metaAccounts.value = [] }
    } else metaAccounts.value = []
  } catch { accounts.value = []; metaAccounts.value = [] }
  finally { loading.value = false; await nextTick(); if (filterText.value) treeRef.value?.filter(filterText.value) }
}
onMounted(load)
</script>

<style scoped lang="scss">
.page-container { min-height: 100%; }
.page-head { display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom:18px; }
.eyebrow { margin-bottom:5px; color:#6b7f95; font-size:12px; }
.page-title { margin:0; color:#102a43; font-size:28px; line-height:1.25; }
.page-subtitle { margin:7px 0 0; color:#627d98; font-size:13px; }
.head-actions { display:flex; gap:10px; flex-wrap:wrap; }
.stats-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:16px; }
.stat-card { border:none; border-radius:12px; }
.stat-label { color:#829ab1; font-size:12px; }
.stat-value { margin-top:8px; color:#102a43; font-size:25px; font-weight:700; }
.stat-desc { margin-top:4px; color:#9fb3c8; font-size:12px; }
.tree-card { border:none; border-radius:12px; }
.card-header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.card-title { color:#243b53; font-weight:600; }
.card-hint { margin-left:10px; color:#9fb3c8; font-size:12px; }
.search-input { width:340px; }
.tree-wrap { min-height:360px; }
:deep(.el-tree) { background:transparent; color:#243b53; }
:deep(.el-tree-node__content) { min-height:50px; height:auto; border-radius:8px; margin:2px 0; }
:deep(.el-tree-node__content:hover) { background:#f5f9fd; }
:deep(.el-tree-node.is-current > .el-tree-node__content) { background:#eef6ff; }
.tree-node { display:flex; align-items:center; justify-content:space-between; width:100%; min-width:0; padding-right:10px; gap:16px; }
.node-main,.node-actions { display:flex; align-items:center; min-width:0; gap:8px; }
.node-name { max-width:460px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; }
.node-platform,.node-business { font-weight:600; }
.node-icon { flex:0 0 auto; font-size:17px; }
.node-platform { color:#1877f2; } .node-business { color:#64748b; } .node-account { color:#94a3b8; }
.drawer-summary { display:flex; align-items:center; gap:14px; padding:4px 0 20px; }
.summary-icon { display:flex; align-items:center; justify-content:center; width:42px; height:42px; border-radius:10px; background:#eef6ff; color:#1877f2; font-size:20px; }
.summary-icon.account { background:#f4f7fa; color:#64748b; }
.summary-title { color:#102a43; font-size:17px; font-weight:600; } .summary-id { margin-top:4px; color:#829ab1; font-size:12px; }
.detail-descriptions { margin-top:4px; } .drawer-actions { display:flex; gap:10px; margin-top:20px; }
@media (max-width:900px) { .stats-grid{grid-template-columns:repeat(2,minmax(0,1fr));} .page-head,.card-header{flex-direction:column;align-items:stretch;} .search-input{width:100%;} }
@media (max-width:600px) { .stats-grid{grid-template-columns:1fr;} .tree-node{align-items:flex-start;flex-direction:column;gap:5px;padding:6px 0;} }
</style>

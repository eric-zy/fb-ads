<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <div class="eyebrow">账号中心 / Meta</div>
        <h2 class="page-title">账号</h2>
        <p class="page-subtitle">统一接入和管理各广告平台账户，当前支持 Meta。</p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openAddDialog">接入账号</el-button>
      </div>
    </div>

    <div class="stats-grid">
      <el-card shadow="never"><div class="stat-label">平台</div><div class="stat-value">Meta</div><div class="stat-desc">OAuth 2.0</div></el-card>
      <el-card shadow="never"><div class="stat-label">授权连接</div><div class="stat-value">{{ credentialRows.filter(row => row.status === 'ACTIVE').length }}</div><div class="stat-desc">当前有效凭据</div></el-card>
      <el-card shadow="never"><div class="stat-label">账号</div><div class="stat-value">{{ accounts.length }}</div><div class="stat-desc">已同步账号</div></el-card>
      <el-card shadow="never"><div class="stat-label">可投放</div><div class="stat-value">{{ activeCount }}</div><div class="stat-desc">系统状态 ACTIVE</div></el-card>
    </div>

    <el-tabs v-model="activeTab" class="account-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="账户总览" name="overview">
        <el-card shadow="never" class="tree-card">
      <template #header>
        <div class="card-header">
          <div><b>账号列表</b><span>可直接用于投放的 Meta 账号</span></div>
          <el-input v-model="filterText" clearable :prefix-icon="Search" placeholder="搜索 BM / Business ID / 账号" class="search-input" />
        </div>
      </template>
      <div v-loading="loading" class="tree-wrap">
        <el-tree ref="treeRef" :data="treeData" node-key="id" default-expand-all highlight-current :filter-node-method="filterNode" :props="treeProps" empty-text="暂无可投账号" @node-click="handleNodeClick">
          <template #default="{ data }">
            <div class="tree-node">
              <div class="node-main">
                <el-icon><Platform v-if="data.type === 'platform'" /><OfficeBuilding v-else-if="data.type === 'business'" /><CreditCard v-else /></el-icon>
                <span class="node-name">{{ data.label }}</span>
                <el-tag v-if="data.type === 'platform'" size="small" effect="plain">{{ data.children?.length || 0 }} BM</el-tag>
                <el-tag v-else-if="data.type === 'business'" size="small" effect="plain">{{ data.accountCount || 0 }} 账户</el-tag>
              </div>
              <div v-if="data.type === 'business'" class="node-actions" @click.stop>
                <el-tag :type="credentialTagType(data.credentialStatus)" size="small">{{ credentialLabel(data.credentialStatus) }}</el-tag>
                <el-button v-if="isAdmin && data.businessId" link type="primary" size="small" @click="authorizeBusiness(data)">{{ data.credentialStatus === 'ACTIVE' ? '重新授权' : '授权 Meta' }}</el-button>
                <el-button v-if="data.businessId" link type="primary" size="small" @click="openBusiness(data)">查看 BM</el-button>
              </div>
              <div v-else-if="data.type === 'account'" class="node-actions" @click.stop>
                <el-tag :type="accountStatusType(data)" size="small" effect="plain">{{ accountStatusLabel(data) }}</el-tag>
                <el-button link type="primary" size="small" @click="openAccount(data)">账户详情</el-button>
              </div>
            </div>
          </template>
        </el-tree>
        <el-empty v-if="!loading && businessNodes.length === 0" description="还没有接入 Meta 账号">
          <template #default><el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openAddDialog">接入账号</el-button></template>
        </el-empty>
      </div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="账号列表" name="accounts-list">
        <el-card shadow="never" class="tab-card">
          <div class="list-toolbar">
            <el-input v-model="accountSearch" clearable placeholder="搜索账号名称 / Account ID" class="list-search" />
            <el-select v-model="accountMetaStatus" clearable placeholder="Meta 状态" class="status-select">
              <el-option label="正常" value="ACTIVE" /><el-option label="已停用" value="DISABLED" /><el-option label="待同步" value="PENDING" />
            </el-select>
            <el-select v-model="accountSystemStatus" clearable placeholder="投放状态" class="status-select">
              <el-option label="可投放" value="ACTIVE" /><el-option label="已停用" value="DISABLED" />
            </el-select>
            <el-button type="primary" plain :disabled="!selectedAccountRows.length" @click="syncSelectedAccounts">批量同步</el-button>
            <el-button type="success" plain :disabled="!selectedAccountRows.length" @click="setSelectedAccountsStatus('unfreeze')">批量启用</el-button>
            <el-button type="warning" plain :disabled="!selectedAccountRows.length" @click="setSelectedAccountsStatus('freeze')">批量停用</el-button>
            <el-button type="primary" :disabled="!selectedAccountRows.length" @click="goBatchPublish">批量投放</el-button>
          </div>
          <el-table :data="filteredAccounts" v-loading="loading" stripe @selection-change="selectedAccountRows = $event">
            <el-table-column type="selection" width="48" :selectable="isAccountSelectable" />
            <el-table-column label="账号" min-width="190"><template #default="{ row }">{{ row.account_name || row.account_id }}</template></el-table-column>
            <el-table-column prop="account_id" label="Account ID" min-width="160" />
            <el-table-column label="归属" min-width="150"><template #default="{ row }">{{ row.business_name || '账号' }}</template></el-table-column>
            <el-table-column label="Meta 状态" width="130"><template #default="{ row }"><el-tag :type="row.effective_status === 'ACTIVE' ? 'success' : 'warning'" size="small">{{ row.effective_status || row.account_status || '待同步' }}</el-tag></template></el-table-column>
            <el-table-column label="投放状态" width="120"><template #default="{ row }"><el-tag :type="row.system_status === 'ACTIVE' ? 'success' : 'danger'" size="small">{{ row.system_status === 'ACTIVE' ? '可投放' : '已停用' }}</el-tag></template></el-table-column>
            <el-table-column label="操作" width="80"><template #default="{ row }"><el-button link type="primary" @click="openAccount({ type: 'account', source: row, accountId: row.account_id, label: row.account_name || row.account_id })">详情</el-button></template></el-table-column>
          </el-table>
          <el-pagination v-if="accountTotal > accountPageSize" v-model:current-page="accountPage" :page-size="accountPageSize" :total="accountTotal" layout="total, prev, pager, next" @current-change="load" />
          <el-empty v-if="!loading && !accounts.length" description="暂无可投账号" />
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="接入账户" name="connect">
        <el-card shadow="never" class="tab-card">
          <div class="connect-panel">
            <div><h3>接入账号</h3><p>通过 Facebook 授权读取当前用户可访问的账号，系统会自动同步 BM 归属。</p></div>
            <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openAddDialog">接入账号</el-button>
          </div>
          <el-empty v-if="!isAdmin" description="当前账号没有接入广告账户的权限" />
          <el-alert v-else type="info" :closable="false" show-icon title="授权说明">只会读取你在 Facebook 中有权限访问的广告账户，Access Token 由服务端加密保存。</el-alert>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="授权凭据" name="credentials">
        <el-card shadow="never" class="tab-card">
          <el-table :data="credentialRows" v-loading="credentialLoading" stripe>
            <el-table-column type="expand" width="48">
              <template #default="{ row }">
                <div class="credential-linked">
                  <span class="linked-title">关联广告账户</span>
                  <el-tag v-for="account in (row.linked_accounts || [])" :key="account.id" size="small" effect="plain">
                    {{ account.name || account.account_id }} · {{ account.owner_type === 'PERSONAL' ? '个人' : 'BM' }}
                  </el-tag>
                  <span v-if="!row.linked_accounts?.length" class="muted-text">暂无直接关联账户</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="授权范围" min-width="180">
              <template #default="{ row }">{{ row.meta_account_name || (row.linked_personal_account_count ? '个人广告账户' : '未绑定资产') }}</template>
            </el-table-column>
            <el-table-column prop="name" label="凭据名称" min-width="150" />
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }"><el-tag :type="credentialTagType(row.status)">{{ credentialLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="access_token_masked" label="Token" width="180" />
            <el-table-column prop="expires_at" label="过期时间" width="190" />
            <el-table-column prop="last_verified_at" label="最近验证" width="190" />
            <el-table-column label="权限" min-width="220">
              <template #default="{ row }">
                <el-tag v-for="scope in (row.scopes || [])" :key="scope" size="small" effect="plain" style="margin-right:4px">{{ scope }}</el-tag>
                <span v-if="!row.scopes?.length" class="muted-text">未记录</span>
              </template>
            </el-table-column>
            <el-table-column label="投放权限" width="110">
              <template #default="{ row }"><el-tag :type="row.permission_ready ? 'success' : 'danger'" size="small">{{ row.permission_ready ? '正常' : '缺少权限' }}</el-tag></template>
            </el-table-column>
            <el-table-column label="关联账户" width="110">
              <template #default="{ row }"><el-tag size="small">{{ row.linked_account_count || 0 }} 个</el-tag></template>
            </el-table-column>
            <el-table-column label="账户类型" width="130">
              <template #default="{ row }">{{ row.linked_personal_account_count ? `个人 ${row.linked_personal_account_count} 个` : '企业 / BM' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110">
              <template #default="{ row }"><el-button v-if="isAdmin && (!row.permission_ready || row.is_expired || row.status !== 'ACTIVE')" link type="primary" @click="reauthorizeCredential(row)">重新授权</el-button></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!credentialLoading && !credentialRows.length" description="暂无授权凭据" />
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="同步记录" name="sync">
        <el-card shadow="never" class="tab-card">
          <el-table :data="syncRows" v-loading="syncLoading" stripe>
            <el-table-column prop="business_name" label="企业资产" min-width="180" />
            <el-table-column prop="sync_type" label="同步类型" width="130" />
            <el-table-column prop="status" label="状态" width="140">
              <template #default="{ row }"><el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'warning'">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="total_count" label="总数" width="90" />
            <el-table-column prop="success_count" label="成功" width="90" />
            <el-table-column prop="failed_count" label="失败" width="90" />
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
          </el-table>
          <el-empty v-if="!syncLoading && !syncRows.length" description="暂无同步记录" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="addDialogVisible" title="添加 Meta 广告用户" width="620px" destroy-on-close>
      <div v-if="oauthStep === 'login'" class="oauth-content">
        <div class="oauth-hero"><div class="oauth-logo"><Platform /></div><div><div class="oauth-title">Facebook 登录授权</div><div class="oauth-subtitle">将在独立的 Meta 官方授权窗口中完成登录和权限确认，本系统不会获取你的 Facebook 密码。</div></div></div>
        <div class="steps">
          <div><b>1　Facebook 登录</b><p>在官方弹窗中登录需要接入广告资产的账号。</p></div>
          <div><b>2　确认授权</b><p>确认广告管理、广告读取和业务资产权限。</p></div>
          <div><b>3　选择广告账户</b><p>系统读取可访问广告账户，BM 由后端自动关联。</p></div>
        </div>
        <el-alert type="info" :closable="false" show-icon title="安全说明">Access Token 仅由服务端加密保存，不会显示给前端。</el-alert>
      </div>
      <div v-else-if="oauthStep === 'businesses'">
        <el-alert v-if="oauthError" type="error" :closable="false" show-icon :title="oauthError" />
        <div class="select-title">选择要接入的广告账户</div>
        <p class="select-desc">个人账户无需关联 BM；企业账户会保留 Meta 返回的 BM 归属。</p>
        <el-radio-group v-model="oauthOwnerFilter" size="small" class="owner-filter">
          <el-radio-button label="ALL">全部</el-radio-button>
          <el-radio-button label="PERSONAL">个人账户</el-radio-button>
          <el-radio-button label="BUSINESS">BM 账户</el-radio-button>
        </el-radio-group>
        <el-checkbox-group v-model="selectedOAuthAccountIds" class="business-list">
          <div v-for="item in filteredOAuthAdAccounts" :key="item.id" class="business-option" :class="{ selected: selectedOAuthAccountIds.includes(item.id) }">
            <el-checkbox :label="item.id"><b>{{ item.name || item.id }}</b></el-checkbox>
            <div>广告账户：{{ item.id }} · {{ item.business?.id ? `BM：${item.business.name || item.business.id}` : '个人广告账户' }}</div>
          </div>
        </el-checkbox-group>
        <el-empty v-if="!filteredOAuthAdAccounts.length && !oauthError" description="当前筛选条件下没有可接入的广告账户" />
      </div>
      <div v-else class="success-state"><el-icon><Connection /></el-icon><h3>Meta 授权成功</h3><p>广告账户已接入，系统已自动处理 BM 归属。</p></div>
      <template #footer>
        <el-button @click="closeAddDialog">取消</el-button>
        <el-button v-if="oauthStep === 'login'" type="primary" :loading="authorizing" :icon="Connection" @click="startOAuth">登录 Meta 并授权</el-button>
        <el-button v-else-if="oauthStep === 'businesses'" type="primary" :loading="completing" :disabled="!selectedOAuthAccountIds.length" @click="completeOAuth">确认接入并同步</el-button>
        <el-button v-else type="primary" @click="closeAddDialog">完成</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="520px">
      <template v-if="selectedBusiness"><el-descriptions :column="1" border><el-descriptions-item label="类型">{{ selectedBusiness.businessId ? 'Business / BM' : '个人授权' }}</el-descriptions-item><el-descriptions-item label="名称">{{ selectedBusiness.label }}</el-descriptions-item><el-descriptions-item label="Business ID">{{ selectedBusiness.metaBusinessId || '-' }}</el-descriptions-item><el-descriptions-item label="授权"><el-tag :type="credentialTagType(selectedBusiness.credentialStatus)">{{ credentialLabel(selectedBusiness.credentialStatus) }}</el-tag></el-descriptions-item><el-descriptions-item label="广告账户">{{ selectedBusiness.accountCount || 0 }}</el-descriptions-item><el-descriptions-item label="同步">{{ syncLabel(selectedBusiness.syncStatus) }}</el-descriptions-item></el-descriptions><el-button v-if="isAdmin && selectedBusiness.businessId" type="primary" class="drawer-button" @click="authorizeBusiness(selectedBusiness)">重新授权 Meta</el-button></template>
      <template v-else-if="selectedAccount"><el-descriptions :column="1" border><el-descriptions-item label="账号">{{ selectedAccount.label }}</el-descriptions-item><el-descriptions-item label="Account ID">{{ selectedAccount.accountId }}</el-descriptions-item><el-descriptions-item label="账号来源">{{ selectedAccount.source?.owner_type === 'PERSONAL' ? '账号授权' : 'BM 授权' }}</el-descriptions-item><el-descriptions-item label="BM">{{ selectedAccount.businessName || '-' }}</el-descriptions-item><el-descriptions-item label="Meta 状态">{{ selectedAccount.effectiveStatus || selectedAccount.accountStatus || '待同步' }}</el-descriptions-item><el-descriptions-item label="系统状态">{{ selectedAccount.systemStatus === 'ACTIVE' ? '可投放' : '已停用' }}</el-descriptions-item><el-descriptions-item label="已消费">{{ formatMoney(selectedAccount.amountSpent, selectedAccount.currency) }}</el-descriptions-item></el-descriptions></template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ElTree } from 'element-plus'
import { Connection, CreditCard, OfficeBuilding, Platform, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { accountApi, credentialApi, metaAccountApi, type AdAccountItem, type MetaAccountItem, type CredentialItem, type SyncLogItem } from '@/api/admin'
import { useUserStore } from '@/stores/userStore'
import { formatMoney } from '@/utils/money'

type DiscoveredBusiness = { id: string; name?: string | null; verification_status?: string | null }
type TreeNode = { id: string; label: string; type: 'platform' | 'business' | 'account'; children?: TreeNode[]; businessId?: string; metaBusinessId?: string; credentialStatus?: string; syncStatus?: string; accountCount?: number; accountId?: string; accountStatus?: string | null; effectiveStatus?: string | null; systemStatus?: string; amountSpent?: number; currency?: string; businessName?: string | null; source?: AdAccountItem }
const router = useRouter(); const route = useRoute(); const userStore = useUserStore(); const activeTab = ref('overview'); const treeRef = ref<InstanceType<typeof ElTree>>(); const loading = ref(false); const credentialLoading = ref(false); const syncLoading = ref(false); const filterText = ref(''); const accountSearch = ref(''); const accountMetaStatus = ref(''); const accountSystemStatus = ref(''); const selectedAccountRows = ref<AdAccountItem[]>([]); const accountPage = ref(1); const accountPageSize = 20; const accountTotal = ref(0); const accounts = ref<AdAccountItem[]>([]); const metaAccounts = ref<MetaAccountItem[]>([]); const credentialRows = ref<CredentialItem[]>([]); const syncRows = ref<Array<SyncLogItem & { business_name: string }>>([]); const drawerVisible = ref(false); const selectedBusiness = ref<TreeNode | null>(null); const selectedAccount = ref<TreeNode | null>(null); const addDialogVisible = ref(false); const authorizing = ref(false); const completing = ref(false); const oauthCredentialId = ref<string | null>(null); const oauthStep = ref<'login' | 'businesses' | 'success'>('login'); const oauthError = ref(''); const discoveredBusinesses = ref<DiscoveredBusiness[]>([]); const selectedDiscoveredBusinessId = ref<string | null>(null); const oauthAdAccounts = ref<any[]>([]); const selectedOAuthAccountIds = ref<string[]>([]); const oauthOwnerFilter = ref<'ALL'|'PERSONAL'|'BUSINESS'>('ALL'); const isAdmin = computed(() => userStore.isAdmin); const activeCount = computed(() => accounts.value.filter(a => a.system_status === 'ACTIVE').length); const treeProps = { children: 'children', label: 'label' }
const filteredAccounts = computed(() => accounts.value.filter(account => { const q = accountSearch.value.trim().toLowerCase(); const meta = account.effective_status || account.account_status || 'PENDING'; return (!q || `${account.account_name || ''} ${account.account_id}`.toLowerCase().includes(q)) && (!accountMetaStatus.value || meta === accountMetaStatus.value) && (!accountSystemStatus.value || account.system_status === accountSystemStatus.value) }))
async function syncSelectedAccounts() { const ids = selectedAccountRows.value.map(account => account.id); if (!ids.length) return; try { await accountApi.syncBatch({ account_ids: ids }); ElMessage.success(`已提交 ${ids.length} 个账号的同步任务`); selectedAccountRows.value = []; await load() } catch { /* 全局请求拦截器提示错误 */ } }
async function setSelectedAccountsStatus(action: 'freeze' | 'unfreeze') { const ids = selectedAccountRows.value.map(account => account.id); if (!ids.length) return; try { await accountApi.bulk({ action, account_ids: ids, reason: action === 'freeze' ? '管理员批量停用' : undefined }); ElMessage.success(`已批量${action === 'freeze' ? '停用' : '启用'} ${ids.length} 个账号`); selectedAccountRows.value = []; await load() } catch { /* 全局请求拦截器提示错误 */ } }
function goBatchPublish() { router.push({ path: '/dashboard/batch-publish', query: { account_ids: selectedAccountRows.value.map(account => account.id).join(',') } }) }
function isAccountSelectable(account: AdAccountItem) { const metaStatus = account.effective_status || account.account_status; return account.system_status === 'ACTIVE' && (!metaStatus || metaStatus === 'ACTIVE') }
const filteredOAuthAdAccounts = computed(() => oauthAdAccounts.value.filter(item => oauthOwnerFilter.value === 'ALL' || (item.business?.id ? 'BUSINESS' : 'PERSONAL') === oauthOwnerFilter.value))
const businessNodes = computed<TreeNode[]>(() => { const map = new Map<string, TreeNode>(); for (const m of metaAccounts.value) map.set(m.id, { id: `business:${m.id}`, label: m.name, type: 'business', businessId: m.id, metaBusinessId: m.business_id, credentialStatus: m.credential_status, syncStatus: m.sync_status, accountCount: m.account_count, children: [] }); for (const a of accounts.value) { const key = a.business_id || '__personal__'; let n = map.get(key); if (!n) { n = { id: `business:${key}`, label: a.business_id ? (a.business_name || `BM ${a.business_id}`) : '个人授权账户', type: 'business', businessId: a.business_id || undefined, metaBusinessId: a.business_id || undefined, credentialStatus: a.business_id ? 'NONE' : (a.credential_id ? 'ACTIVE' : 'NONE'), syncStatus: 'PENDING', accountCount: 0, children: [] }; map.set(key, n) } n.children!.push({ id: `account:${a.id}`, label: a.account_name || a.account_id, type: 'account', accountId: a.account_id, accountStatus: a.account_status, effectiveStatus: a.effective_status, systemStatus: a.system_status, amountSpent: a.amount_spent, currency: a.currency, businessName: a.business_name, source: a }) } for (const n of map.values()) n.accountCount = n.children?.length || n.accountCount || 0; return [...map.values()].sort((a,b) => a.label.localeCompare(b.label, 'zh-CN')) })
const treeData = computed(() => [{ id: 'platform:meta', label: 'Meta / Facebook', type: 'platform' as const, children: businessNodes.value }]); const drawerTitle = computed(() => selectedBusiness.value ? 'BM 详情' : '广告账户详情')
watch(filterText, v => treeRef.value?.filter(v))
function filterNode(value: string, data: TreeNode) { if (!value) return true; const k = value.toLowerCase(); return [data.label, data.metaBusinessId, data.accountId, data.businessName].some(v => v?.toLowerCase().includes(k)) }
function credentialLabel(s?: string) { if (!s || s === 'NONE') return '未授权'; if (s === 'ACTIVE') return '已授权'; if (s === 'EXPIRED') return '已过期'; if (s === 'DISABLED') return '已停用'; return '权限异常' }
function credentialTagType(s?: string): 'success'|'danger'|'warning'|'info' { if (s === 'ACTIVE') return 'success'; if (s === 'EXPIRED') return 'danger'; if (s === 'DISABLED') return 'warning'; return 'info' }
function accountStatusLabel(n: TreeNode) { if (n.systemStatus !== 'ACTIVE') return '已停用'; return (n.effectiveStatus || n.accountStatus) === 'ACTIVE' ? '正常' : (n.effectiveStatus || n.accountStatus || '待校验') }
function accountStatusType(n: TreeNode): 'success'|'danger'|'warning'|'info' { if (n.systemStatus !== 'ACTIVE') return 'danger'; return (n.effectiveStatus || n.accountStatus) === 'ACTIVE' ? 'success' : 'warning' }
function syncLabel(s?: string) { return ({ PENDING: '待同步', SYNCING: '同步中', SUCCESS: '已同步', FAILED: '同步失败' } as Record<string,string>)[s || ''] || s || '-' }
function handleNodeClick(n: TreeNode) { if (n.type === 'business') { selectedBusiness.value = n; selectedAccount.value = null; drawerVisible.value = true } else if (n.type === 'account') { selectedAccount.value = n; selectedBusiness.value = null; drawerVisible.value = true } }
function openBusiness(n: TreeNode) { if (n.businessId) router.push(`/admin/businesses/${n.businessId}`) }
function openAccount(n: TreeNode) { if (n.source?.id) router.push(`/admin/accounts/${n.source.id}`) }
function openAddDialog() { oauthStep.value = 'login'; oauthError.value = ''; discoveredBusinesses.value = []; selectedDiscoveredBusinessId.value = null; oauthAdAccounts.value = []; selectedOAuthAccountIds.value = []; oauthCredentialId.value = null; oauthOwnerFilter.value = 'ALL'; addDialogVisible.value = true }
function closeAddDialog() { addDialogVisible.value = false; if (route.query.meta_auth || route.query.credential_id) router.replace({ query: { ...route.query, meta_auth: undefined, credential_id: undefined, message: undefined } }) }
async function startOAuth() { const popup = window.open('', 'meta-oauth', 'width=620,height=760,resizable=yes,scrollbars=yes'); authorizing.value = true; oauthError.value = ''; try { const { data } = await credentialApi.oauthAuthorizeFirst(); if (!data.authorization_url) throw new Error('Meta 未返回授权地址'); if (popup) popup.location.href = data.authorization_url; else window.location.assign(data.authorization_url) } catch (e: any) { popup?.close(); oauthError.value = e?.response?.data?.detail || e?.message || '无法启动 Facebook 登录'; ElMessage.error(oauthError.value) } finally { authorizing.value = false } }
async function openBusinessDiscovery(id?: string) { addDialogVisible.value = true; oauthStep.value = 'businesses'; oauthError.value = ''; const credentialId = id || String(route.query.credential_id || ''); if (!credentialId) { oauthError.value = '缺少本次 OAuth 授权凭据，请重新授权'; return } oauthCredentialId.value = credentialId; try { const { data } = await credentialApi.oauthAdAccounts(credentialId); oauthAdAccounts.value = data.accounts || []; } catch (e: any) { oauthError.value = e?.response?.data?.detail || '无法读取 Meta 可访问广告账户，请重新授权' } }
async function completeOAuth() { if (!oauthCredentialId.value || !selectedOAuthAccountIds.value.length) return; completing.value = true; try { await credentialApi.oauthCompleteAccounts({ credential_id: oauthCredentialId.value, account_ids: selectedOAuthAccountIds.value }); oauthStep.value = 'success'; ElMessage.success('广告账户接入成功，正在刷新账户列表'); await load(); } catch (e: any) { oauthError.value = e?.response?.data?.detail || '广告账户接入失败，请重试'; ElMessage.error(oauthError.value) } finally { completing.value = false } }
async function loadCredentials() { if (!isAdmin.value) return; credentialLoading.value = true; try { const r = await credentialApi.list({ page: 1, page_size: 100 }); credentialRows.value = r.data || [] } catch { credentialRows.value = [] } finally { credentialLoading.value = false } }
async function loadSyncLogs() { if (!isAdmin.value) return; syncLoading.value = true; try { const results = await Promise.all(metaAccounts.value.map(async business => { try { const r = await metaAccountApi.syncLogs(business.id, { limit: 20 }); return (r.data || []).map((row: SyncLogItem) => ({ ...row, business_name: business.name })) } catch { return [] } })); syncRows.value = results.flat().sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))) } finally { syncLoading.value = false } }
async function handleTabChange(tab: string | number) { if (tab === 'credentials') await loadCredentials(); if (tab === 'sync') await loadSyncLogs() }
function handleOAuthMessage(e: MessageEvent) { if (e.origin !== window.location.origin) return; if (e.data?.type === 'meta-oauth-ready') openBusinessDiscovery(e.data.credential_id); if (e.data?.type === 'meta-oauth-completed') load() }
async function authorizeBusiness(n: TreeNode | null) { if (!n?.businessId) return; try { const { data } = await credentialApi.oauthAuthorize(n.businessId); window.location.assign(data.authorization_url) } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '无法发起 Meta 重新授权') } }
async function reauthorizeCredential(row: CredentialItem) { try { const { data } = row.meta_account_id ? await credentialApi.oauthAuthorize(row.meta_account_id) : await credentialApi.oauthAuthorizeFirst(); window.location.assign(data.authorization_url) } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '无法发起 Meta 重新授权') } }
async function load(page = accountPage.value) { accountPage.value = page; loading.value = true; try { const r = await accountApi.list({ page, page_size: accountPageSize }); accounts.value = r.data || []; accountTotal.value = Number(r.headers?.['x-total-count'] || accounts.value.length); if (isAdmin.value) { try { const m = await metaAccountApi.list(); metaAccounts.value = m.data || [] } catch { metaAccounts.value = [] } } } catch { accounts.value = []; accountTotal.value = 0; metaAccounts.value = [] } finally { loading.value = false; await nextTick(); if (filterText.value) treeRef.value?.filter(filterText.value) } }
function handleOAuthRoute() { const auth = String(route.query.meta_auth || ''); if (auth === 'businesses') { if (window.opener) { const id = String(route.query.credential_id || ''); if (id) { window.opener.postMessage({ type: 'meta-oauth-ready', credential_id: id }, window.location.origin); setTimeout(() => window.close(), 200) } } else openBusinessDiscovery(String(route.query.credential_id || '')) } else if (auth === 'success') { if (window.opener) { window.opener.postMessage({ type: 'meta-oauth-completed', meta_account_id: String(route.query.meta_account_id || '') }, window.location.origin); setTimeout(() => window.close(), 200) } else { ElMessage.success('Meta 授权成功，账户正在同步'); void load() } } else if (auth === 'error') { const message = String(route.query.message || 'Meta 授权失败或已取消'); if (window.opener) { window.opener.postMessage({ type: 'meta-oauth-error', message }, window.location.origin); setTimeout(() => window.close(), 200) } else { addDialogVisible.value = true; oauthStep.value = 'login'; oauthError.value = message } } }
onMounted(async () => { window.addEventListener('message', handleOAuthMessage); await load(); handleOAuthRoute() })
onBeforeUnmount(() => window.removeEventListener('message', handleOAuthMessage))
</script>

<style scoped lang="scss">
.page-container{min-height:100%}.page-head{display:flex;justify-content:space-between;gap:24px;margin-bottom:18px}.eyebrow{color:#6b7f95;font-size:12px}.page-title{margin:5px 0;color:#102a43;font-size:28px}.page-subtitle{margin:0;color:#627d98;font-size:13px}.head-actions,.node-actions{display:flex;align-items:center;gap:8px}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:12px}.stat-label,.stat-desc{color:#829ab1;font-size:12px}.stat-value{margin:7px 0;color:#102a43;font-size:25px;font-weight:700}.account-tabs{margin-top:2px}.tab-card,.tree-card{border:none}.card-header{display:flex;align-items:center;justify-content:space-between;gap:16px}.card-header span{margin-left:10px;color:#9fb3c8;font-size:12px}.search-input{width:340px}.tree-wrap{min-height:380px}.tree-node{display:flex;justify-content:space-between;align-items:center;width:100%;padding-right:10px;gap:15px}.node-main{display:flex;align-items:center;gap:8px;min-width:0}.node-name{max-width:460px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.connect-panel{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:20px}.connect-panel h3{margin:0 0 8px;color:#102a43}.connect-panel p{margin:0;color:#829ab1;font-size:13px}.oauth-hero{display:flex;align-items:center;gap:14px;margin-bottom:20px}.oauth-logo{display:flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:14px;background:#eef6ff;color:#1877f2;font-size:24px}.oauth-title{font-size:18px;font-weight:600;color:#102a43}.oauth-subtitle,.steps p,.select-desc{color:#829ab1;font-size:12px}.steps{display:grid;gap:15px;margin-bottom:20px}.steps p{margin:5px 0 0}.business-list{display:flex;flex-direction:column;width:100%;gap:10px;margin-top:15px}.business-option{padding:14px;border:1px solid #e5edf5;border-radius:10px;cursor:pointer}.business-option.selected{border-color:#409eff;background:#f5f9ff}.business-option>div{margin:7px 0 0 24px;color:#829ab1;font-size:12px}.select-title{margin-top:15px;font-size:16px;font-weight:600;color:#243b53}.success-state{text-align:center;padding:45px}.success-state .el-icon{font-size:52px;color:#18a058}.success-state h3{margin:15px 0 5px}.success-state p{color:#829ab1}.drawer-button{margin-top:20px}@media(max-width:900px){.stats-grid{grid-template-columns:repeat(2,1fr)}.page-head,.card-header,.connect-panel{flex-direction:column;align-items:stretch}.search-input{width:100%}}@media(max-width:600px){.stats-grid{grid-template-columns:1fr}.tree-node{align-items:flex-start;flex-direction:column}.node-actions{width:100%}}
</style>

<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <div class="eyebrow">账号中心 / Meta</div>
        <h2 class="page-title">BM / 广告账户</h2>
        <p class="page-subtitle">通过 Meta OAuth 2.0 一键授权，自动发现 Business Manager 并同步广告账户。</p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openAddDialog">添加广告用户</el-button>
      </div>
    </div>

    <div class="stats-grid">
      <el-card shadow="never"><div class="stat-label">平台</div><div class="stat-value">Meta</div><div class="stat-desc">OAuth 2.0</div></el-card>
      <el-card shadow="never"><div class="stat-label">BM</div><div class="stat-value">{{ businessNodes.length }}</div><div class="stat-desc">当前可见 BM</div></el-card>
      <el-card shadow="never"><div class="stat-label">广告账户</div><div class="stat-value">{{ accounts.length }}</div><div class="stat-desc">已同步账户</div></el-card>
      <el-card shadow="never"><div class="stat-label">可投放</div><div class="stat-value">{{ activeCount }}</div><div class="stat-desc">系统状态 ACTIVE</div></el-card>
    </div>

    <el-card shadow="never" class="tree-card">
      <template #header>
        <div class="card-header">
          <div><b>账号结构</b><span>Meta → BM → 广告账户</span></div>
          <el-input v-model="filterText" clearable :prefix-icon="Search" placeholder="搜索 BM / Business ID / 广告账户" class="search-input" />
        </div>
      </template>
      <div v-loading="loading" class="tree-wrap">
        <el-tree ref="treeRef" :data="treeData" node-key="id" default-expand-all highlight-current :filter-node-method="filterNode" :props="treeProps" empty-text="暂无 BM 或广告账户" @node-click="handleNodeClick">
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
                <el-button v-if="isAdmin" link type="primary" size="small" @click="authorizeBusiness(data)">{{ data.credentialStatus === 'ACTIVE' ? '重新授权' : '授权 Meta' }}</el-button>
                <el-button link type="primary" size="small" @click="openBusiness(data)">查看 BM</el-button>
              </div>
              <div v-else-if="data.type === 'account'" class="node-actions" @click.stop>
                <el-tag :type="accountStatusType(data)" size="small" effect="plain">{{ accountStatusLabel(data) }}</el-tag>
                <el-button link type="primary" size="small" @click="openAccount(data)">账户详情</el-button>
              </div>
            </div>
          </template>
        </el-tree>
        <el-empty v-if="!loading && businessNodes.length === 0" description="还没有接入 Meta 账号">
          <template #default><el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openAddDialog">添加广告用户</el-button></template>
        </el-empty>
      </div>
    </el-card>

    <el-dialog v-model="addDialogVisible" title="添加 Meta 广告用户" width="620px" destroy-on-close>
      <div v-if="oauthStep === 'login'" class="oauth-content">
        <div class="oauth-hero"><div class="oauth-logo"><Platform /></div><div><div class="oauth-title">Meta OAuth 2.0 一键授权</div><div class="oauth-subtitle">将在独立窗口打开 Meta 官方登录和授权页面，本系统不会获取你的 Meta 密码。</div></div></div>
        <div class="steps">
          <div><b>1　登录 Meta</b><p>使用需要接入广告资产的 Meta 用户登录。</p></div>
          <div><b>2　确认授权</b><p>确认 Business Manager、广告账户等所需权限。</p></div>
          <div><b>3　选择 BM</b><p>授权完成后系统自动读取该用户可访问的 BM。</p></div>
        </div>
        <el-alert type="info" :closable="false" show-icon title="安全说明">Access Token 仅由服务端加密保存，不会显示给前端。</el-alert>
      </div>
      <div v-else-if="oauthStep === 'businesses'">
        <el-alert v-if="oauthError" type="error" :closable="false" show-icon :title="oauthError" />
        <div class="select-title">选择要接入的 Business Manager</div>
        <p class="select-desc">系统发现 {{ discoveredBusinesses.length }} 个可访问 BM，请选择一个接入。</p>
        <el-radio-group v-model="selectedDiscoveredBusinessId" class="business-list">
          <div v-for="item in discoveredBusinesses" :key="item.id" class="business-option" :class="{ selected: selectedDiscoveredBusinessId === item.id }" @click="selectedDiscoveredBusinessId = item.id">
            <el-radio :label="item.id"><b>{{ item.name || item.id }}</b></el-radio>
            <div>Business ID：{{ item.id }}<span v-if="item.verification_status"> · {{ item.verification_status }}</span></div>
          </div>
        </el-radio-group>
        <el-empty v-if="!discoveredBusinesses.length && !oauthError" description="Meta 没有返回可访问的 BM，请确认授权用户拥有 Business Manager 权限" />
      </div>
      <div v-else class="success-state"><el-icon><Connection /></el-icon><h3>Meta 授权成功</h3><p>BM 已接入，系统正在后台同步广告账户。</p></div>
      <template #footer>
        <el-button @click="closeAddDialog">取消</el-button>
        <el-button v-if="oauthStep === 'login'" type="primary" :loading="authorizing" :icon="Connection" @click="startOAuth">登录 Meta 并授权</el-button>
        <el-button v-else-if="oauthStep === 'businesses'" type="primary" :loading="completing" :disabled="!selectedDiscoveredBusinessId" @click="completeOAuth">确认接入并同步</el-button>
        <el-button v-else type="primary" @click="closeAddDialog">完成</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawerVisible" :title="drawerTitle" size="520px">
      <template v-if="selectedBusiness"><el-descriptions :column="1" border><el-descriptions-item label="BM">{{ selectedBusiness.label }}</el-descriptions-item><el-descriptions-item label="Business ID">{{ selectedBusiness.metaBusinessId || '-' }}</el-descriptions-item><el-descriptions-item label="授权"><el-tag :type="credentialTagType(selectedBusiness.credentialStatus)">{{ credentialLabel(selectedBusiness.credentialStatus) }}</el-tag></el-descriptions-item><el-descriptions-item label="广告账户">{{ selectedBusiness.accountCount || 0 }}</el-descriptions-item><el-descriptions-item label="同步">{{ syncLabel(selectedBusiness.syncStatus) }}</el-descriptions-item></el-descriptions><el-button v-if="isAdmin" type="primary" class="drawer-button" @click="authorizeBusiness(selectedBusiness)">重新授权 Meta</el-button></template>
      <template v-else-if="selectedAccount"><el-descriptions :column="1" border><el-descriptions-item label="广告账户">{{ selectedAccount.label }}</el-descriptions-item><el-descriptions-item label="Account ID">{{ selectedAccount.accountId }}</el-descriptions-item><el-descriptions-item label="BM">{{ selectedAccount.businessName || '-' }}</el-descriptions-item><el-descriptions-item label="Meta 状态">{{ selectedAccount.accountStatus || '-' }}</el-descriptions-item><el-descriptions-item label="系统状态">{{ selectedAccount.systemStatus === 'ACTIVE' ? '可投放' : '已停用' }}</el-descriptions-item><el-descriptions-item label="已消费">{{ formatMoney(selectedAccount.amountSpent, selectedAccount.currency) }}</el-descriptions-item></el-descriptions></template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { ElTree } from 'element-plus'
import { Connection, CreditCard, OfficeBuilding, Platform, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { accountApi, credentialApi, metaAccountApi, type AdAccountItem, type MetaAccountItem } from '@/api/admin'
import { useUserStore } from '@/stores/userStore'
import { formatMoney } from '@/utils/money'

type DiscoveredBusiness = { id: string; name?: string | null; verification_status?: string | null }
type TreeNode = { id: string; label: string; type: 'platform' | 'business' | 'account'; children?: TreeNode[]; businessId?: string; metaBusinessId?: string; credentialStatus?: string; syncStatus?: string; accountCount?: number; accountId?: string; accountStatus?: string | null; effectiveStatus?: string | null; systemStatus?: string; amountSpent?: number; currency?: string; businessName?: string | null; source?: AdAccountItem }
const router = useRouter(); const route = useRoute(); const userStore = useUserStore(); const treeRef = ref<InstanceType<typeof ElTree>>(); const loading = ref(false); const filterText = ref(''); const accounts = ref<AdAccountItem[]>([]); const metaAccounts = ref<MetaAccountItem[]>([]); const drawerVisible = ref(false); const selectedBusiness = ref<TreeNode | null>(null); const selectedAccount = ref<TreeNode | null>(null); const addDialogVisible = ref(false); const authorizing = ref(false); const completing = ref(false); const oauthCredentialId = ref<string | null>(null); const oauthStep = ref<'login' | 'businesses' | 'success'>('login'); const oauthError = ref(''); const discoveredBusinesses = ref<DiscoveredBusiness[]>([]); const selectedDiscoveredBusinessId = ref<string | null>(null); const isAdmin = computed(() => userStore.isAdmin); const activeCount = computed(() => accounts.value.filter(a => a.system_status === 'ACTIVE').length); const treeProps = { children: 'children', label: 'label' }
const businessNodes = computed<TreeNode[]>(() => { const map = new Map<string, TreeNode>(); for (const m of metaAccounts.value) map.set(m.id, { id: `business:${m.id}`, label: m.name, type: 'business', businessId: m.id, metaBusinessId: m.business_id, credentialStatus: m.credential_status, syncStatus: m.sync_status, accountCount: m.account_count, children: [] }); for (const a of accounts.value) { if (!a.business_id) continue; let n = map.get(a.business_id); if (!n) { n = { id: `business:${a.business_id}`, label: a.business_name || `BM ${a.business_id}`, type: 'business', businessId: a.business_id, metaBusinessId: a.business_id, credentialStatus: 'NONE', syncStatus: 'PENDING', accountCount: 0, children: [] }; map.set(a.business_id, n) } n.children!.push({ id: `account:${a.id}`, label: a.account_name || a.account_id, type: 'account', accountId: a.account_id, accountStatus: a.account_status, effectiveStatus: a.effective_status, systemStatus: a.system_status, amountSpent: a.amount_spent, currency: a.currency, businessName: a.business_name, source: a }) } for (const n of map.values()) n.accountCount = n.children?.length || n.accountCount || 0; return [...map.values()].sort((a,b) => a.label.localeCompare(b.label, 'zh-CN')) })
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
function openAddDialog() { oauthStep.value = 'login'; oauthError.value = ''; discoveredBusinesses.value = []; selectedDiscoveredBusinessId.value = null; oauthCredentialId.value = null; addDialogVisible.value = true }
function closeAddDialog() { addDialogVisible.value = false; if (route.query.meta_auth || route.query.credential_id) router.replace({ query: { ...route.query, meta_auth: undefined, credential_id: undefined, message: undefined } }) }
async function startOAuth() { authorizing.value = true; oauthError.value = ''; try { const { data } = await credentialApi.oauthAuthorizeFirst(); const popup = window.open(data.authorization_url, 'meta_oauth', 'width=980,height=820,menubar=no,toolbar=no,location=yes,status=no,resizable=yes,scrollbars=yes'); if (!popup) window.location.assign(data.authorization_url) } catch (e: any) { oauthError.value = e?.response?.data?.detail || '无法发起 Meta 授权，请检查 Meta App 配置'; ElMessage.error(oauthError.value) } finally { authorizing.value = false } }
async function openBusinessDiscovery(id?: string) { addDialogVisible.value = true; oauthStep.value = 'businesses'; oauthError.value = ''; const credentialId = id || String(route.query.credential_id || ''); if (!credentialId) { oauthError.value = '缺少本次 OAuth 授权凭据，请重新授权'; return } oauthCredentialId.value = credentialId; try { const { data } = await credentialApi.oauthBusinesses(credentialId); discoveredBusinesses.value = data.businesses || []; if (discoveredBusinesses.value.length === 1) selectedDiscoveredBusinessId.value = discoveredBusinesses.value[0].id } catch (e: any) { oauthError.value = e?.response?.data?.detail || '无法读取 Meta 可访问 BM，请重新授权' } }
async function completeOAuth() { if (!oauthCredentialId.value || !selectedDiscoveredBusinessId.value) return; completing.value = true; try { await credentialApi.oauthComplete({ credential_id: oauthCredentialId.value, business_id: selectedDiscoveredBusinessId.value }); oauthStep.value = 'success'; ElMessage.success('Meta 广告用户接入成功，正在同步广告账户'); await load(); if (window.opener && !window.opener.closed) { window.opener.postMessage({ type: 'meta-oauth-completed' }, window.location.origin); setTimeout(() => window.close(), 500) } } catch (e: any) { oauthError.value = e?.response?.data?.detail || 'BM 接入失败，请重试'; ElMessage.error(oauthError.value) } finally { completing.value = false } }
function handleOAuthMessage(e: MessageEvent) { if (e.origin !== window.location.origin) return; if (e.data?.type === 'meta-oauth-ready') openBusinessDiscovery(e.data.credential_id); if (e.data?.type === 'meta-oauth-completed') load() }
async function authorizeBusiness(n: TreeNode | null) { if (!n?.businessId) return; try { const { data } = await credentialApi.oauthAuthorize(n.businessId); window.open(data.authorization_url, 'meta_oauth', 'width=980,height=820,menubar=no,toolbar=no,location=yes,status=no,resizable=yes,scrollbars=yes') } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '无法发起 Meta 重新授权') } }
async function load() { loading.value = true; try { const r = await accountApi.list({ page: 1, page_size: 100 }); accounts.value = r.data || []; if (isAdmin.value) { try { const m = await metaAccountApi.list(); metaAccounts.value = m.data || [] } catch { metaAccounts.value = [] } } } catch { accounts.value = []; metaAccounts.value = [] } finally { loading.value = false; await nextTick(); if (filterText.value) treeRef.value?.filter(filterText.value) } }
function handleOAuthRoute() { const auth = String(route.query.meta_auth || ''); if (auth === 'businesses') { if (window.opener) { const id = String(route.query.credential_id || ''); if (id) { window.opener.postMessage({ type: 'meta-oauth-ready', credential_id: id }, window.location.origin); setTimeout(() => window.close(), 200) } } else openBusinessDiscovery(String(route.query.credential_id || '')) } else if (auth === 'error') { const message = String(route.query.message || 'Meta 授权失败或已取消'); if (window.opener) { window.opener.postMessage({ type: 'meta-oauth-error', message }, window.location.origin); setTimeout(() => window.close(), 200) } else { addDialogVisible.value = true; oauthStep.value = 'login'; oauthError.value = message } } }
onMounted(async () => { window.addEventListener('message', handleOAuthMessage); await load(); handleOAuthRoute() })
onBeforeUnmount(() => window.removeEventListener('message', handleOAuthMessage))
</script>

<style scoped lang="scss">
.page-container{min-height:100%}.page-head{display:flex;justify-content:space-between;gap:24px;margin-bottom:18px}.eyebrow{color:#6b7f95;font-size:12px}.page-title{margin:5px 0;color:#102a43;font-size:28px}.page-subtitle{margin:0;color:#627d98;font-size:13px}.head-actions,.node-actions{display:flex;align-items:center;gap:8px}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}.stat-label,.stat-desc{color:#829ab1;font-size:12px}.stat-value{margin:7px 0;color:#102a43;font-size:25px;font-weight:700}.tree-card{border:none}.card-header{display:flex;align-items:center;justify-content:space-between;gap:16px}.card-header span{margin-left:10px;color:#9fb3c8;font-size:12px}.search-input{width:340px}.tree-wrap{min-height:380px}.tree-node{display:flex;justify-content:space-between;align-items:center;width:100%;padding-right:10px;gap:15px}.node-main{display:flex;align-items:center;gap:8px;min-width:0}.node-name{max-width:460px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.oauth-hero{display:flex;align-items:center;gap:14px;margin-bottom:20px}.oauth-logo{display:flex;align-items:center;justify-content:center;width:48px;height:48px;border-radius:14px;background:#eef6ff;color:#1877f2;font-size:24px}.oauth-title{font-size:18px;font-weight:600;color:#102a43}.oauth-subtitle,.steps p,.select-desc{color:#829ab1;font-size:12px}.steps{display:grid;gap:15px;margin-bottom:20px}.steps p{margin:5px 0 0}.business-list{display:flex;flex-direction:column;width:100%;gap:10px;margin-top:15px}.business-option{padding:14px;border:1px solid #e5edf5;border-radius:10px;cursor:pointer}.business-option.selected{border-color:#409eff;background:#f5f9ff}.business-option>div{margin:7px 0 0 24px;color:#829ab1;font-size:12px}.select-title{margin-top:15px;font-size:16px;font-weight:600;color:#243b53}.success-state{text-align:center;padding:45px}.success-state .el-icon{font-size:52px;color:#18a058}.success-state h3{margin:15px 0 5px}.success-state p{color:#829ab1}.drawer-button{margin-top:20px}@media(max-width:900px){.stats-grid{grid-template-columns:repeat(2,1fr)}.page-head,.card-header{flex-direction:column;align-items:stretch}.search-input{width:100%}}@media(max-width:600px){.stats-grid{grid-template-columns:1fr}.tree-node{align-items:flex-start;flex-direction:column}.node-actions{width:100%}}
</style>

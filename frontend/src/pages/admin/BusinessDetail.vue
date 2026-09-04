<template>
  <div class="page-container" v-loading="loading">
    <div class="page-head">
      <div class="head-left">
        <el-button link :icon="ArrowLeft" @click="goBack">返回</el-button>
        <div>
          <h2 class="page-title">
            {{ detail?.name || 'BM 详情' }}
            <el-tag :type="statusType(detail)" effect="light" class="ml8">{{ statusLabel(detail) }}</el-tag>
          </h2>
          <p class="page-subtitle" v-if="detail">Business ID: {{ detail.business_id }}</p>
          <div v-if="detail" class="oauth-status">
            <el-tag :type="detail.credential_status === 'ACTIVE' ? 'success' : 'warning'" effect="plain">
              {{ detail.credential_status === 'ACTIVE' ? 'Meta 已授权' : '未完成 Meta 授权' }}
            </el-tag>
            <el-button link type="primary" size="small" @click="authorizeMeta">
              {{ detail.credential_status === 'ACTIVE' ? '重新授权' : '立即授权' }}
            </el-button>
          </div>
        </div>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" :loading="syncing" @click="syncAccounts">同步</el-button>
        <el-button :icon="Connection" @click="verifyConnection">验证连接</el-button>
        <el-button type="primary" :icon="Plus" @click="openImport">导入账户</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="stat-row">
      <el-col :xs="12" :sm="6"><el-card shadow="never" class="stat-card"><div class="stat-value">{{ stats.total }}</div><div class="stat-label">广告账户</div></el-card></el-col>
      <el-col :xs="12" :sm="6"><el-card shadow="never" class="stat-card"><div class="stat-value ok">{{ stats.system_active }}</div><div class="stat-label">可投放</div></el-card></el-col>
      <el-col :xs="12" :sm="6"><el-card shadow="never" class="stat-card"><div class="stat-value warn">{{ stats.system_disabled }}</div><div class="stat-label">系统停用</div></el-card></el-col>
      <el-col :xs="12" :sm="6"><el-card shadow="never" class="stat-card"><div class="stat-value danger">{{ stats.meta_abnormal }}</div><div class="stat-label">Meta 异常</div></el-card></el-col>
    </el-row>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="广告账户" name="accounts">
          <el-table :data="accounts" stripe style="width: 100%">
            <el-table-column prop="account_name" label="账户名" min-width="150" />
            <el-table-column prop="account_id" label="Account ID" min-width="150" />
            <el-table-column label="Meta 状态" width="120"><template #default="{ row }"><el-tag v-if="row.account_status" :type="metaStatusType(row.account_status)" effect="plain" size="small">{{ metaStatusLabel(row.account_status) }}</el-tag><span v-else class="sub-text">未同步</span></template></el-table-column>
            <el-table-column label="系统状态" width="120"><template #default="{ row }"><el-tag :type="row.system_status === 'ACTIVE' ? 'success' : 'danger'" effect="light" round size="small">{{ row.system_status === 'ACTIVE' ? '可投放' : '已停用' }}</el-tag></template></el-table-column>
            <el-table-column label="已消费" min-width="130"><template #default="{ row }">{{ formatMoney(row.amount_spent, row.currency) }}</template></el-table-column>
            <el-table-column label="最后同步" width="170"><template #default="{ row }">{{ formatTime(row.last_synced_at) }}</template></el-table-column>
            <el-table-column label="操作" width="120" fixed="right"><template #default="{ row }"><el-button link :type="row.system_status === 'ACTIVE' ? 'danger' : 'success'" size="small" @click="toggleStatus(row)">{{ row.system_status === 'ACTIVE' ? '停用' : '启用' }}</el-button></template></el-table-column>
            <template #empty><el-empty description="该 BM 下暂无账户，可点击「导入账户」" /></template>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="同步记录" name="logs">
          <el-table :data="syncLogs" stripe style="width: 100%">
            <el-table-column prop="sync_type" label="类型" width="130" />
            <el-table-column label="状态" width="150"><template #default="{ row }"><el-tag :type="logStatusType(row.status)" effect="plain" size="small">{{ row.status }}</el-tag></template></el-table-column>
            <el-table-column label="结果" width="130"><template #default="{ row }">{{ row.success_count }} / {{ row.total_count }}</template></el-table-column>
            <el-table-column prop="error_message" label="错误" min-width="220" show-overflow-tooltip />
            <el-table-column label="开始时间" width="170"><template #default="{ row }">{{ formatTime(row.started_at) }}</template></el-table-column>
            <template #empty><el-empty description="暂无同步记录" /></template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="importVisible" title="导入广告账户" width="680px" destroy-on-close>
      <div class="import-tip">从 Meta 拉取 {{ detail?.name }} 下的账户，勾选后导入。<el-button link type="primary" :loading="fetching" @click="fetchFromMeta">重新拉取</el-button></div>
      <el-table :data="candidates" v-loading="fetching" stripe style="width: 100%" @selection-change="onCandidatesChange" ref="candidateTableRef">
        <el-table-column type="selection" width="46" /><el-table-column prop="name" label="账户名" min-width="160" /><el-table-column prop="id" label="Account ID" min-width="150" /><el-table-column prop="account_status" label="状态" width="110" /><el-table-column prop="currency" label="货币" width="90" />
        <el-table-column label="已存在" width="100"><template #default="{ row }"><el-tag v-if="row._existing" type="info" size="small" effect="plain">已在库中</el-tag><span v-else class="sub-text">新账户</span></template></el-table-column>
        <template #empty><el-empty description="点击上方「重新拉取」获取 Meta 账户列表" /></template>
      </el-table>
      <template #footer><span class="selected-tip">已选择：{{ selectedCandidates.length }}</span><el-button @click="importVisible = false">取消</el-button><el-button type="primary" :loading="importing" @click="submitImport">导入选中</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh, Connection, Plus } from '@element-plus/icons-vue'
import { metaAccountApi, credentialApi, accountApi, type AdAccountItem, type MetaAccountItem, type SyncLogItem } from '@/api/admin'
import { formatMoney } from '@/utils/money'
import request from '@/utils/request'

const route = useRoute()
const router = useRouter()
const businessId = computed(() => String(route.params.id || ''))
const loading = ref(false)
const detail = ref<MetaAccountItem | null>(null)
const accounts = ref<AdAccountItem[]>([])
const syncLogs = ref<SyncLogItem[]>([])
const activeTab = ref('accounts')
const syncing = ref(false)
const stats = ref({ total: 0, system_active: 0, system_disabled: 0, meta_abnormal: 0 })
const importVisible = ref(false)
const fetching = ref(false)
const importing = ref(false)
const candidates = ref<any[]>([])
const selectedCandidates = ref<any[]>([])
const candidateTableRef = ref<any>(null)

function formatTime(v: string | null) { if (!v) return '-'; return v.replace('T', ' ').slice(0, 19) }
function statusLabel(row: MetaAccountItem | null) { if (!row) return '-'; return ({ ACTIVE: '启用', DISABLED: '已禁用', ARCHIVED: '已归档' } as Record<string, string>)[row.status] || row.status }
function statusType(row: MetaAccountItem | null): 'success' | 'danger' | 'info' { if (!row) return 'info'; if (row.status === 'ACTIVE') return 'success'; if (row.status === 'DISABLED') return 'danger'; return 'info' }
function metaStatusLabel(v: string) { return ({ '1': '正常', '2': '已禁用', '3': '未结算', '7': '风险审核中', '8': '待结算', '9': '宽限期', '100': '待关闭', '101': '已关闭', ACTIVE: '正常', DISABLED: '已禁用', UNSETTLED: '未结算' } as Record<string, string>)[v] || v }
function metaStatusType(v: string): 'success' | 'danger' | 'warning' | 'info' { if (v === '1' || v === 'ACTIVE') return 'success'; if (v === '2' || v === 'DISABLED' || v === '101') return 'danger'; if (v === '3' || v === '7' || v === '8' || v === '100') return 'warning'; return 'info' }
function logStatusType(status: string): 'success' | 'danger' | 'warning' | 'info' { if (status === 'SUCCESS') return 'success'; if (status === 'FAILED') return 'danger'; if (status === 'PARTIAL_SUCCESS') return 'warning'; return 'info' }

async function authorizeMeta() { try { const { data } = await credentialApi.oauthAuthorize(businessId.value); window.location.assign(data.authorization_url) } catch {} }
async function loadDetail() { loading.value = true; try { const { data } = await metaAccountApi.detail(businessId.value); detail.value = data; accounts.value = data.accounts || []; stats.value = data.account_stats || stats.value } catch {} finally { loading.value = false } }
async function loadLogs() { try { const { data } = await metaAccountApi.syncLogs(businessId.value, { limit: 30 }); syncLogs.value = data } catch { syncLogs.value = [] } }
async function syncAccounts() { syncing.value = true; try { const { data } = await metaAccountApi.syncAccounts(businessId.value); ElMessage.success(`同步任务已提交（${data.job_id.slice(0, 8)}…）`); setTimeout(async () => { await loadDetail(); await loadLogs() }, 3000) } catch {} finally { syncing.value = false } }
async function verifyConnection() { try { const { data } = await metaAccountApi.verifyConnection(businessId.value); if (data.dev_mode) ElMessage.warning('开发模式：未配置 FB 凭据，未做真实校验'); else if (data.ok) ElMessage.success('连接正常，Business ID 校验通过'); else ElMessage.error('校验失败：' + (data.error || '未知错误')) } catch {} }
async function toggleStatus(row: AdAccountItem) { try { if (row.system_status === 'ACTIVE') await accountApi.freeze(row.id, '管理员停用'); else await accountApi.unfreeze(row.id); await loadDetail() } catch {} }
function openImport() { importVisible.value = true; fetchFromMeta() }
async function fetchFromMeta() { fetching.value = true; try { const { data } = await request.get(`/api/v1/meta-accounts/${businessId.value}/ad-accounts/from-meta`); const existingIds = new Set(accounts.value.map((a) => a.account_id)); candidates.value = (data.accounts || []).map((a: any) => ({ id: a.id, name: a.name, account_status: a.account_status, currency: a.currency, _existing: existingIds.has(a.id) })); if (data.dev_mode) ElMessage.warning('开发模式：未配置 FB 凭据，无法拉取真实账户列表') } catch {} finally { fetching.value = false } }
function onCandidatesChange(rows: any[]) { selectedCandidates.value = rows }
async function submitImport() { if (!selectedCandidates.value.length) { ElMessage.warning('请至少勾选一个账户'); return }; importing.value = true; try { await request.post(`/api/v1/meta-accounts/${businessId.value}/ad-accounts/import`, { account_ids: selectedCandidates.value.map((a) => a.id) }); ElMessage.success('导入完成'); importVisible.value = false; await loadDetail() } catch {} finally { importing.value = false } }
function goBack() { router.push({ name: 'AdminMetaAccounts' }) }
onMounted(async () => { await loadDetail(); await loadLogs() })
</script>

<style scoped>
.head-left { display: flex; align-items: flex-start; gap: 10px; }
.head-actions { display: flex; gap: 8px; }
.oauth-status { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.ml8 { margin-left: 8px; }
.stat-row { margin-bottom: 16px; }
.stat-card { text-align: center; }
.stat-value { font-size: 26px; font-weight: 600; }
.stat-value.ok { color: #16a34a; }
.stat-value.warn { color: #d97706; }
.stat-value.danger { color: #dc2626; }
.stat-label { margin-top: 4px; font-size: 13px; color: #6b7280; }
.sub-text { color: #9ca3af; font-size: 12px; }
.import-tip { margin-bottom: 12px; font-size: 13px; color: #4b5563; }
.selected-tip { margin-right: 12px; font-size: 13px; color: #6b7280; }
</style>

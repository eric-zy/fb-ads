<template>
  <div class="reports-page">
    <div class="page-head">
      <div><div class="eyebrow">数据分析</div><h2>投放统计</h2><p>按账户时区统计最近 {{ days }} 天，点击数据行查看下级投放对象。</p></div>
      <div><el-button v-if="canManageRevenue" :disabled="!selectedAccount" @click="openRevenue">导入业务收入</el-button><el-button :disabled="!parentStack.length" @click="goBack">返回上级</el-button></div>
    </div>
    <el-card shadow="never" class="filters">
      <el-select v-model="accountId" placeholder="搜索广告账户名称或 ID" filterable remote :remote-method="searchAccounts" :loading="accountsLoading" @change="resetAndLoad"><el-option v-for="account in accounts" :key="account.id" :label="`${account.account_name || account.account_id} · ${account.currency}`" :value="account.id" /></el-select>
      <el-select v-model="days" @change="loadBreakdown"><el-option label="近 7 天" :value="7"/><el-option label="近 30 天" :value="30"/><el-option label="近 90 天" :value="90"/></el-select>
    </el-card>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <el-alert title="ROAS 使用 Meta 回传的转化价值。业务收入、利润和 ROI 使用导入收入；缺少收入时显示 —。" type="info" :closable="false" class="metric-note"/>
    <el-empty v-if="!accountId" description="请选择广告账户"/>
    <el-card v-else shadow="never"><template #header>{{ levelLabel }}统计</template>
      <el-table v-loading="loading" :data="items" stripe @row-click="drill">
        <el-table-column label="名称 / Meta ID" min-width="230"><template #default="{ row }"><div>{{ row.entity_name }}</div><small>{{ row.entity_id }}</small></template></el-table-column>
        <el-table-column prop="currency" label="币种" width="80"/><el-table-column label="花费"><template #default="{ row }">{{ metric(row.spend) }}</template></el-table-column><el-table-column prop="impressions" label="展示"/><el-table-column prop="clicks" label="点击"/><el-table-column prop="conversions" label="转化"/>
        <el-table-column label="转化率"><template #default="{ row }">{{ Number(row.conversion_rate || 0).toFixed(2) }}%</template></el-table-column>
        <el-table-column label="CPA"><template #default="{ row }">{{ metric(row.cpa) }}</template></el-table-column><el-table-column label="Meta ROAS"><template #default="{ row }">{{ metric(row.roas) }}</template></el-table-column>
        <el-table-column label="业务收入"><template #default="{ row }">{{ metric(row.revenue) }}</template></el-table-column><el-table-column label="利润"><template #default="{ row }">{{ metric(row.profit) }}</template></el-table-column><el-table-column label="ROI"><template #default="{ row }">{{ row.roi == null ? '—' : `${(row.roi * 100).toFixed(2)}%` }}</template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="revenueVisible" title="导入每日业务收入" width="520px" :close-on-click-modal="false">
      <el-alert title="填写该账户当日、该来源的收入总额。同一日期和来源再次导入会覆盖旧值，不同来源会合计。收入目前仅关联到账户。" type="info" :closable="false"/>
      <el-form label-width="90px" class="revenue-form" @submit.prevent="saveRevenue">
        <el-form-item label="广告账户">{{ selectedAccount?.account_name || selectedAccount?.account_id }}</el-form-item>
        <el-form-item label="日期" required><el-date-picker v-model="revenueDate" type="date" value-format="YYYY-MM-DD"/></el-form-item>
        <el-form-item label="收入来源" required><el-input v-model="revenueSource" maxlength="64" placeholder="例如 manual、order_system"/></el-form-item>
        <el-form-item label="收入总额" required><el-input v-model="revenueAmount" inputmode="decimal" placeholder="0"><template #append>{{ selectedAccount?.currency }}</template></el-input></el-form-item>
        <el-alert v-if="revenueError" :title="revenueError" type="error" :closable="false"/>
      </el-form>
      <template #footer><el-button :disabled="savingRevenue" @click="revenueVisible = false">取消</el-button><el-button type="primary" :loading="savingRevenue" @click="saveRevenue">保存收入总额</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { reportsApi, type ReportItem } from '@/api/reports'
import { useUserStore } from '@/stores/userStore'

type Level = 'account' | 'campaign' | 'adset' | 'ad'
const userStore = useUserStore()
const accounts = ref<AdAccountItem[]>([]), accountId = ref(''), days = ref(30)
const accountsLoading = ref(false)
const level = ref<Level>('account'), parentId = ref(''), items = ref<ReportItem[]>([])
const parentStack = ref<Array<{ level: Level; parentId: string }>>([])
const loading = ref(false), error = ref('')
const selectedAccount = computed(() => accounts.value.find(account => account.id === accountId.value))
const canManageRevenue = computed(() => userStore.isAdmin || userStore.hasPermission('revenue:manage'))
const levelLabel = computed(() => ({ account: '账号', campaign: 'Campaign', adset: 'AdSet', ad: '广告' }[level.value]))
const nextLevel: Partial<Record<Level, Level>> = { account: 'campaign', campaign: 'adset', adset: 'ad' }
const revenueVisible = ref(false), savingRevenue = ref(false), revenueError = ref('')
const revenueDate = ref(''), revenueSource = ref('manual'), revenueAmount = ref('')
let requestNo = 0
const metric = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 4 })
function todayInAccount() {
  let timeZone = selectedAccount.value?.timezone || 'UTC'
  try { new Intl.DateTimeFormat('en', { timeZone }).format() } catch { timeZone = 'UTC' }
  const parts = new Intl.DateTimeFormat('en', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const get = (type: string) => parts.find(part => part.type === type)?.value
  return `${get('year')}-${get('month')}-${get('day')}`
}
let accountsRequestNo = 0
async function searchAccounts(query = '') {
  const currentRequest = ++accountsRequestNo
  accountsLoading.value = true
  try {
    const selected = selectedAccount.value
    const { data } = await accountApi.list({ search: query.trim() || undefined, page: 1, page_size: 100 })
    if (currentRequest !== accountsRequestNo) return
    accounts.value = selected && !data.some(account => account.id === selected.id) ? [selected, ...data] : data
    if (!accountId.value && accounts.value.length) accountId.value = accounts.value[0].id
  } catch {
    if (currentRequest === accountsRequestNo) error.value = '账户加载失败，请检查权限或稍后重试'
  } finally {
    if (currentRequest === accountsRequestNo) accountsLoading.value = false
  }
}
async function loadBreakdown() {
  const currentRequest = ++requestNo
  if (!accountId.value) return
  loading.value = true; error.value = ''; items.value = []
  try { const { data } = await reportsApi.breakdown({ dimension: level.value, days: days.value, parent_id: parentId.value || accountId.value }); if (currentRequest === requestNo) items.value = data.items || [] }
  catch { if (currentRequest === requestNo) error.value = '统计加载失败，请检查权限或同步状态' }
  finally { if (currentRequest === requestNo) loading.value = false }
}
function resetAndLoad() { level.value = 'account'; parentId.value = ''; parentStack.value = []; void loadBreakdown() }
function drill(row: ReportItem) { const next = nextLevel[level.value]; if (!next) return; parentStack.value.push({ level: level.value, parentId: parentId.value }); level.value = next; parentId.value = row.entity_id; void loadBreakdown() }
function goBack() { const previous = parentStack.value.pop(); if (previous) { level.value = previous.level; parentId.value = previous.parentId; void loadBreakdown() } }
function openRevenue() { revenueDate.value = todayInAccount(); revenueAmount.value = ''; revenueError.value = ''; revenueVisible.value = true }
async function saveRevenue() {
  const account = selectedAccount.value
  if (!account || savingRevenue.value) return
  revenueError.value = ''
  if (!revenueDate.value || revenueDate.value > todayInAccount() || !/^[a-zA-Z0-9_.-]{1,64}$/.test(revenueSource.value)) { revenueError.value = '日期不能晚于账户当天；来源限英文字母、数字、下划线、点和短横线'; return }
  if (!/^-?\d+(\.\d+)?$/.test(revenueAmount.value.trim())) { revenueError.value = '请输入有效收入金额'; return }
  savingRevenue.value = true
  try { await reportsApi.importRevenue([{ account_id: account.id, date: revenueDate.value, source: revenueSource.value, currency: account.currency || 'USD', revenue: revenueAmount.value.trim() }]); revenueVisible.value = false; ElMessage.success('每日收入总额已保存'); await loadBreakdown() }
  catch (err: unknown) { const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail; revenueError.value = typeof detail === 'string' ? detail : '保存失败，请检查金额精度和账户权限' }
  finally { savingRevenue.value = false }
}
onMounted(async () => { await searchAccounts(); await loadBreakdown() })
</script>
<style scoped>
.reports-page{padding:4px}.page-head{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}.eyebrow{color:#829ab1;font-size:12px}.page-head h2{margin:6px 0;color:#102a43}.page-head p{margin:0;color:#627d98;font-size:13px}.filters{margin-bottom:16px}.filters .el-select{width:260px;margin-right:12px}.metric-note{margin:12px 0}small{color:#9aaabd;font-size:11px}.el-table{cursor:pointer}.revenue-form{margin-top:20px}@media(max-width:700px){.page-head{flex-direction:column;align-items:start}.filters .el-select{width:100%;margin:4px 0}}
</style>

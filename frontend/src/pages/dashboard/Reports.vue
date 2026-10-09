<template>
  <div class="reports-page">
    <div class="page-head">
      <div><div class="eyebrow">数据分析</div><h2>投放统计</h2><p>按账户时区统计 {{ dateRange?.[0] }} 至 {{ dateRange?.[1] }}（{{ days }} 天），点击数据行查看下级对象；环比对比紧邻的上一等长周期。</p></div>
      <div><el-button v-if="userStore.isAdmin" :disabled="!selectedAccount || !dateRangeValid" :loading="syncing" @click="syncReports">同步所选日期</el-button><el-button v-if="canManageRevenue" :disabled="!selectedAccount" @click="openRevenue">导入业务收入</el-button><el-button :disabled="!parentStack.length" @click="goBack">返回上级</el-button></div>
    </div>
    <el-card shadow="never" class="filters">
      <el-select v-model="accountId" placeholder="搜索广告账户名称或 ID" filterable remote :remote-method="searchAccounts" :loading="accountsLoading" @change="resetAndLoad"><el-option v-for="account in accounts" :key="account.id" :label="`${account.account_name || account.account_id} · ${account.currency}`" :value="account.id" /></el-select>
      <DateRangeFields v-model="dateRange" :today="todayInAccount()" :disabled="syncing" @validity-change="dateRangeValid = $event" @change="loadBreakdown" />
      <el-checkbox v-model="compareEnabled" @change="loadBreakdown">对比上一周期</el-checkbox>
    </el-card>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <el-alert title="转化合计为购买、线索和注册动作去重后的合计。ROAS 使用 Meta 回传的转化价值。业务收入、利润和 ROI 使用导入收入；缺少收入时显示 —。" type="info" :closable="false" class="metric-note"/>
    <el-alert v-if="qualityNote" :title="qualityNote" type="info" :closable="false" class="metric-note"/>
    <el-alert v-if="compareError" :title="compareError" type="warning" :closable="false" class="metric-note"/>
    <el-alert v-if="comparisonLoading" title="正在加载上一周期，当前周期数据可先查看" type="info" :closable="false" class="metric-note"/>
    <el-empty v-if="!accountId" description="请选择广告账户"/>
    <el-card v-else shadow="never"><template #header>{{ levelLabel }}统计</template>
      <el-table v-loading="loading" :data="items" stripe @row-click="drill">
        <el-table-column label="名称 / Meta ID" min-width="230"><template #default="{ row }"><div>{{ row.entity_name }}</div><small>{{ row.meta_id || '—' }}</small></template></el-table-column>
        <el-table-column prop="currency" label="币种" width="80"/><el-table-column label="花费"><template #default="{ row }">{{ metric(row.spend) }}</template></el-table-column>
        <el-table-column v-if="compareEnabled" label="花费环比" min-width="115"><template #default="{ row }">{{ comparison(row as ReportItem, 'spend') }}</template></el-table-column>
        <el-table-column prop="impressions" label="展示"/><el-table-column prop="clicks" label="点击"/><el-table-column prop="conversions" label="转化"/>
        <el-table-column v-if="compareEnabled" label="转化环比" min-width="115"><template #default="{ row }">{{ comparison(row as ReportItem, 'conversions') }}</template></el-table-column>
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
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { reportsApi, type ReportItem } from '@/api/reports'
import { waitForReportSync } from '@/utils/reportSync'
import { useUserStore } from '@/stores/userStore'
import DateRangeFields from '@/components/DateRangeFields.vue'
import { inclusiveDays, rangeForDays, shiftDateOnly } from '@/utils/dateRange'
import { hasCompleteCoverage, percentageChange } from '@/utils/reportComparison'

type Level = 'account' | 'campaign' | 'adset' | 'ad'
const userStore = useUserStore()
const accounts = ref<AdAccountItem[]>([]), accountId = ref('')
const dateRange = ref<[string, string] | null>(rangeForDays(30))
const dateRangeValid = ref(true)
const days = computed(() => dateRange.value ? inclusiveDays(...dateRange.value) : 30)
const dateParams = computed(() => dateRange.value ? { start_date: dateRange.value[0], end_date: dateRange.value[1] } : { days: 30 })
const accountsLoading = ref(false)
const level = ref<Level>('account'), parentId = ref(''), items = ref<ReportItem[]>([])
const previousItems = ref<Record<string, ReportItem>>({}), compareEnabled = ref(true), compareError = ref('')
const comparisonReady = ref(false), comparisonLoading = ref(false)
const parentStack = ref<Array<{ level: Level; parentId: string }>>([])
const loading = ref(false), error = ref(''), syncing = ref(false), qualityNote = ref('')
const selectedAccount = computed(() => accounts.value.find(account => account.id === accountId.value))
const canManageRevenue = computed(() => userStore.isAdmin || userStore.hasPermission('revenue:manage'))
const levelLabel = computed(() => ({ account: '账号', campaign: 'Campaign', adset: 'AdSet', ad: '广告' }[level.value]))
const nextLevel: Partial<Record<Level, Level>> = { account: 'campaign', campaign: 'adset', adset: 'ad' }
const revenueVisible = ref(false), savingRevenue = ref(false), revenueError = ref('')
const revenueDate = ref(''), revenueSource = ref('manual'), revenueAmount = ref('')
let requestNo = 0
let breakdownController: AbortController | undefined
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
  if (!dateRangeValid.value) return
  const currentRequest = ++requestNo
  breakdownController?.abort()
  const controller = new AbortController()
  breakdownController = controller
  loading.value = false; error.value = ''; compareError.value = ''; qualityNote.value = ''
  items.value = []; previousItems.value = {}; comparisonReady.value = false; comparisonLoading.value = false
  if (!accountId.value) return
  loading.value = true
  const selectedId = accountId.value, expectedDays = days.value
  const params = { dimension: level.value, ...dateParams.value, parent_id: parentId.value || selectedId }
  const config = { signal: controller.signal, skipErrorMessage: true }
  const previous = previousDateRange()
  // Attach a rejection handler immediately; the prior request may fail before the current one completes.
  const currentRequestPromise = reportsApi.breakdown(params, config)
  const previousRequest = compareEnabled.value && previous
    ? reportsApi.breakdown({ ...params, start_date: previous[0], end_date: previous[1] }, config).then(response => response.data, () => null)
    : null
  comparisonLoading.value = !!previousRequest
  try {
    const { data } = await currentRequestPromise
    if (currentRequest !== requestNo) return
    items.value = data.items || []
    const quality = data.data_quality || []
    qualityNote.value = quality.length ? quality.map((item: { status: string; covered_days: number; expected_days: number }) => {
      const labels: Record<string, string> = { FRESH: '正常', STALE: '延迟', NEVER: '未同步', INCOMPLETE: '日期未补全', FAILED: '失败', SYNCING: '同步中', PENDING: '待同步' }
      return `报表同步：${labels[item.status] || item.status}；已覆盖 ${item.covered_days}/${item.expected_days} 天`
    }).join('；') : '所选范围暂无已确认的报表同步记录'
    if (previousRequest) {
      const currentComplete = hasCompleteCoverage(quality, selectedId, expectedDays)
      if (!currentComplete) compareError.value = '当前周期同步记录未完整覆盖，暂不计算环比'
      void previousRequest.then(previousData => {
        if (currentRequest !== requestNo || controller.signal.aborted) return
        comparisonLoading.value = false
        if (!previousData) { compareError.value = '上一周期数据暂不可用，当前周期数据仍可查看'; return }
        if (!currentComplete) return
        if (!hasCompleteCoverage(previousData.data_quality, selectedId, expectedDays)) {
          compareError.value = '上一周期同步记录未完整覆盖，暂不计算环比'
          return
        }
        previousItems.value = Object.fromEntries((previousData.items || []).map(item => [item.entity_id, item]))
        comparisonReady.value = true
      })
    }
  }
  catch {
    if (currentRequest === requestNo && !controller.signal.aborted) {
      error.value = '统计加载失败，请检查权限或同步状态'
      comparisonLoading.value = false
      controller.abort()
    }
  }
  finally { if (currentRequest === requestNo) loading.value = false }
}
function previousDateRange(): [string, string] | null {
  if (!dateRange.value) return null
  const [start, end] = dateRange.value
  const daysCount = inclusiveDays(start, end)
  return [shiftDateOnly(start, -daysCount), shiftDateOnly(end, -daysCount)]
}
function comparison(row: ReportItem, field: 'spend' | 'conversions') {
  if (!comparisonReady.value) return '—'
  const previous = previousItems.value[row.entity_id]
  if (previous && previous.currency !== row.currency) return '—'
  // A fully synchronized period with no row means this entity had no delivery.
  return percentageChange(row[field], previous ? previous[field] : 0)
}
let reportController: AbortController | undefined
async function syncReports() {
  if (!dateRangeValid.value) return
  syncing.value = true
  reportController = new AbortController()
  let syncError = ''
  try {
    const { data } = await reportsApi.sync({ account_id: accountId.value, ...dateParams.value })
    await waitForReportSync(data.task_ids || [], reportController.signal)
    ElMessage.success('报表同步完成')
  } catch (err) {
    if (!reportController.signal.aborted) syncError = err instanceof Error ? err.message : '同步失败'
  } finally {
    if (!reportController.signal.aborted) {
      await loadBreakdown()
      if (syncError) error.value = syncError
    }
    syncing.value = false
  }
}
onUnmounted(() => { ++requestNo; breakdownController?.abort(); reportController?.abort() })
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
onMounted(async () => { await searchAccounts(); dateRange.value = rangeForDays(30, todayInAccount()); await loadBreakdown() })
</script>
<style scoped>
.reports-page{padding:4px}.page-head{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}.eyebrow{color:#829ab1;font-size:12px}.page-head h2{margin:6px 0;color:#102a43}.page-head p{margin:0;color:#627d98;font-size:13px}.filters{margin-bottom:16px}.filters :deep(.el-card__body){display:flex;flex-wrap:wrap;align-items:center;gap:12px}.filters .el-select{width:260px}.metric-note{margin:12px 0}small{color:#9aaabd;font-size:11px}.el-table{cursor:pointer}.revenue-form{margin-top:20px}@media(max-width:700px){.page-head{flex-direction:column;align-items:start}.filters .el-select{width:100%;margin:4px 0}}
</style>

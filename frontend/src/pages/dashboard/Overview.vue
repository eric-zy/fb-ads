<template>
  <div class="overview-page">
    <div class="page-toolbar">
      <div>
        <h2>工作台</h2>
        <p>只展示当前用户有权访问的广告账户、投放任务和 Meta 数据。</p>
      </div>
      <div class="toolbar-actions">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="false"
          :disabled="loading"
          @change="scheduleLoad"
        />
        <el-button :icon="Refresh" :loading="loading" @click="loadSummary">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="scope-alert" />

    <el-alert
      v-if="summary && summary.scope.account_count === 0"
      title="当前账号没有可见广告账户"
      description="请联系管理员分配广告账户后再查看投放数据。"
      type="info"
      :closable="false"
      show-icon
      class="scope-alert"
    />

    <div v-if="summary && summary.freshness.status !== 'FRESH' && summary.scope.account_count" class="alert-with-action">
      <el-alert :title="freshnessText" :description="freshnessDescription" type="warning" :closable="false" show-icon />
      <el-button v-if="canSyncReports" link type="primary" :loading="syncLoading" @click="syncReports">立即同步</el-button>
      <el-button v-else link type="primary" @click="goToReports">查看同步入口</el-button>
    </div>

    <el-alert
      v-if="currencyTotals.length > 1"
      :title="`当前范围包含 ${currencyTotals.length} 种币种，金额未进行汇率换算`"
      description="请通过币种选择器分别查看各币种的消耗、趋势和转化数据。"
      type="info"
      :closable="false"
      show-icon
      class="scope-alert"
    />

    <el-row :gutter="16" class="stat-cards">
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card">
          <div class="stat-header"><span>区间消耗</span><el-icon><Money /></el-icon></div>
          <div v-if="primaryTotal" class="stat-value">{{ money(primaryTotal.spend, primaryTotal.currency) }}</div>
          <div v-else class="stat-value muted">—</div>
          <div class="stat-footer">{{ primaryTotal?.currency || '未同步' }} · 币种独立统计 · {{ rangeText }}</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card">
          <div class="stat-header"><span>活跃系列</span><el-icon><Promotion /></el-icon></div>
          <div class="stat-value">{{ summary?.kpis.active_campaigns ?? 0 }}</div>
          <div class="stat-footer">共 {{ summary?.kpis.total_campaigns ?? 0 }} 个未删除系列</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card">
          <div class="stat-header"><span>平均 CTR</span><el-icon><TrendCharts /></el-icon></div>
          <div class="stat-value">{{ summary ? `${summary.kpis.average_ctr.toFixed(2)}%` : '—' }}</div>
          <div class="stat-footer">按展示量加权汇总当前可见账户</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card" :class="{ 'risk-alert': pendingCount > 0 }">
          <div class="stat-header"><span>待处理事项</span><el-icon><Warning /></el-icon></div>
          <div class="stat-value">{{ pendingCount }}</div>
          <div class="stat-footer">告警 {{ summary?.kpis.open_alerts || 0 }} · 失败任务 {{ summary?.kpis.failed_jobs || 0 }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="content-row">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="card-header">
              <span>消耗趋势</span>
              <el-select v-if="currencyTotals.length" v-model="selectedCurrency" size="small" class="currency-selector">
                <el-option v-for="item in currencyTotals" :key="item.currency" :label="item.currency" :value="item.currency" />
              </el-select>
            </div>
          </template>
          <div v-if="trendRows.length" ref="chartRef" class="spend-chart"></div>
          <el-empty v-else description="当前范围暂无报表数据" :image-size="70" />
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="card-header"><span>最近任务</span><el-button link type="primary" @click="goToTasks">查看全部</el-button></div>
          </template>
          <el-table :data="summary?.recent_tasks || []" size="small" height="300" @row-click="goToTasks">
            <el-table-column label="动作" width="100">
              <template #default="{ row }">{{ actionLabel(row.action_type) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }"><el-tag :type="getStatusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="结果" min-width="100">
              <template #default="{ row }">{{ row.success_count }}/{{ row.total_accounts }} 成功<span v-if="row.failed_count"> · {{ row.failed_count }} 失败</span></template>
            </el-table-column>
            <el-table-column label="创建时间" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!summary?.recent_tasks.length" description="暂无任务" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="content-row">
      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header><div class="card-header"><span>投放健康度</span><el-button link type="primary" @click="goToCampaigns">查看广告系列</el-button></div></template>
          <div class="health-grid">
            <div v-for="item in healthItems" :key="item.key" class="health-item"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div>
          </div>
          <el-alert v-if="summary?.kpis.status_drift" :title="`${summary.kpis.status_drift} 个对象存在期望状态与 Meta 状态不一致`" type="warning" :closable="false" class="inline-alert" />
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="12">
        <el-card shadow="never">
          <template #header><div class="card-header"><span>未处理告警</span><el-button link type="primary" @click="goToRiskControl">风控中心</el-button></div></template>
          <div v-if="summary?.alerts.length" class="alert-list">
            <div v-for="alert in summary.alerts" :key="alert.id" class="alert-item" role="button" tabindex="0" @click="goToRiskControl">
              <el-tag type="warning" size="small">{{ alertTypeLabel(alert.alert_type) }}</el-tag>
              <div class="alert-content"><strong>{{ alert.title }}</strong><span>{{ alert.message }}</span><small>{{ formatDateTime(alert.created_at) }}</small></div>
            </div>
          </div>
          <el-empty v-else description="暂无未处理告警" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="quick-card">
      <template #header><div class="card-header"><span>快速操作</span><small>{{ scopeText }}</small></div></template>
      <div class="quick-actions">
        <el-button v-if="canPublish" type="primary" :disabled="!hasAccounts" :title="hasAccounts ? '' : '当前没有可见广告账户'" @click="goToBatchPublish"><el-icon><Promotion /></el-icon>批量投放广告</el-button>
        <el-button v-if="canPublish" type="success" :disabled="!hasAccounts" :title="hasAccounts ? '' : '当前没有可见广告账户'" @click="goToScheduledTasks"><el-icon><Timer /></el-icon>创建定时任务</el-button>
        <el-button type="warning" @click="goToRiskControl"><el-icon><Warning /></el-icon>查看风险状态</el-button>
        <el-button type="info" @click="goToReports"><el-icon><PieChart /></el-icon>查看报表</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Money, PieChart, Promotion, Refresh, Timer, TrendCharts, Warning } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { formatRequestError } from '@/utils/request'
import { useAccountStore } from '@/stores/accountStore'
import { useUserStore } from '@/stores/userStore'
import { reportsApi, workbenchApi, type WorkbenchSummary } from '@/api/reports'

const router = useRouter()
const accountStore = useAccountStore()
const userStore = useUserStore()
const loading = ref(false)
const summary = ref<WorkbenchSummary | null>(null)
const loadError = ref('')
const syncLoading = ref(false)
const dateRange = ref<[string, string] | null>(null)
const selectedCurrency = ref('')
const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let abortController: AbortController | null = null
let requestSequence = 0
let loadTimer: ReturnType<typeof setTimeout> | null = null

const currencyTotals = computed(() => summary.value?.currency_totals || [])
const primaryTotal = computed(() => currencyTotals.value.find(item => item.currency === selectedCurrency.value) || currencyTotals.value[0] || null)
const chartCurrency = computed(() => selectedCurrency.value || currencyTotals.value[0]?.currency || '')
const trendRows = computed(() => (summary.value?.trend || []).filter(row => row.currency === chartCurrency.value))
const rangeText = computed(() => summary.value ? `${summary.value.range.start_date} 至 ${summary.value.range.end_date}` : '当前范围')
const pendingCount = computed(() => (summary.value?.kpis.open_alerts || 0) + (summary.value?.kpis.failed_jobs || 0))
const hasAccounts = computed(() => (summary.value?.scope.account_count || 0) > 0)
const freshnessText = computed(() => {
  if (!summary.value) return ''
  const freshness = summary.value.freshness
  if (freshness.status === 'NEVER') return '当前可见账户尚未同步报表数据'
  return `有 ${freshness.stale_account_count + freshness.never_synced_account_count} 个账户的数据需要关注`
})
const freshnessDescription = computed(() => {
  if (!summary.value) return ''
  const freshness = summary.value.freshness
  const details: string[] = []
  if (freshness.stale_account_count) details.push(`${freshness.stale_account_count} 个账户已延迟`)
  if (freshness.never_synced_account_count) details.push(`${freshness.never_synced_account_count} 个账户从未同步`)
  return `${details.join('，')}。当前工作台不会用 0 代替未知数据，请到报表页检查同步状态。`
})
const scopeText = computed(() => {
  const count = summary.value?.scope.account_count ?? 0
  return accountStore.selectedAccount ? `当前账户：${accountStore.selectedAccount.account_name}` : `全部可见账户 ${count} 个`
})
const canPublish = computed(() => userStore.isAdmin || userStore.hasPermission('job:create'))
const canSyncReports = computed(() => userStore.isAdmin)
const healthItems = computed(() => {
  const counts = summary.value?.delivery_health.status_counts || {}
  return [
    { key: 'ACTIVE', label: '投放中', value: counts.ACTIVE || 0 },
    { key: 'PAUSED', label: '已暂停', value: counts.PAUSED || 0 },
    { key: 'ARCHIVED', label: '已归档', value: counts.ARCHIVED || 0 },
    { key: 'DELETED', label: '已删除', value: counts.DELETED || 0 },
  ]
})

const money = (value: number, currency: string) => {
  const symbols: Record<string, string> = { USD: '$', EUR: '€', GBP: '£', CNY: '¥', JPY: '¥' }
  return `${symbols[currency] || currency + ' '}${Number(value || 0).toFixed(currency === 'JPY' ? 0 : 2)}`
}

const dateParams = () => {
  const [start_date, end_date] = dateRange.value || []
  return { account_id: accountStore.selectedAccountId || undefined, start_date, end_date }
}

const renderChart = () => {
  if (!chartRef.value) return
  if (chart) chart.dispose()
  if (!trendRows.value.length) return
  chart = echarts.init(chartRef.value)
  chart.setOption({
    tooltip: { trigger: 'axis', valueFormatter: (value: number) => money(value, chartCurrency.value) },
    grid: { left: 55, right: 20, top: 20, bottom: 35 },
    xAxis: { type: 'category', data: trendRows.value.map(row => row.date) },
    yAxis: { type: 'value' },
    series: [{ name: chartCurrency.value, data: trendRows.value.map(row => row.spend), type: 'line', smooth: true, itemStyle: { color: '#667eea' }, areaStyle: { color: 'rgba(102, 126, 234, 0.1)' } }],
  })
  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(chartRef.value)
}

const scheduleLoad = () => {
  if (loadTimer) clearTimeout(loadTimer)
  loadTimer = setTimeout(() => {
    loadTimer = null
    void loadSummary()
  }, 250)
}

const loadSummary = async () => {
  const sequence = ++requestSequence
  abortController?.abort()
  const controller = new AbortController()
  abortController = controller
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await workbenchApi.summary(dateParams(), { signal: controller.signal, skipErrorMessage: true })
    if (sequence !== requestSequence) return
    summary.value = data
    if (!currencyTotals.value.some(item => item.currency === selectedCurrency.value)) {
      selectedCurrency.value = currencyTotals.value[0]?.currency || ''
    }
    if (!dateRange.value) dateRange.value = [data.range.start_date, data.range.end_date]
    await nextTick()
    renderChart()
  } catch (error: any) {
    if (sequence !== requestSequence || controller.signal.aborted || error?.code === 'ERR_CANCELED') return
    loadError.value = error?.response?.status === 403
      ? '当前账号没有工作台访问权限'
      : formatRequestError(error) || '工作台数据加载失败，请稍后重试'
    ElMessage.warning(loadError.value)
  } finally {
    if (sequence === requestSequence) {
      loading.value = false
      abortController = null
    }
  }
}

const syncReports = async () => {
  syncLoading.value = true
  try {
    const { data } = await reportsApi.sync({ account_id: accountStore.selectedAccountId || undefined, days: 7 })
    ElMessage.success(`已提交 ${data.account_count || 0} 个账户的同步任务`)
    await loadSummary()
  } finally {
    syncLoading.value = false
  }
}

const formatDateTime = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(date)
}

const actionLabel = (action: string) => ({
  CREATE: '创建投放', PAUSE: '暂停投放', ENABLE: '启用投放', ARCHIVE: '归档', DELETE: '删除', RESTORE: '恢复', UPDATE_BUDGET: '调整预算', SYNC: '数据同步',
}[action] || action)
const statusLabel = (status: string) => ({
  RUNNING: '执行中', QUEUED: '排队中', PENDING: '待执行', VALIDATING: '校验中', SUCCESS: '成功', PARTIAL_SUCCESS: '部分成功', FAILED: '失败', CANCELLED: '已取消',
}[status] || status)
const alertTypeLabel = (type: string) => ({
  AUTH: '授权异常', PERMISSION: '权限异常', RATE_LIMIT: '频率限制', SYNC_FAILED: '同步失败', DATA_STALE: '数据延迟', SYSTEM: '系统异常',
}[type] || type)
const getStatusType = (status: string) => ({
  RUNNING: 'success', QUEUED: 'warning', PENDING: 'info', VALIDATING: 'info', SUCCESS: 'success', PARTIAL_SUCCESS: 'warning', FAILED: 'danger', CANCELLED: 'info',
}[status] || 'info')

const goToBatchPublish = () => router.push('/dashboard/batch-publish')
const goToScheduledTasks = () => router.push('/dashboard/scheduled-tasks')
const goToRiskControl = () => router.push('/dashboard/risk-control')
const goToReports = () => router.push('/dashboard/reports')
const goToCampaigns = () => router.push('/dashboard/campaigns')
const goToTasks = () => router.push('/dashboard/jobs')

watch(() => accountStore.selectedAccountId, scheduleLoad)
watch(chartCurrency, async () => {
  await nextTick()
  renderChart()
})
onMounted(() => void loadSummary())
onBeforeUnmount(() => {
  if (loadTimer) clearTimeout(loadTimer)
  abortController?.abort()
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<style scoped lang="scss">
.overview-page { min-height: 100%; }
.page-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; h2 { margin: 0 0 6px; font-size: 22px; } p { margin: 0; color: #909399; font-size: 13px; } }
.toolbar-actions { display: flex; gap: 10px; align-items: center; }
.scope-alert { margin-bottom: 16px; }
.alert-with-action { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; :deep(.el-alert) { flex: 1; } }
.stat-cards { margin-bottom: 16px; }
.stat-card { background: #fff; border-radius: 8px; padding: 18px; box-shadow: 0 1px 4px rgba(0, 0, 0, .06); .stat-header { display: flex; justify-content: space-between; color: #909399; font-size: 14px; } .stat-header .el-icon { color: #667eea; font-size: 22px; } .stat-value { margin: 15px 0 8px; color: #303133; font-size: 27px; font-weight: 600; } .stat-value.muted { color: #c0c4cc; } .stat-footer { color: #909399; font-size: 12px; } &.risk-alert { border-left: 4px solid #e6a23c; } }
.content-row { margin-bottom: 16px; }
.chart-card { min-height: 360px; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-weight: 600; }
.currency-selector { width: 92px; }
.spend-chart { width: 100%; height: 300px; }
.health-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.health-item { padding: 14px; background: #f7f9fc; border-radius: 8px; display: flex; flex-direction: column; gap: 8px; color: #909399; font-size: 13px; strong { color: #303133; font-size: 24px; } }
.inline-alert { margin-top: 16px; }
.alert-list { display: flex; flex-direction: column; gap: 12px; min-height: 260px; }
.alert-item { display: flex; gap: 10px; align-items: flex-start; padding-bottom: 10px; border-bottom: 1px solid #ebeef5; cursor: pointer; &:hover { background: #f7f9fc; } .alert-content { display: flex; flex-direction: column; gap: 4px; min-width: 0; strong { color: #303133; } span { color: #606266; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } small { color: #c0c4cc; font-size: 11px; } } }
.quick-card { margin-bottom: 16px; }
.card-header small { color: #909399; font-weight: 400; }
.quick-actions { display: flex; gap: 12px; flex-wrap: wrap; }
@media (max-width: 800px) { .page-toolbar { align-items: flex-start; flex-direction: column; } .toolbar-actions { width: 100%; .el-date-editor { flex: 1; } } .health-grid { grid-template-columns: repeat(2, 1fr); } .alert-with-action { align-items: flex-start; flex-direction: column; } }
</style>

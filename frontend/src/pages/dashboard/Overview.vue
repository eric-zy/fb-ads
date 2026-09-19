<template>
  <div class="overview-page" v-loading="loading">
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
          @change="loadSummary"
        />
        <el-button :icon="Refresh" @click="loadSummary">刷新</el-button>
      </div>
    </div>

    <el-alert
      v-if="summary && summary.scope.account_count === 0"
      title="当前账号没有可见广告账户"
      description="请联系管理员分配广告账户后再查看投放数据。"
      type="info"
      :closable="false"
      show-icon
      class="scope-alert"
    />

    <el-alert
      v-if="summary && summary.freshness.status !== 'FRESH' && summary.scope.account_count"
      :title="freshnessText"
      :description="summary.freshness.status === 'NEVER' ? '当前范围还没有同步到报表数据，工作台不会用 0 代替未知数据。' : '请从报表页或账号同步入口发起回补。'"
      type="warning"
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
          <div class="stat-footer">{{ primaryTotal?.currency || '未同步' }} · {{ rangeText }}</div>
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
          <div class="stat-footer">基于当前范围可见账户汇总</div>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card" :class="{ 'risk-alert': (summary?.kpis.open_alerts || 0) > 0 }">
          <div class="stat-header"><span>待处理事项</span><el-icon><Warning /></el-icon></div>
          <div class="stat-value">{{ (summary?.kpis.open_alerts || 0) + (summary?.kpis.failed_jobs || 0) }}</div>
          <div class="stat-footer">告警 {{ summary?.kpis.open_alerts || 0 }} · 失败任务 {{ summary?.kpis.failed_jobs || 0 }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16" class="content-row">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="card-header"><span>消耗趋势</span><el-tag v-if="chartCurrency" size="small" effect="plain">{{ chartCurrency }}</el-tag></div>
          </template>
          <div id="spend-chart" class="spend-chart"></div>
          <el-empty v-if="!summary?.trend.length" description="当前范围暂无报表数据" :image-size="70" />
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="chart-card">
          <template #header>
            <div class="card-header"><span>最近任务</span><el-button link type="primary" @click="goToTasks">查看全部</el-button></div>
          </template>
          <el-table :data="summary?.recent_tasks || []" size="small" height="300">
            <el-table-column prop="action_type" label="动作" width="100" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }"><el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="结果" min-width="100">
              <template #default="{ row }">{{ row.success_count }}/{{ row.total_accounts }} 成功</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="150" show-overflow-tooltip />
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
            <div v-for="alert in summary.alerts" :key="alert.id" class="alert-item">
              <el-tag type="warning" size="small">{{ alert.alert_type }}</el-tag>
              <div class="alert-content"><strong>{{ alert.title }}</strong><span>{{ alert.message }}</span></div>
            </div>
          </div>
          <el-empty v-else description="暂无未处理告警" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="quick-card">
      <template #header><div class="card-header"><span>快速操作</span><small>{{ scopeText }}</small></div></template>
      <div class="quick-actions">
        <el-button v-if="canPublish" type="primary" @click="goToBatchPublish"><el-icon><Promotion /></el-icon>批量投放广告</el-button>
        <el-button v-if="canPublish" type="success" @click="goToScheduledTasks"><el-icon><Timer /></el-icon>创建定时任务</el-button>
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
import { useAccountStore } from '@/stores/accountStore'
import { useUserStore } from '@/stores/userStore'
import { workbenchApi, type WorkbenchSummary } from '@/api/reports'

const router = useRouter()
const accountStore = useAccountStore()
const userStore = useUserStore()
const loading = ref(false)
const summary = ref<WorkbenchSummary | null>(null)
const dateRange = ref<[string, string] | null>(null)
let chart: echarts.ECharts | null = null

const primaryTotal = computed(() => summary.value?.currency_totals?.[0] || null)
const chartCurrency = computed(() => primaryTotal.value?.currency || '')
const rangeText = computed(() => summary.value ? `${summary.value.range.start_date} 至 ${summary.value.range.end_date}` : '当前范围')
const freshnessText = computed(() => {
  if (!summary.value) return ''
  if (summary.value.freshness.status === 'NEVER') return '当前范围尚未同步报表数据'
  return `报表数据已延迟 ${summary.value.freshness.age_hours ?? 0} 小时`
})
const scopeText = computed(() => {
  const count = summary.value?.scope.account_count ?? 0
  return `当前用户可见账户 ${count} 个${accountStore.selectedAccount ? ` · ${accountStore.selectedAccount.account_name}` : ''}`
})
const canPublish = computed(() => userStore.isAdmin || userStore.hasPermission('job:create'))
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
  const dom = document.getElementById('spend-chart')
  if (!dom) return
  if (chart) chart.dispose()
  chart = echarts.init(dom)
  const rows = (summary.value?.trend || []).filter(row => row.currency === chartCurrency.value)
  chart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 45, right: 20, top: 20, bottom: 35 },
    xAxis: { type: 'category', data: rows.map(row => row.date) },
    yAxis: { type: 'value' },
    series: [{ data: rows.map(row => row.spend), type: 'line', smooth: true, itemStyle: { color: '#667eea' }, areaStyle: { color: 'rgba(102, 126, 234, 0.1)' } }],
  })
}

const loadSummary = async () => {
  loading.value = true
  try {
    const { data } = await workbenchApi.summary(dateParams())
    summary.value = data
    await nextTick()
    renderChart()
  } catch {
    summary.value = null
    ElMessage.error('工作台数据加载失败，请检查账号权限和同步状态')
  } finally {
    loading.value = false
  }
}

const getStatusType = (status: string) => ({
  RUNNING: 'success', QUEUED: 'warning', PENDING: 'info', SUCCESS: 'success', PARTIAL_SUCCESS: 'warning', FAILED: 'danger', CANCELLED: 'info',
}[status] || 'info')

const goToBatchPublish = () => router.push('/dashboard/batch-publish')
const goToScheduledTasks = () => router.push('/dashboard/scheduled-tasks')
const goToRiskControl = () => router.push('/dashboard/risk-control')
const goToReports = () => router.push('/dashboard/reports')
const goToCampaigns = () => router.push('/dashboard/campaigns')
const goToTasks = () => router.push('/dashboard/jobs')

watch(() => accountStore.selectedAccountId, loadSummary)
onMounted(loadSummary)
onBeforeUnmount(() => chart?.dispose())
</script>

<style scoped lang="scss">
.overview-page { min-height: 100%; }
.page-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 16px; h2 { margin: 0 0 6px; font-size: 22px; } p { margin: 0; color: #909399; font-size: 13px; } }
.toolbar-actions { display: flex; gap: 10px; align-items: center; }
.scope-alert { margin-bottom: 16px; }
.stat-cards { margin-bottom: 16px; }
.stat-card { background: #fff; border-radius: 8px; padding: 18px; box-shadow: 0 1px 4px rgba(0, 0, 0, .06); .stat-header { display: flex; justify-content: space-between; color: #909399; font-size: 14px; } .stat-header .el-icon { color: #667eea; font-size: 22px; } .stat-value { margin: 15px 0 8px; color: #303133; font-size: 27px; font-weight: 600; } .stat-value.muted { color: #c0c4cc; } .stat-footer { color: #909399; font-size: 12px; } &.risk-alert { border-left: 4px solid #e6a23c; } }
.content-row { margin-bottom: 16px; }
.chart-card { min-height: 360px; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-weight: 600; }
.spend-chart { width: 100%; height: 300px; }
.health-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.health-item { padding: 14px; background: #f7f9fc; border-radius: 8px; display: flex; flex-direction: column; gap: 8px; color: #909399; font-size: 13px; strong { color: #303133; font-size: 24px; } }
.inline-alert { margin-top: 16px; }
.alert-list { display: flex; flex-direction: column; gap: 12px; min-height: 260px; }
.alert-item { display: flex; gap: 10px; align-items: flex-start; padding-bottom: 10px; border-bottom: 1px solid #ebeef5; .alert-content { display: flex; flex-direction: column; gap: 4px; min-width: 0; strong { color: #303133; } span { color: #909399; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } } }
.quick-card { margin-bottom: 16px; }
.card-header small { color: #909399; font-weight: 400; }
.quick-actions { display: flex; gap: 12px; flex-wrap: wrap; }
@media (max-width: 800px) { .page-toolbar { align-items: flex-start; flex-direction: column; } .toolbar-actions { width: 100%; .el-date-editor { flex: 1; } } .health-grid { grid-template-columns: repeat(2, 1fr); } }
</style>

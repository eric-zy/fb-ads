<template>
  <div class="overview-page">
    <el-row :gutter="20" class="stat-cards">
      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">今日花费</span>
            <el-icon class="stat-icon"><Money /></el-icon>
          </div>
          <div class="stat-value">${{ todaySpend.toFixed(2) }}</div>
          <div class="stat-footer">{{ spendTrend }}% vs 昨天</div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">活跃系列</span>
            <el-icon class="stat-icon"><Promotion /></el-icon>
          </div>
          <div class="stat-value">{{ activeCampaigns }}</div>
          <div class="stat-footer">共 {{ totalCampaigns }} 个系列</div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">平均CTR</span>
            <el-icon class="stat-icon"><TrendCharts /></el-icon>
          </div>
          <div class="stat-value">{{ avgCtr.toFixed(2) }}%</div>
          <div class="stat-footer">数据同步中...</div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="stat-card" :class="{ 'risk-alert': riskScore > 0.5 }">
          <div class="stat-header">
            <span class="stat-label">风险评分</span>
            <el-icon class="stat-icon"><Warning /></el-icon>
          </div>
          <div class="stat-value">{{ (riskScore * 100).toFixed(0) }}</div>
          <div class="stat-footer" :style="{ color: riskScore > 0.5 ? '#f56c6c' : '#67c23a' }">
            {{ riskStatus }}
          </div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <!-- 花费趋势图 -->
      <el-col :xs="24" :md="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>花费趋势</span>
              <el-button type="text" @click="refreshChart">刷新</el-button>
            </div>
          </template>
          <div id="spend-chart" style="height: 300px"></div>
        </el-card>
      </el-col>

      <!-- 最近任务 -->
      <el-col :xs="24" :md="12">
        <el-card class="chart-card">
          <template #header>
            <div class="card-header">
              <span>最近任务</span>
              <el-button type="text" @click="goToTasks">查看全部</el-button>
            </div>
          </template>
          <el-table :data="recentTasks" style="width: 100%">
            <el-table-column prop="task_type" label="任务类型" width="80" />
            <el-table-column prop="status" label="状态">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="120" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快速操作 -->
    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="24">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>快速操作</span>
            </div>
          </template>
          <div class="quick-actions">
            <el-button type="primary" size="large" @click="goToBatchPublish">
              <el-icon><Rocket /></el-icon>
              批量投放广告
            </el-button>
            <el-button type="success" size="large" @click="goToScheduledTasks">
              <el-icon><Timer /></el-icon>
              创建定时任务
            </el-button>
            <el-button type="warning" size="large" @click="goToRiskControl">
              <el-icon><Warning /></el-icon>
              查看风险状态
            </el-button>
            <el-button type="info" size="large" @click="goToReports">
              <el-icon><PieChart /></el-icon>
              查看报表
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAccountStore } from '@/stores/accountStore'
import * as echarts from 'echarts'

const router = useRouter()
const accountStore = useAccountStore()

const todaySpend = ref(0)
const spendTrend = ref(5)
const activeCampaigns = ref(0)
const totalCampaigns = ref(0)
const avgCtr = ref(1.23)
const riskScore = ref(0.35)
const recentTasks = ref([])

const riskStatus = computed(() => {
  if (riskScore.value > 0.7) return '严重'
  if (riskScore.value > 0.5) return '高风险'
  if (riskScore.value > 0.3) return '中等'
  return '安全'
})

const initChart = () => {
  const chartDom = document.getElementById('spend-chart')
  if (!chartDom) return

  const myChart = echarts.init(chartDom)
  const option = {
    tooltip: {
      trigger: 'axis',
    },
    xAxis: {
      type: 'category',
      data: ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
    },
    yAxis: {
      type: 'value',
    },
    series: [
      {
        data: [120, 200, 150, 80, 70, 110, 130],
        type: 'line',
        smooth: true,
        itemStyle: {
          color: '#667eea',
        },
        areaStyle: {
          color: 'rgba(102, 126, 234, 0.1)',
        },
      },
    ],
  }
  myChart.setOption(option)
}

const refreshChart = () => {
  initChart()
  ElMessage.success('图表已刷新')
}

const getStatusType = (status: string) => {
  const typeMap: Record<string, string> = {
    running: 'success',
    pending: 'info',
    completed: 'success',
    failed: 'danger',
  }
  return typeMap[status] || 'info'
}

const goToBatchPublish = () => router.push('/dashboard/batch-publish')
const goToScheduledTasks = () => router.push('/dashboard/scheduled-tasks')
const goToRiskControl = () => router.push('/dashboard/risk-control')
const goToReports = () => router.push('/dashboard/reports')
const goToTasks = () => router.push('/dashboard/scheduled-tasks')

onMounted(() => {
  // 加载数据
  if (accountStore.selectedAccount) {
    // 这里会调用实际的API获取数据
  }
  initChart()
})
</script>

<style scoped lang="scss">
.overview-page {
  .stat-cards {
    margin-bottom: 20px;

    .stat-card {
      background: white;
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
      transition: all 0.3s ease;

      &:hover {
        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
        transform: translateY(-2px);
      }

      &.risk-alert {
        border-left: 4px solid #f56c6c;
      }

      .stat-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 15px;

        .stat-label {
          color: #909399;
          font-size: 14px;
        }

        .stat-icon {
          font-size: 24px;
          color: #667eea;
        }
      }

      .stat-value {
        font-size: 28px;
        font-weight: 600;
        color: #333;
        margin-bottom: 10px;
      }

      .stat-footer {
        font-size: 12px;
        color: #909399;
      }
    }
  }

  .chart-card {
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }

  .quick-actions {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;

    .el-button {
      flex: 1;
      min-width: 150px;
    }
  }
}
</style>

<template>
  <div class="risk-control-page">
    <!-- 账户风险状态 -->
    <el-row :gutter="20" class="status-cards">
      <el-col :xs="24" :sm="12" :md="6">
        <div class="status-card" :class="{ alert: accountHealth?.is_healthy === false }">
          <h3>账户状态</h3>
          <p class="status-value">{{ accountHealth?.health_report?.status || 'loading' }}</p>
          <p class="status-desc">
            {{ accountHealth?.is_healthy ? '正常' : '异常' }}
          </p>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="status-card">
          <h3>风险评分</h3>
          <div class="score-ring">
            <el-progress
              type="circle"
              :percentage="Math.round(riskScore * 100)"
              :color="getRiskColor"
            />
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="status-card">
          <h3>发布频次</h3>
          <p class="status-value">{{ frequencyStatus }}</p>
          <p class="status-desc">{{ frequencyDays }}天内</p>
        </div>
      </el-col>

      <el-col :xs="24" :sm="12" :md="6">
        <div class="status-card">
          <h3>API限制</h3>
          <p class="status-value">{{ rateLimitUsage }}%</p>
          <p class="status-desc">当前小时</p>
        </div>
      </el-col>
    </el-row>

    <!-- 风险事件列表 -->
    <el-card style="margin-top: 20px">
      <template #header>
        <div class="card-header">
          <span>风险事件</span>
          <el-button type="text" @click="loadRiskEvents">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-table
        :data="riskEvents"
        :loading="eventsLoading"
        style="width: 100%"
      >
        <el-table-column prop="event_type" label="事件类型" width="150" />
        <el-table-column prop="risk_level" label="风险等级" width="100">
          <template #default="{ row }">
            <el-tag :type="getRiskLevelType(row.risk_level)">
              {{ row.risk_level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" />
        <el-table-column prop="description" label="描述" width="200" />
        <el-table-column prop="is_resolved" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_resolved ? 'success' : 'info'">
              {{ row.is_resolved ? '已解决' : '未解决' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="150" />
      </el-table>
    </el-card>

    <!-- 建议措施 -->
    <el-card style="margin-top: 20px">
      <template #header>
        <div class="card-header">
          <span>系统建议</span>
        </div>
      </template>

      <div v-if="recommendations?.actions?.length > 0" class="recommendations">
        <div
          v-for="action in recommendations.actions"
          :key="action.type"
          class="recommendation-item"
          :class="{ [action.priority]: true }"
        >
          <div class="item-header">
            <span class="priority">{{ getPriorityLabel(action.priority) }}</span>
            <span class="type">{{ action.type }}</span>
          </div>
          <p class="message">{{ action.message }}</p>
          <p class="reason">原因: {{ action.reason }}</p>
        </div>
      </div>
      <el-empty v-else description="暂无建议" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAccountStore } from '@/stores/accountStore'
import request from '@/utils/request'

const accountStore = useAccountStore()

const accountHealth = ref<any>(null)
const riskScore = ref(0)
const frequencyStatus = ref('安全')
const frequencyDays = ref(24)
const rateLimitUsage = ref(0)
const riskEvents = ref<any[]>([])
const recommendations = ref<any>(null)
const eventsLoading = ref(false)

const getRiskColor = computed(() => {
  const percentage = riskScore.value * 100
  if (percentage > 70) return '#f56c6c'
  if (percentage > 50) return '#e6a23c'
  if (percentage > 30) return '#409eff'
  return '#67c23a'
})

const getRiskLevelType = (level: string) => {
  const typeMap: Record<string, string> = {
    critical: 'danger',
    high: 'warning',
    medium: 'warning',
    low: 'success',
  }
  return typeMap[level] || 'info'
}

const getPriorityLabel = (priority: string) => {
  const labels: Record<string, string> = {
    critical: '紧急',
    high: '高',
    medium: '中',
    low: '低',
  }
  return labels[priority] || priority
}

const loadAccountHealth = async () => {
  if (!accountStore.selectedAccount) return
  try {
    const response = await request.get(
      `/api/v1/accounts/${accountStore.selectedAccount.account_id}/account-health-check`
    )
    accountHealth.value = response.data
  } catch (error) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const loadRiskScore = async () => {
  if (!accountStore.selectedAccount) return
  try {
    const response = await request.get(
      `/api/v1/accounts/${accountStore.selectedAccount.account_id}/fraud-score`
    )
    riskScore.value = response.data.fraud_score
  } catch (error) {
    console.error('Error loading risk score:', error)
  }
}

const loadRiskEvents = async () => {
  if (!accountStore.selectedAccount) return
  eventsLoading.value = true
  try {
    const response = await request.get(
      `/api/v1/accounts/${accountStore.selectedAccount.account_id}/risk-events`
    )
    riskEvents.value = response.data.events || []
  } catch (error) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    eventsLoading.value = false
  }
}

const loadRecommendations = async () => {
  if (!accountStore.selectedAccount) return
  try {
    const response = await request.get(
      `/api/v1/accounts/${accountStore.selectedAccount.account_id}/safety-recommendations`
    )
    recommendations.value = response.data.recommendations
  } catch (error) {
    console.error('Error loading recommendations:', error)
  }
}

const loadFrequencyStatus = async () => {
  if (!accountStore.selectedAccount) return
  try {
    const response = await request.get(
      `/api/v1/accounts/${accountStore.selectedAccount.account_id}/publish-frequency-check?hours=24`
    )
    const report = response.data.frequency_report
    frequencyStatus.value = report.frequency_status
  } catch (error) {
    console.error('Error loading frequency status:', error)
  }
}

const loadRateLimitStatus = async () => {
  if (!accountStore.selectedAccount) return
  try {
    const response = await request.get(
      `/api/v1/accounts/${accountStore.selectedAccount.account_id}/rate-limit-status`
    )
    const hourStatus = response.data.rate_limits.hour
    rateLimitUsage.value = Math.round(hourStatus.usage_ratio * 100)
  } catch (error) {
    console.error('Error loading rate limit:', error)
  }
}

const loadAllData = async () => {
  await Promise.all([
    loadAccountHealth(),
    loadRiskScore(),
    loadRiskEvents(),
    loadRecommendations(),
    loadFrequencyStatus(),
    loadRateLimitStatus(),
  ])
}

onMounted(() => {
  loadAllData()
  // 每30秒刷新一次
  const timer = setInterval(loadAllData, 30000)
  return () => clearInterval(timer)
})
</script>

<style scoped lang="scss">
.risk-control-page {
  .status-cards {
    .status-card {
      background: white;
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
      transition: all 0.3s ease;

      &.alert {
        border-left: 4px solid #f56c6c;
      }

      h3 {
        margin: 0 0 15px 0;
        font-size: 14px;
        color: #909399;
      }

      .status-value {
        margin: 0 0 8px 0;
        font-size: 24px;
        font-weight: 600;
        color: #333;
      }

      .status-desc {
        margin: 0;
        font-size: 12px;
        color: #909399;
      }

      .score-ring {
        display: flex;
        justify-content: center;
        margin: 10px 0;
      }
    }
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .recommendations {
    display: flex;
    flex-direction: column;
    gap: 15px;

    .recommendation-item {
      padding: 15px;
      border-left: 4px solid #409eff;
      border-radius: 4px;
      background-color: #f5f7fa;

      &.critical {
        border-left-color: #f56c6c;
        background-color: #fef0f0;
      }

      &.high {
        border-left-color: #e6a23c;
        background-color: #fdf6ec;
      }

      .item-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;

        .priority {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 12px;
          font-weight: 600;
          background-color: rgba(59, 130, 246, 0.1);
          color: #3b82f6;
        }

        .type {
          font-size: 14px;
          font-weight: 600;
          color: #333;
        }
      }

      .message {
        margin: 8px 0;
        font-size: 14px;
        color: #333;
      }

      .reason {
        margin: 0;
        font-size: 12px;
        color: #909399;
      }
    }
  }
}
</style>

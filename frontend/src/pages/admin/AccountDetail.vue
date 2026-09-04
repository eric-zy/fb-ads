<!--
  广告账户详情（Meta 账号管理 V1 —— 设计文档 §18）

  展示：账户名称 / Account ID / 所属 BM / Meta Status / Effective Status /
        Currency / Timezone / Spend Cap / Amount Spent / Balance / 最后同步 / 系统状态

  系统设置：参与批量投放开关（ON/OFF）
    —— 只改 system_status，不影响 Meta 侧状态，也不会被同步覆盖（文档 §24）。
-->
<template>
  <div class="account-detail">
    <div class="detail-header">
      <div class="header-main">
        <el-button :icon="ArrowLeft" circle size="small" @click="goBack" />
        <div class="title-block">
          <h3>{{ detail?.account_name || detail?.account_id || '账户详情' }}</h3>
          <div class="sub-meta">
            <span class="mono">{{ detail?.account_id || '-' }}</span>
            <el-divider direction="vertical" />
            <span>所属 BM：{{ detail?.business_name || '-' }}</span>
          </div>
        </div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="syncing" @click="handleSync">
          同步
        </el-button>
        <el-button
          :type="isDeployEnabled ? 'warning' : 'success'"
          :loading="toggling"
          :disabled="!detail"
          @click="onDeploySwitch(!isDeployEnabled)"
        >
          {{ isDeployEnabled ? '禁止参与投放' : '允许参与投放' }}
        </el-button>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="6" animated />

    <template v-else-if="detail">
      <!-- 概览 -->
      <el-row :gutter="12" class="section">
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">账户余额</div>
            <div class="stat-value">
              {{ formatMoney(detail.balance, detail.currency) }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">累计消费</div>
            <div class="stat-value">
              {{ formatMoney(detail.amount_spent, detail.currency) }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">花费上限</div>
            <div class="stat-value">
              {{ detail.spend_cap ? formatMoney(detail.spend_cap, detail.currency) : '不限' }}
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card shadow="never" class="stat-card">
            <div class="stat-label">风控评分</div>
            <div class="stat-value">{{ detail.risk_score ?? 0 }}</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 基本信息 -->
      <el-card shadow="never" class="section">
        <template #header><span class="card-title">基本信息</span></template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="账户名称">
            {{ detail.account_name || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="Account ID">
            <span class="mono">{{ detail.account_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="所属 BM">
            <el-link
              v-if="detail.business_id"
              type="primary"
              @click="goBusiness(detail.business_id)"
            >
              {{ detail.business_name || detail.business_id }}
            </el-link>
            <span v-else>-</span>
          </el-descriptions-item>
          <el-descriptions-item label="货币">
            {{ detail.currency || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="时区">
            {{ detail.timezone || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatTime(detail.created_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 状态（文档 §7：Meta 状态与系统状态分离） -->
      <el-card shadow="never" class="section">
        <template #header>
          <span class="card-title">状态</span>
          <span class="card-subtitle">Meta 状态由同步覆盖，系统状态不会被同步覆盖</span>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Meta Status">
            <el-tag :type="metaStatusType(detail.account_status)" size="small">
              {{ metaStatusLabel(detail.account_status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Effective Status">
            <el-tag :type="metaStatusType(detail.effective_status)" size="small">
              {{ metaStatusLabel(detail.effective_status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="系统状态">
            <el-tag :type="isDeployEnabled ? 'success' : 'danger'" size="small">
              {{ isDeployEnabled ? '允许投放' : '已禁用' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Meta 禁用原因">
            {{ detail.disable_reason || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="系统禁用原因">
            {{ detail.system_status_reason || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="状态变更时间">
            {{ formatTime(detail.system_status_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="最后同步">
            {{ formatTime(detail.last_synced_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="同步错误">
            <span :class="{ 'text-danger': detail.last_sync_error }">
              {{ detail.last_sync_error || '无' }}
            </span>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 金额（文档 §9：最小货币单位存储，展示层换算） -->
      <el-card shadow="never" class="section">
        <template #header><span class="card-title">金额</span></template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Spend Cap">
            {{ formatMoney(detail.spend_cap, detail.currency) }}
          </el-descriptions-item>
          <el-descriptions-item label="Amount Spent">
            {{ formatMoney(detail.amount_spent, detail.currency) }}
          </el-descriptions-item>
          <el-descriptions-item label="Balance">
            {{ formatMoney(detail.balance, detail.currency) }}
          </el-descriptions-item>
          <el-descriptions-item label="日消费限额">
            {{ formatMoney(detail.daily_spend_limit, detail.currency) }}
          </el-descriptions-item>
          <el-descriptions-item label="月消费限额">
            {{ formatMoney(detail.monthly_spend_limit, detail.currency) }}
          </el-descriptions-item>
          <el-descriptions-item label="最近风控检查">
            {{ formatTime(detail.last_risk_check) }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 系统设置 -->
      <el-card shadow="never" class="section">
        <template #header><span class="card-title">系统设置</span></template>
        <div class="setting-row">
          <div class="setting-text">
            <div class="setting-title">参与批量投放</div>
            <div class="setting-hint">
              关闭后该账户不会出现「可投放账户池」，但不影响 Meta 侧状态，
              也不会被 Meta 同步重新打开。
            </div>
          </div>
          <el-switch
            v-model="deployEnabled"
            :loading="toggling"
            active-text="开启"
            inactive-text="关闭"
            @change="onDeploySwitch"
          />
        </div>
      </el-card>
    </template>

    <el-empty v-else description="账户不存在或无权访问" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { formatMoney } from '@/utils/money'

const route = useRoute()
const router = useRouter()
const accountId = computed(() => String(route.params.id || ''))

const loading = ref(false)
const syncing = ref(false)
const toggling = ref(false)
const detail = ref<AdAccountItem | null>(null)
const deployEnabled = ref(false)

const isDeployEnabled = computed(() => detail.value?.system_status === 'ACTIVE')

function formatTime(v: string | null) {
  if (!v) return '-'
  return v.replace('T', ' ').slice(0, 19)
}

function metaStatusLabel(v: string | null) {
  if (!v) return '-'
  return (
    {
      '1': '正常', '2': '已禁用', '3': '未结算', '7': '风险审核中',
      '8': '待结算', '9': '宽限期', '100': '待关闭', '101': '已关闭',
      ACTIVE: '正常', DISABLED: '已禁用', UNSETTLED: '未结算',
    }[v] || v
  )
}

function metaStatusType(v: string | null): 'success' | 'danger' | 'warning' | 'info' {
  if (!v) return 'info'
  if (v === '1' || v === 'ACTIVE') return 'success'
  if (v === '2' || v === 'DISABLED' || v === '101') return 'danger'
  if (v === '3' || v === '7' || v === '8' || v === '100') return 'warning'
  return 'info'
}

function errorOf(e: any): string {
  return e?.response?.data?.detail || e?.message || '操作失败'
}

async function load() {
  if (!accountId.value) return
  loading.value = true
  try {
    const { data } = await accountApi.detail(accountId.value)
    detail.value = data
    deployEnabled.value = data.system_status === 'ACTIVE'
  } catch (e: any) {
    ElMessage.error(errorOf(e))
    detail.value = null
  } finally {
    loading.value = false
  }
}

async function handleSync() {
  syncing.value = true
  try {
    const { data } = await accountApi.sync(accountId.value)
    ElMessage.success(`同步任务已提交（job_id: ${data.job_id}）`)
    // 异步执行，稍后刷新一次看是否有新数据
    setTimeout(load, 2000)
  } catch (e: any) {
    ElMessage.error(errorOf(e))
  } finally {
    syncing.value = false
  }
}

/** 切换「参与批量投放」：只改 system_status，不动 Meta 状态 */
async function onDeploySwitch(val: boolean) {
  if (!detail.value) return
  toggling.value = true
  try {
    if (val) {
      await accountApi.unfreeze(accountId.value)
    } else {
      await accountApi.freeze(accountId.value, '管理员在账户详情页禁用')
    }
    ElMessage.success(val ? '已允许参与批量投放' : '已禁止参与批量投放')
    await load()
  } catch (e: any) {
    ElMessage.error(errorOf(e))
    deployEnabled.value = !val // 回滚开关，避免界面与后端不一致
  } finally {
    toggling.value = false
  }
}

function goBack() {
  router.push({ name: 'AdminAccounts' })
}

function goBusiness(id: string) {
  router.push({ name: 'AdminBusinessDetail', params: { id } })
}

onMounted(load)
</script>

<style scoped>
.account-detail {
  padding: 4px;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.header-main {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-block h3 {
  margin: 0 0 4px;
  font-size: 18px;
}
.sub-meta {
  display: flex;
  align-items: center;
  font-size: 13px;
  color: #909399;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.section {
  margin-bottom: 12px;
}
.stat-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.stat-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 20px;
  font-weight: 600;
}
.card-title {
  font-weight: 600;
}
.card-subtitle {
  margin-left: 8px;
  font-size: 12px;
  color: #909399;
  font-weight: 400;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.text-danger {
  color: #f56c6c;
}
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}
.setting-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.setting-hint {
  font-size: 12px;
  color: #909399;
  max-width: 640px;
}
</style>

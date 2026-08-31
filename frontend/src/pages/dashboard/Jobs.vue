<template>
  <div class="jobs-page">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">任务中心（Job Center）</h2>
            <p class="page-desc">
              批量投放、批量启停、批量改预算都会生成异步任务。
              每个账户是独立子项：部分成功会标记 PARTIAL_SUCCESS，失败项可单独重跑。
            </p>
          </div>
          <div class="actions">
            <el-select
              v-model="statusFilter"
              placeholder="状态筛选"
              clearable
              style="width: 180px"
              @change="loadJobs"
            >
              <el-option label="PENDING" value="PENDING" />
              <el-option label="RUNNING" value="RUNNING" />
              <el-option label="SUCCESS" value="SUCCESS" />
              <el-option label="PARTIAL_SUCCESS" value="PARTIAL_SUCCESS" />
              <el-option label="FAILED" value="FAILED" />
              <el-option label="CANCELLED" value="CANCELLED" />
            </el-select>
            <el-checkbox v-model="autoRefresh" style="margin-left: 12px">自动刷新(5s)</el-checkbox>
            <el-button :icon="Refresh" @click="loadJobs">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="jobs" v-loading="loading" size="small">
        <el-table-column prop="id" label="Job ID" width="240" show-overflow-tooltip />
        <el-table-column label="动作" width="130">
          <template #default="{ row }">
            <el-tag size="small">{{ actionLabel(row.action_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="160">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="200">
          <template #default="{ row }">
            <el-progress
              :percentage="percent(row)"
              :stroke-width="14"
              :status="progressStatus(row.status)"
            />
          </template>
        </el-table-column>
        <el-table-column label="总/成功/失败" width="130">
          <template #default="{ row }">
            {{ row.total_accounts }} /
            <span style="color:#67c23a">{{ row.success_count }}</span> /
            <span style="color:#f56c6c">{{ row.failed_count }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewDetail(row.id)">详情</el-button>
            <el-button
              link
              type="warning"
              :disabled="!row.failed_count || isFinal(row.status) === false"
              @click="handleRetry(row)"
            >
              重跑失败
            </el-button>
            <el-button link type="danger" :disabled="isFinal(row.status)" @click="handleCancel(row)">
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 任务详情 -->
    <el-dialog v-model="detailVisible" title="任务详情" width="900px">
      <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
        <el-descriptions-item label="Job ID">{{ currentJob?.id }}</el-descriptions-item>
        <el-descriptions-item label="动作">{{ currentJob?.action_type }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusTagType(currentJob?.status || '')" size="small">
            {{ currentJob?.status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="总数">{{ currentJob?.total_accounts }}</el-descriptions-item>
        <el-descriptions-item label="成功">{{ currentJob?.success_count }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ currentJob?.failed_count }}</el-descriptions-item>
        <el-descriptions-item label="创建">{{ currentJob?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="开始">{{ currentJob?.started_at || '-' }}</el-descriptions-item>
        <el-descriptions-item label="结束">{{ currentJob?.finished_at || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="currentJob?.error_message"
        :title="currentJob.error_message"
        type="error"
        :closable="false"
        style="margin-bottom: 12px"
      />

      <el-table :data="currentJob?.items || []" size="small" max-height="380">
        <el-table-column prop="ad_account_id" label="广告账户" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="itemTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="meta_campaign_id" label="Meta Campaign" width="170" show-overflow-tooltip />
        <el-table-column label="AdSet / Ad" width="120">
          <template #default="{ row }">
            {{ (row.adset_ids?.length || 0) }} / {{ (row.ad_ids?.length || 0) }}
          </template>
        </el-table-column>
        <el-table-column prop="retry_count" label="重试" width="70" />
        <el-table-column label="错误" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error_category" class="err-cat">[{{ row.error_category }}]</span>
            {{ row.error_message }}
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          type="warning"
          :disabled="!currentJob?.failed_count"
          @click="currentJob && handleRetry(currentJob)"
        >
          重跑失败项（{{ currentJob?.failed_count || 0 }}）
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  jobsApi,
  isFinalStatus,
  type CampaignJob,
} from '@/api/jobs'

const jobs = ref<CampaignJob[]>([])
const currentJob = ref<CampaignJob | null>(null)
const loading = ref(false)
const detailVisible = ref(false)
const statusFilter = ref('')
const autoRefresh = ref(true)

let timer: number | null = null

const isFinal = (status: string) => isFinalStatus(status)

const actionLabel = (action: string) =>
  ({
    CREATE: '批量创建',
    PAUSE: '批量暂停',
    ENABLE: '批量启用',
    UPDATE_BUDGET: '批量改预算',
    SYNC: '数据同步',
  }[action] || action)

const statusTagType = (status: string) =>
  ({
    PENDING: 'info',
    VALIDATING: 'info',
    QUEUED: 'info',
    RUNNING: 'primary',
    SUCCESS: 'success',
    PARTIAL_SUCCESS: 'warning',
    FAILED: 'danger',
    CANCELLED: 'info',
  }[status] || 'info')

const itemTagType = (status: string) =>
  ({ SUCCESS: 'success', FAILED: 'danger', RUNNING: 'primary', PENDING: 'info' }[status] || 'info')

const percent = (row: CampaignJob) => {
  if (!row.total_accounts) return 0
  return Math.round(((row.success_count + row.failed_count) / row.total_accounts) * 100)
}

const progressStatus = (status: string) => {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED' || status === 'CANCELLED') return 'exception'
  return undefined
}

const loadJobs = async () => {
  loading.value = true
  try {
    const { data } = await jobsApi.list({ status: statusFilter.value || undefined, limit: 100 })
    jobs.value = data
  } finally {
    loading.value = false
  }
}

const viewDetail = async (id: string) => {
  const { data } = await jobsApi.get(id)
  currentJob.value = data
  detailVisible.value = true
}

const handleRetry = async (row: CampaignJob) => {
  try {
    await ElMessageBox.confirm(
      `将重新执行该任务中失败的 ${row.failed_count} 个账户，已成功的账户不受影响。`,
      '重跑确认',
      { type: 'warning' }
    )
  } catch {
    return
  }

  try {
    await jobsApi.retry(row.id)
    ElMessage.success('已重新分派失败账户')
    await loadJobs()
    if (currentJob.value?.id === row.id) {
      const { data } = await jobsApi.get(row.id)
      currentJob.value = data
    }
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const handleCancel = async (row: CampaignJob) => {
  try {
    await ElMessageBox.confirm('确定取消该任务？未完成的账户将被标记为已跳过。', '取消确认', {
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    await jobsApi.cancel(row.id)
    ElMessage.success('任务已取消')
    await loadJobs()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

// 仅在存在进行中任务时才有必要轮询
const startTimer = () => {
  stopTimer()
  timer = window.setInterval(async () => {
    if (!autoRefresh.value) return
    await loadJobs()
    if (detailVisible.value && currentJob.value) {
      const { data } = await jobsApi.get(currentJob.value.id)
      currentJob.value = data
    }
  }, 5000)
}

const stopTimer = () => {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  loadJobs()
  startTimer()
})

onUnmounted(stopTimer)
</script>

<style scoped lang="scss">
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;

  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; max-width: 620px; }
}
.actions { display: flex; align-items: center; }
.err-cat { color: #e6a23c; margin-right: 4px; }
</style>

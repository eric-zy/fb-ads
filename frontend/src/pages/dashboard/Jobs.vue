<template>
  <div class="jobs-page">
    <el-card class="jobs-shell" shadow="never">
      <template #header>
        <div class="header-bar">
          <div class="title-block">
            <span class="eyebrow">DELIVERY OPERATIONS</span>
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
              class="status-select"
              @change="loadJobs"
            >
              <el-option label="全部状态" value="" />
              <el-option label="等待中" value="PENDING" />
              <el-option label="执行中" value="RUNNING" />
              <el-option label="已成功" value="SUCCESS" />
              <el-option label="部分成功" value="PARTIAL_SUCCESS" />
              <el-option label="失败" value="FAILED" />
              <el-option label="已取消" value="CANCELLED" />
            </el-select>
            <el-checkbox v-model="autoRefresh" class="auto-refresh">自动刷新 <span>5s</span></el-checkbox>
            <el-button class="refresh-button" :icon="Refresh" @click="loadJobs">刷新</el-button>
          </div>
        </div>
      </template>

      <div class="job-summary">
        <div class="summary-card total"><span class="summary-icon">◷</span><div><span class="summary-label">当前任务</span><strong>{{ summary.total }}</strong></div></div>
        <div class="summary-card running"><span class="summary-icon">↻</span><div><span class="summary-label">执行中</span><strong>{{ summary.running }}</strong></div></div>
        <div class="summary-card success"><span class="summary-icon">✓</span><div><span class="summary-label">已完成</span><strong>{{ summary.success }}</strong></div></div>
        <div class="summary-card failed"><span class="summary-icon">!</span><div><span class="summary-label">需关注</span><strong>{{ summary.failed }}</strong></div></div>
      </div>

      <el-table class="job-table" :data="jobs" v-loading="loading" size="small" row-key="id">
        <el-table-column label="任务 ID" width="180" show-overflow-tooltip>
          <template #default="{ row }"><span class="job-id">{{ shortId(row.id) }}</span></template>
        </el-table-column>
        <el-table-column label="任务动作" width="130">
          <template #default="{ row }">
            <el-tag class="action-tag" size="small" effect="plain">{{ actionLabel(row.action_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="125">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small" effect="light">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="执行进度" min-width="190">
          <template #default="{ row }">
            <div class="progress-cell">
              <div class="progress-line"><el-progress :percentage="percent(row)" :stroke-width="8" :show-text="false" :status="progressStatus(row.status)" /><span>{{ percent(row) }}%</span></div>
              <small>{{ row.success_count + row.failed_count }} / {{ row.total_accounts }} 个账户已处理</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="账户结果" width="145">
          <template #default="{ row }">
            <div class="result-counts"><span class="result-total">{{ row.total_accounts }} 总数</span><span class="result-success">{{ row.success_count }} 成功</span><span class="result-failed">{{ row.failed_count }} 失败</span></div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="165" show-overflow-tooltip><template #default="{ row }"><span class="created-time">{{ formatDateTime(row.created_at) }}</span></template></el-table-column>
        <el-table-column label="发布人" width="115" show-overflow-tooltip><template #default="{ row }">{{ row.publisher?.username || row.publisher?.email || row.created_by || '-' }}</template></el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <div class="operation-actions">
              <el-button class="detail-button" size="small" type="primary" plain @click="viewDetail(row.id)">查看详情</el-button>
              <el-dropdown v-if="hasMoreActions(row)" trigger="click" @command="(command: string) => handleAction(command, row)">
                <el-button class="more-button" size="small" plain>更多<el-icon><ArrowDown /></el-icon></el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="canEditRepublish && row.action_type === 'CREATE' && ['FAILED', 'PARTIAL_SUCCESS'].includes(row.status)" command="edit">编辑后重投</el-dropdown-item>
                    <el-dropdown-item v-if="canRetry" command="retry" :disabled="!row.failed_count || !isFinal(row.status)">重跑失败项</el-dropdown-item>
                    <el-dropdown-item v-if="canCancel" command="cancel" :disabled="isFinal(row.status)" divided>取消任务</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无任务记录" /></template>
      </el-table>
    </el-card>

    <!-- 任务详情 -->
    <el-dialog v-model="detailVisible" title="任务详情" width="900px">
      <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
        <el-descriptions-item label="Job ID">{{ currentJob?.id }}</el-descriptions-item>
        <el-descriptions-item label="动作">{{ currentJob?.action_type }}</el-descriptions-item>
        <el-descriptions-item label="修订版本">
          v{{ currentJob?.revision_no || 1 }}{{ currentJob?.edit_mode === 'EDIT_REPUBLISH' ? '（编辑重投）' : '' }}
        </el-descriptions-item>
        <el-descriptions-item label="来源任务">{{ currentJob?.parent_job_id || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusTagType(currentJob?.status || '')" size="small">
            {{ statusLabel(currentJob?.status || '') }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="总数">{{ currentJob?.total_accounts }}</el-descriptions-item>
        <el-descriptions-item label="成功">{{ currentJob?.success_count }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ currentJob?.failed_count }}</el-descriptions-item>
        <el-descriptions-item label="创建">{{ currentJob?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="发布人">{{ currentJob?.publisher?.username || currentJob?.publisher?.email || currentJob?.created_by || '-' }}</el-descriptions-item>
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

      <el-divider content-position="left">修订历史</el-divider>
      <el-table :data="revisions" v-loading="revisionsLoading" size="small" border style="margin-bottom: 16px">
        <el-table-column prop="version" label="版本" width="80">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="变更" width="80">
          <template #default="{ row }">{{ row.diff?.length || 0 }} 项</template>
        </el-table-column>
        <el-table-column prop="published_job_id" label="提交任务" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新时间" width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="canEditRepublish && ['DRAFT', 'READY', 'INVALID'].includes(row.status) && currentJob"
              link
              type="primary"
              @click="continueRevision(row)"
            >
              继续编辑
            </el-button>
            <el-button
              v-if="canEditRepublish && ['DRAFT', 'READY', 'INVALID'].includes(row.status)"
              link
              type="danger"
              @click="discardRevision(row)"
            >
              放弃
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-table :data="currentJob?.items || []" size="small" max-height="380">
        <el-table-column prop="ad_account_id" label="广告账户" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="itemTagType(row.status)" size="small">{{ row.status }}</el-tag>
            <el-tag v-if="row.response_payload?.cleanup_failed" type="danger" size="small" style="margin-left:4px">待人工清理</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="meta_campaign_id" label="Meta Campaign" width="170" show-overflow-tooltip />
        <el-table-column label="AdSet / Ad" width="120">
          <template #default="{ row }">
            {{ (row.adset_ids?.length || 0) }} / {{ (row.ad_ids?.length || 0) }}
          </template>
        </el-table-column>
        <el-table-column prop="retry_count" label="重试" width="70" />
        <el-table-column label="Meta 状态" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.response_payload?.effective_status || row.response_payload?.meta_status || '-' }}
          </template>
        </el-table-column>
          <el-table-column label="错误" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.error_category" class="err-cat">[{{ row.error_category }}]</span>
            {{ row.error_message }}
          </template>
          </el-table-column>
        <el-table-column label="审核/错误详情" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.response_payload?.review_status || row.response_payload?.error_message || row.response_payload?.failure?.message || row.error_message || '-' }}
          </template>
        </el-table-column>
          <el-table-column label="待清理 Meta 对象" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.response_payload?.cleanup_object_ids?.join(', ') || '-' }}
            </template>
          </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button
          v-if="currentJob && canEditRepublish && currentJob.action_type === 'CREATE' && ['FAILED', 'PARTIAL_SUCCESS'].includes(currentJob.status)"
          type="success"
          @click="detailVisible = false; editRepublish(currentJob)"
        >
          编辑后重投
        </el-button>
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  jobsApi,
  isFinalStatus,
  type CampaignJob,
  type CampaignJobRevision,
} from '@/api/jobs'
import { useUserStore } from '@/stores/userStore'

const jobs = ref<CampaignJob[]>([])
const currentJob = ref<CampaignJob | null>(null)
const loading = ref(false)
const detailVisible = ref(false)
const revisions = ref<CampaignJobRevision[]>([])
const revisionsLoading = ref(false)
const statusFilter = ref('')
const autoRefresh = ref(true)
const userStore = useUserStore()
const router = useRouter()
const canRetry = computed(() => userStore.isAdmin || userStore.hasPermission('job:retry'))
const canCancel = computed(() => userStore.isAdmin || userStore.hasPermission('job:cancel'))
const canEditRepublish = computed(() => userStore.isAdmin || userStore.hasPermission('job:create'))
const summary = computed(() => ({
  total: jobs.value.length,
  running: jobs.value.filter((job) => !isFinal(job.status)).length,
  success: jobs.value.filter((job) => job.status === 'SUCCESS').length,
  failed: jobs.value.filter((job) => ['FAILED', 'PARTIAL_SUCCESS'].includes(job.status)).length,
}))

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

const statusLabel = (status: string) =>
  ({
    PENDING: '等待中',
    VALIDATING: '校验中',
    QUEUED: '排队中',
    RUNNING: '执行中',
    SUCCESS: '已完成',
    PARTIAL_SUCCESS: '部分成功',
    FAILED: '执行失败',
    CANCELLED: '已取消',
  }[status] || status || '-')

const shortId = (id: string) => id ? `${id.slice(0, 8)}…${id.slice(-6)}` : '-'
const formatDateTime = (value?: string | null) => value ? value.replace('T', ' ').slice(0, 19) : '-'

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
    DRAFT: 'info',
    READY: 'success',
    INVALID: 'danger',
    SUBMITTED: 'warning',
    DISCARDED: 'info',
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

const hasMoreActions = (row: CampaignJob) =>
  (canEditRepublish.value && row.action_type === 'CREATE' && ['FAILED', 'PARTIAL_SUCCESS'].includes(row.status))
  || canRetry.value
  || canCancel.value

const handleAction = (command: string, row: CampaignJob) => {
  if (command === 'edit') editRepublish(row)
  else if (command === 'retry') void handleRetry(row)
  else if (command === 'cancel') void handleCancel(row)
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

const loadRevisions = async (jobId: string) => {
  revisionsLoading.value = true
  try {
    const { data } = await jobsApi.listRevisions(jobId)
    revisions.value = data
  } catch {
    revisions.value = []
  } finally {
    revisionsLoading.value = false
  }
}

const viewDetail = async (id: string) => {
  const { data } = await jobsApi.get(id)
  currentJob.value = data
  await loadRevisions(id)
  detailVisible.value = true
  if (!isFinal(data.status)) startTimer()
}

const editRepublish = (row: CampaignJob) => {
  router.push({ path: '/dashboard/batch-publish', query: { source_job_id: row.id } })
}

const continueRevision = (revision: CampaignJobRevision) => {
  if (!currentJob.value) return
  detailVisible.value = false
  router.push({
    path: '/dashboard/batch-publish',
    query: { source_job_id: currentJob.value.id, revision_id: revision.id },
  })
}

const discardRevision = async (revision: CampaignJobRevision) => {
  try {
    await ElMessageBox.confirm(
      `确认放弃修订 v${revision.version}？该版本会保留审计记录，但不能继续编辑。`,
      '放弃修订',
      { type: 'warning', confirmButtonText: '确认放弃', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  await jobsApi.discardRevision(revision.id)
  ElMessage.success('修订已放弃')
  if (currentJob.value) await loadRevisions(currentJob.value.id)
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
    startTimer()
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
    if (currentJob.value?.id === row.id) {
      const { data } = await jobsApi.get(row.id)
      currentJob.value = data
    }
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

// 仅在存在进行中任务时才有必要轮询
const startTimer = () => {
  stopTimer()
  timer = window.setInterval(async () => {
    if (!autoRefresh.value) return
    const active = jobs.value.some((job) => !isFinal(job.status))
    if (!active && (!currentJob.value || isFinal(currentJob.value.status))) {
      stopTimer()
      return
    }
    await loadJobs()
    if (detailVisible.value && currentJob.value) {
      const { data } = await jobsApi.get(currentJob.value.id)
      currentJob.value = data
      if (isFinal(data.status) && !jobs.value.some((job) => !isFinal(job.status))) stopTimer()
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
.jobs-page { min-height: 100%; }
.jobs-shell { border: 0; border-radius: 16px; overflow: hidden; background: #fff; box-shadow: 0 8px 28px rgba(31, 55, 80, .06); }
.jobs-shell :deep(.el-card__header) { padding: 24px 24px 20px; border-bottom: 1px solid #edf1f5; }
.jobs-shell :deep(.el-card__body) { padding: 0 20px 20px; }
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;

  .title-block { min-width: 0; }
  .eyebrow { display: block; margin-bottom: 7px; color: #8a9aad; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }
  .page-title { margin: 0; color: #172b4d; font-size: 21px; font-weight: 700; }
  .page-desc { margin: 8px 0 0; color: #7b8da3; font-size: 13px; line-height: 1.65; max-width: 650px; }
}
.actions { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.status-select { width: 140px; }
.auto-refresh { margin: 0 2px 0 4px; color: #60758d; font-size: 13px; }
.auto-refresh span { color: #2f80ed; font-weight: 600; }
.refresh-button { border-color: #dbe5ef; color: #486581; }
.job-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; padding: 20px 4px 18px; }
.summary-card { display: flex; align-items: center; gap: 12px; min-height: 70px; padding: 13px 16px; border: 1px solid #edf1f5; border-radius: 12px; background: #fbfcfe; }
.summary-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; font-size: 19px; font-weight: 700; }
.summary-card div { display: flex; flex-direction: column; gap: 2px; }
.summary-label { color: #7b8da3; font-size: 12px; }
.summary-card strong { color: #172b4d; font-size: 23px; line-height: 1.1; }
.summary-card.total .summary-icon { color: #2f80ed; background: #eaf3ff; }
.summary-card.running .summary-icon { color: #9b6b00; background: #fff4d6; }
.summary-card.success .summary-icon { color: #2f9e62; background: #e7f7ee; }
.summary-card.failed .summary-icon { color: #d95757; background: #ffeded; }
.job-table { color: #40566f; }
.job-table :deep(th.el-table__cell) { height: 46px; color: #8495a8; background: #fbfcfe; font-size: 12px; font-weight: 600; }
.job-table :deep(td.el-table__cell) { height: 66px; border-bottom-color: #eef2f6; }
.job-table :deep(.el-table__row:hover > td.el-table__cell) { background: #f8fbff; }
.job-id { color: #6f839a; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.action-tag { color: #3978c7; border-color: #cfe2fa; background: #f3f8ff; }
.progress-cell { min-width: 155px; padding-right: 8px; }
.progress-line { display: flex; align-items: center; gap: 9px; }
.progress-line .el-progress { flex: 1; }
.progress-line > span { width: 36px; color: #60758d; font-size: 12px; text-align: right; }
.progress-cell small { display: block; margin-top: 5px; color: #9aaabd; font-size: 11px; }
.result-counts { display: flex; flex-wrap: wrap; gap: 4px 8px; color: #8495a8; font-size: 12px; line-height: 1.5; }
.result-success { color: #36a269; }
.result-failed { color: #e06464; }
.created-time { color: #6f839a; font-size: 12px; }
.operation-actions { display: flex; align-items: center; gap: 6px; }
.detail-button { border-color: #cfe2fa; }
.more-button { color: #60758d; border-color: #dbe5ef; }
.more-button :deep(.el-icon) { margin-left: 3px; }
.err-cat { color: #e6a23c; margin-right: 4px; }
@media (max-width: 1050px) {
  .header-bar { flex-direction: column; }
  .actions { width: 100%; justify-content: flex-end; }
  .job-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>

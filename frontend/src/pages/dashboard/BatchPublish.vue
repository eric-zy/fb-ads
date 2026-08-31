<template>
  <div class="batch-publish">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">批量投放</h2>
            <p class="page-desc">
              选择<b>投放模板</b>与目标广告账户，系统按「模板 → 账户」生成部署任务：
              每个账户独立创建 Campaign / AdSet / Ad，全部进入队列异步执行，
              可实时查看进度、失败可单独重跑。
            </p>
          </div>
        </div>
      </template>

      <el-form label-width="110px" :model="form">
        <!-- 模板 -->
        <el-form-item label="投放模板" required>
          <el-select
            v-model="form.template_id"
            filterable
            placeholder="选择投放模板"
            style="width: 100%"
            :loading="loadingTemplates"
          >
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="`${t.name}（${t.objective || '-'} · $${t.daily_budget ?? '-'}/天）`"
              :value="t.id"
            />
          </el-select>
          <div class="tip">一次配置模板，即可批量部署到任意数量账户。</div>
        </el-form-item>

        <!-- 账户多选 -->
        <el-form-item label="广告账户" required>
          <el-select
            v-model="form.ad_account_ids"
            multiple
            filterable
            placeholder="选择目标账户"
            style="width: 100%"
            :loading="loadingAccounts"
          >
            <el-option
              v-for="a in accounts"
              :key="a.id"
              :label="`${a.account_name || a.account_id} (${a.account_id})`"
              :value="a.id"
            />
          </el-select>
        </el-form-item>

        <!-- 预算覆盖 -->
        <el-form-item label="预算覆盖">
          <el-input-number v-model="form.budget_override" :min="0" :step="10" />
          <span class="tip-inline">为 0 或留空时沿用模板预算（美元/天）</span>
        </el-form-item>

        <!-- 投放状态 -->
        <el-form-item label="投放状态">
          <el-select v-model="form.status" style="width: 240px">
            <el-option label="暂停（推荐，确认后再启用）" value="PAUSED" />
            <el-option label="立即启用" value="ACTIVE" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :disabled="!canSubmit"
            :loading="submitting"
            @click="submit"
          >
            提交批量投放
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 当前任务进度 -->
      <template v-if="currentJob">
        <el-divider>任务进度</el-divider>
        <p class="job-line">
          任务 <b>{{ currentJob.id }}</b> ·
          <el-tag :type="statusTagType(currentJob.status)" size="small">
            {{ currentJob.status }}
          </el-tag>
        </p>
        <el-progress :percentage="progressPercent" :status="progressStatus" />
        <p class="job-line">
          总计 <b>{{ currentJob.total_accounts }}</b> ·
          成功 <b style="color:#67c23a">{{ currentJob.success_count }}</b> ·
          失败 <b style="color:#f56c6c">{{ currentJob.failed_count }}</b>
        </p>

        <el-table :data="currentJob.items || []" size="small" max-height="300">
          <el-table-column prop="ad_account_id" label="账户" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag :type="itemTagType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="meta_campaign_id" label="Meta Campaign" width="160" show-overflow-tooltip />
          <el-table-column prop="retry_count" label="重试" width="70" />
          <el-table-column label="错误" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.error_category" class="err-cat">[{{ row.error_category }}]</span>
              {{ row.error_message }}
            </template>
          </el-table-column>
        </el-table>

        <div v-if="currentJob.failed_count > 0" style="margin-top: 12px">
          <el-button type="warning" size="small" @click="retryFailed">
            重跑失败账户（{{ currentJob.failed_count }}）
          </el-button>
          <span class="tip-inline">仅重跑失败项，不影响已成功的账户</span>
        </div>
      </template>

      <!-- 历史任务 -->
      <el-divider>历史任务</el-divider>
      <el-table :data="jobs" size="small" v-loading="loadingJobs">
        <el-table-column prop="id" label="Job ID" width="240" show-overflow-tooltip />
        <el-table-column prop="action_type" label="动作" width="120" />
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_accounts" label="总数" width="80" />
        <el-table-column prop="success_count" label="成功" width="80" />
        <el-table-column prop="failed_count" label="失败" width="80" />
        <el-table-column prop="created_at" label="创建时间" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewJob(row.id)">查看</el-button>
            <el-button
              link
              type="danger"
              :disabled="isFinalStatus(row.status)"
              @click="cancelJob(row.id)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { templatesApi, type CampaignTemplate } from '@/api/templates'
import {
  jobsApi,
  isFinalStatus,
  type CampaignJob,
} from '@/api/jobs'

const templates = ref<CampaignTemplate[]>([])
const accounts = ref<AdAccountItem[]>([])
const jobs = ref<CampaignJob[]>([])
const currentJob = ref<CampaignJob | null>(null)

const loadingTemplates = ref(false)
const loadingAccounts = ref(false)
const loadingJobs = ref(false)
const submitting = ref(false)

let pollTimer: number | null = null

const form = reactive({
  template_id: '',
  ad_account_ids: [] as string[],
  budget_override: 0,
  status: 'PAUSED',
})

const canSubmit = computed(() => !!form.template_id && form.ad_account_ids.length > 0)

const progressPercent = computed(() => {
  if (!currentJob.value || !currentJob.value.total_accounts) return 0
  const done = currentJob.value.success_count + currentJob.value.failed_count
  return Math.round((done / currentJob.value.total_accounts) * 100)
})

const progressStatus = computed(() => {
  if (!currentJob.value) return undefined
  if (currentJob.value.status === 'SUCCESS') return 'success'
  if (currentJob.value.status === 'FAILED' || currentJob.value.status === 'CANCELLED') {
    return 'exception'
  }
  return undefined
})

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

// ---------------- 数据加载 ----------------
const loadTemplates = async () => {
  loadingTemplates.value = true
  try {
    const { data } = await templatesApi.list('ACTIVE')
    templates.value = data
  } finally {
    loadingTemplates.value = false
  }
}

const loadAccounts = async () => {
  loadingAccounts.value = true
  try {
    const { data } = await accountApi.list()
    accounts.value = data
  } finally {
    loadingAccounts.value = false
  }
}

const loadJobs = async () => {
  loadingJobs.value = true
  try {
    const { data } = await jobsApi.list({ limit: 50 })
    jobs.value = data
  } finally {
    loadingJobs.value = false
  }
}

// ---------------- 任务提交与轮询 ----------------
const stopPolling = () => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

const startPolling = (jobId: string) => {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      const { data } = await jobsApi.get(jobId)
      currentJob.value = data
      if (isFinalStatus(data.status)) {
        stopPolling()
        await loadJobs()
      }
    } catch (e) {
      stopPolling()
    }
  }, 2000)
}

const submit = async () => {
  if (!canSubmit.value) {
    ElMessage.warning('请选择投放模板与至少一个广告账户')
    return
  }
  submitting.value = true
  try {
    const { data } = await jobsApi.createCampaign({
      template_id: form.template_id,
      ad_account_ids: form.ad_account_ids,
      budget_override: form.budget_override || undefined,
      status: form.status,
    })
    ElMessage.success(`任务已提交：${data.job_id}（共 ${data.total_accounts} 个账户）`)
    const { data: job } = await jobsApi.get(data.job_id)
    currentJob.value = job
    startPolling(data.job_id)
    await loadJobs()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    submitting.value = false
  }
}

const viewJob = async (id: string) => {
  const { data } = await jobsApi.get(id)
  currentJob.value = data
  if (!isFinalStatus(data.status)) startPolling(id)
}

const retryFailed = async () => {
  if (!currentJob.value) return
  try {
    await jobsApi.retry(currentJob.value.id)
    ElMessage.success('已重新分派失败账户')
    startPolling(currentJob.value.id)
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const cancelJob = async (id: string) => {
  try {
    await jobsApi.cancel(id)
    ElMessage.success('任务已取消')
    await loadJobs()
    if (currentJob.value?.id === id) {
      const { data } = await jobsApi.get(id)
      currentJob.value = data
    }
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

onMounted(() => {
  loadTemplates()
  loadAccounts()
  loadJobs()
})

onUnmounted(stopPolling)
</script>

<style scoped lang="scss">
.header-bar {
  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; }
}
.tip { color: #909399; font-size: 12px; margin-top: 4px; }
.tip-inline { color: #909399; font-size: 12px; margin-left: 10px; }
.job-line { margin: 8px 0; }
.err-cat { color: #e6a23c; margin-right: 4px; }
</style>

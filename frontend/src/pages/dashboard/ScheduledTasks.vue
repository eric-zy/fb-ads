<template>
  <div class="scheduled-tasks-page">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">定时投放</h2>
            <p class="page-desc">
              定时投放复用 Job 体系：选择模板与账户并指定执行时间后，任务以 QUEUED 状态落库，
              由 Celery 在指定时刻触发执行。执行进度与结果可在「任务中心」查看。
            </p>
          </div>
          <div class="actions">
            <el-button :icon="Refresh" @click="loadTasks">刷新</el-button>
            <el-button type="primary" @click="openCreate">新建定时投放</el-button>
          </div>
        </div>
      </template>

      <el-table :data="tasks" v-loading="loading" size="small">
        <el-table-column prop="id" label="Job ID" width="240" show-overflow-tooltip />
        <el-table-column label="动作" width="110">
          <template #default="{ row }">
            <el-tag size="small">{{ actionLabel(row.action_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="计划执行时间" width="180">
          <template #default="{ row }">
            <span>{{ formatTime(row.scheduled_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="倒计时" width="130">
          <template #default="{ row }">
            <span :class="{ soon: countdown(row.scheduled_at) === '即将执行' }">
              {{ countdown(row.scheduled_at) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="total_accounts" label="账户数" width="90" />
        <el-table-column prop="created_at" label="创建时间" width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="handleDispatchNow(row)">立即执行</el-button>
            <el-button link type="primary" @click="goToJobs(row.id)">查看</el-button>
            <el-button link type="danger" @click="handleCancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !tasks.length" description="暂无待执行的定时任务" />
    </el-card>

    <!-- 新建定时投放 -->
    <el-dialog
      v-model="dialogVisible"
      title="新建定时投放"
      width="620px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="120px">
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
        </el-form-item>

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

        <el-form-item label="预算覆盖">
          <el-input-number v-model="form.budget_override" :min="0" :step="10" />
          <span class="tip-inline">为 0 时沿用模板预算（美元/天）</span>
        </el-form-item>

        <el-form-item label="投放状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="暂停（推荐，确认后再启用）" value="PAUSED" />
            <el-option label="立即启用" value="ACTIVE" />
          </el-select>
        </el-form-item>

        <el-form-item label="执行时间" required>
          <el-date-picker
            v-model="form.scheduledTime"
            type="datetime"
            placeholder="选择执行时间"
            style="width: 100%"
            :disabled-date="disablePastDate"
            format="YYYY-MM-DD HH:mm"
            value-format="x"
          />
          <div class="tip">
            时间为本地时区（{{ timezoneLabel }}），提交时会自动带上时区偏移，由后端换算为 UTC。
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">创建定时任务</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { templatesApi, type CampaignTemplate } from '@/api/templates'
import { jobsApi, type CampaignJob } from '@/api/jobs'

const router = useRouter()

const tasks = ref<CampaignJob[]>([])
const templates = ref<CampaignTemplate[]>([])
const accounts = ref<AdAccountItem[]>([])

const loading = ref(false)
const loadingTemplates = ref(false)
const loadingAccounts = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)

let timer: number | null = null

const form = reactive({
  template_id: '',
  ad_account_ids: [] as string[],
  budget_override: 0,
  status: 'PAUSED',
  /** el-date-picker 的 value-format="x" 返回毫秒时间戳字符串 */
  scheduledTime: '' as string,
})

const timezoneLabel = computed(() => {
  const offset = -new Date().getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const abs = Math.abs(offset)
  const h = String(Math.floor(abs / 60)).padStart(2, '0')
  const m = String(abs % 60).padStart(2, '0')
  return `UTC${sign}${h}:${m}`
})

const actionLabel = (action: string) =>
  ({ CREATE: '批量创建', PAUSE: '批量暂停', ENABLE: '批量启用', UPDATE_BUDGET: '批量改预算' }[action] || action)

const statusTagType = (status: string) =>
  ({ PENDING: 'info', QUEUED: 'warning', RUNNING: 'primary', SUCCESS: 'success',
     PARTIAL_SUCCESS: 'warning', FAILED: 'danger', CANCELLED: 'info' }[status] || 'info')

const formatTime = (iso?: string | null) => {
  if (!iso) return '-'
  // 后端存的是 UTC naive，补 Z 让浏览器按 UTC 解析
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleString()
}

const countdown = (iso?: string | null) => {
  if (!iso) return '-'
  const target = new Date(iso.endsWith('Z') ? iso : iso + 'Z').getTime()
  const diff = target - Date.now()
  if (diff <= 0) return '即将执行'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins} 分钟后`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时 ${mins % 60} 分后`
  return `${Math.floor(hours / 24)} 天 ${hours % 24} 小时后`
}

// ---------- 数据加载 ----------
const loadTasks = async () => {
  loading.value = true
  try {
    const { data } = await jobsApi.listScheduled(100)
    tasks.value = data
  } finally {
    loading.value = false
  }
}

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

// ---------- 创建 ----------
const disablePastDate = (date: Date) => date.getTime() < Date.now() - 60_000

const openCreate = () => {
  form.template_id = ''
  form.ad_account_ids = []
  form.budget_override = 0
  form.status = 'PAUSED'
  form.scheduledTime = ''
  dialogVisible.value = true
  if (!templates.value.length) loadTemplates()
  if (!accounts.value.length) loadAccounts()
}

/** 本地时间 → 带时区偏移的 ISO 8601（后端换算为 UTC） */
const toIsoWithOffset = (date: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0')
  const offsetMin = -date.getTimezoneOffset()
  const sign = offsetMin >= 0 ? '+' : '-'
  const abs = Math.abs(offsetMin)
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:00` +
    `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
  )
}

const submit = async () => {
  if (!form.template_id || !form.ad_account_ids.length) {
    ElMessage.warning('请选择投放模板与至少一个广告账户')
    return
  }
  if (!form.scheduledTime) {
    ElMessage.warning('请选择执行时间')
    return
  }

  const when = new Date(Number(form.scheduledTime))
  if (when.getTime() <= Date.now()) {
    ElMessage.warning('执行时间必须晚于当前时间')
    return
  }

  submitting.value = true
  try {
    const { data } = await jobsApi.scheduleCampaign({
      template_id: form.template_id,
      ad_account_ids: form.ad_account_ids,
      budget_override: form.budget_override || undefined,
      status: form.status,
      scheduled_at: toIsoWithOffset(when),
    })
    ElMessage.success(`定时任务已创建：${data.job_id}`)
    dialogVisible.value = false
    await loadTasks()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    submitting.value = false
  }
}

// ---------- 操作 ----------
const handleDispatchNow = async (row: CampaignJob) => {
  try {
    await ElMessageBox.confirm('将撤销原定时间并立即执行该任务，确定继续？', '立即执行', {
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    await jobsApi.dispatchNow(row.id)
    ElMessage.success('任务已提交执行')
    await loadTasks()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const handleCancel = async (row: CampaignJob) => {
  try {
    await ElMessageBox.confirm('取消后该定时任务将不再执行，确定继续？', '取消确认', {
      type: 'warning',
    })
  } catch {
    return
  }

  try {
    await jobsApi.cancel(row.id)
    ElMessage.success('定时任务已取消')
    await loadTasks()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const goToJobs = (jobId: string) => {
  router.push('/dashboard/jobs')
}

onMounted(() => {
  loadTasks()
  loadTemplates()
  loadAccounts()
  // 每分钟刷新倒计时与列表
  timer = window.setInterval(loadTasks, 60_000)
})

onUnmounted(() => {
  if (timer !== null) window.clearInterval(timer)
})
</script>

<style scoped lang="scss">
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;

  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; max-width: 640px; }
}
.actions { display: flex; gap: 8px; }
.tip { color: #909399; font-size: 12px; margin-top: 4px; line-height: 1.5; }
.tip-inline { color: #909399; font-size: 12px; margin-left: 10px; }
.soon { color: #e6a23c; font-weight: 600; }
</style>

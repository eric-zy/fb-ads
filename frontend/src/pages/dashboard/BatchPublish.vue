<template>
  <div class="batch-publish">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">{{ t('pages.batch') }}</h2>
            <p class="page-desc">
              选择<b>投放模板</b>与目标广告账户，系统按「模板 → 账户」生成部署任务：
              每个账户独立创建 Campaign / AdSet / Ad，全部进入队列异步执行，
              可实时查看进度、失败可单独重跑。
            </p>
          </div>
        </div>
      </template>

      <el-steps :active="activeStep" finish-status="success" simple class="publish-steps">
        <el-step title="选择模板" />
        <el-step title="广告系列与广告组" />
        <el-step title="广告账户与投放" />
        <el-step title="预览提交" />
      </el-steps>
      <el-form label-width="110px" :model="form" class="publish-form">
        <section v-if="activeStep === 0" class="step-panel">
          <h3>选择投放模板</h3>
          <p class="step-desc">模板包含 Campaign、AdSet、Ad 和素材文案配置，本次投放只覆盖需要变化的参数。</p>
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
            <template #empty>
              <div class="template-empty">
                <span>暂无可用投放模板</span>
                <el-button link type="primary" @click="goCreateTemplate">去创建模板</el-button>
              </div>
            </template>
          </el-select>
          <div class="tip">一次配置模板，即可批量部署到任意数量账户。</div>
          </el-form-item>
          <el-alert v-if="selectedTemplate" type="info" :closable="false" show-icon title="模板内容">
            {{ selectedTemplate.name }} · {{ selectedTemplate.objective || '未设置目标' }} ·
            {{ creativeCount(selectedTemplate) }} 个广告创意
          </el-alert>
          <el-alert v-if="selectedTemplate && !templateReady" type="warning" :closable="false" show-icon>
            该模板尚未选择 Facebook Page，请先到「投放模板」编辑并选择已同步页面。
          </el-alert>
          <el-alert v-if="assetBindings.length" type="info" :closable="false" show-icon title="素材映射">
            素材会在各广告账户的 Celery 子任务中独立上传，不共用 image hash / video ID。
          </el-alert>
          <el-table v-if="assetBindings.length" :data="assetBindings" size="small" style="margin-top:12px">
            <el-table-column prop="asset_id" label="素材" show-overflow-tooltip />
            <el-table-column prop="ad_account_id" label="广告账户" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="110" />
          </el-table>
        </section>
        <section v-else-if="activeStep === 1" class="step-panel">
          <h3>广告系列与广告组</h3>
          <p class="step-desc">以下配置来自模板，将为每个目标广告账户创建独立的 Campaign、AdSet 和 Ad。</p>
          <el-descriptions v-if="selectedTemplate" :column="2" border>
            <el-descriptions-item label="广告系列目标">{{ selectedTemplate.objective || '-' }}</el-descriptions-item>
            <el-descriptions-item label="购买类型">{{ selectedTemplate.buying_type || 'AUCTION' }}</el-descriptions-item>
            <el-descriptions-item label="优化目标">{{ selectedTemplate.optimization_goal || '-' }}</el-descriptions-item>
            <el-descriptions-item label="计费事件">{{ selectedTemplate.billing_event || '-' }}</el-descriptions-item>
            <el-descriptions-item label="默认预算">{{ templateBudget }}</el-descriptions-item>
            <el-descriptions-item label="广告创意">{{ creativeCount(selectedTemplate) }} 个</el-descriptions-item>
          </el-descriptions>
          <el-alert type="warning" :closable="false" show-icon title="模板配置">
            如需修改 Campaign / AdSet / Ad 配置，请先在投放模板中编辑。本次投放可覆盖预算和状态，不会修改模板原始内容。
          </el-alert>
          <el-alert v-if="form.sinan_promotion_id" type="success" :closable="false" show-icon title="已关联司南推广链">{{ form.sinan_promotion_id }}</el-alert>
        </section>
        <section v-else-if="activeStep === 2" class="step-panel">
          <h3>广告账户与本次投放参数</h3>
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
              :label="`${a.account_name || a.account_id} (${a.account_id}) · 支付 ${a.payment_status || 'UNKNOWN'}`"
              :value="a.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="预算覆盖">
          <el-input-number v-model="form.budget_override" :min="0" :step="10" />
          <span class="tip-inline">为 0 或留空时沿用模板预算（美元/天）</span>
        </el-form-item>

        <el-form-item label="投放状态">
          <el-radio-group v-model="form.status">
            <el-radio value="PAUSED">暂停（推荐）</el-radio>
            <el-radio value="ACTIVE">立即启用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-alert v-if="form.status === 'PAUSED'" type="info" :closable="false" show-icon>
          暂停（调试）允许选择未配置支付方式的账户，但不会开始投放；切换为立即启用后，系统只接受支付状态为 AVAILABLE 的账户。
        </el-alert>
        <el-table v-if="selectedAccountRows.length" :data="selectedAccountRows" size="small" style="margin-bottom: 12px">
          <el-table-column prop="account_name" label="账户" show-overflow-tooltip />
          <el-table-column prop="account_id" label="Account ID" show-overflow-tooltip />
          <el-table-column label="支付状态" width="140">
            <template #default="{ row }">
              <el-tag :type="row.payment_status === 'AVAILABLE' ? 'success' : form.status === 'PAUSED' ? 'warning' : 'danger'" size="small">
                {{ row.payment_status || 'UNKNOWN' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="payment_source" label="支付来源" width="140" />
        </el-table>

        <el-form-item v-if="selectedAccountRows.length" label="发布 BM">
          <div class="access-business-list">
            <div v-for="account in selectedAccountRows" :key="account.id" class="access-business-row">
              <span class="account-label">{{ account.account_name || account.account_id }}</span>
              <el-select v-model="accessBusinessIds[account.id]" filterable style="width: 260px" placeholder="选择访问 BM">
                <el-option
                  v-for="business in account.accessible_businesses || []"
                  :key="business.business_id"
                  :label="`${business.business_name || business.meta_business_id || business.business_id} · ${business.access_level}`"
                  :value="business.business_id"
                />
              </el-select>
            </div>
          </div>
          <span class="tip-inline">不选择时使用广告账户原始归属 BM；共享账户发布时请明确选择有权限的 BM。</span>
        </el-form-item>
        <el-alert v-if="!loadingAccounts && !accounts.length" type="warning" :closable="false" show-icon>
          当前没有可投放广告账户，请先完成 Meta OAuth 授权或恢复有效凭据。
        </el-alert>
        <el-alert type="info" :closable="false" show-icon title="地区与人群">
          当前版本沿用模板中的定向配置；地区、人群覆盖字段已预留，下一阶段接入 Meta 定向编辑器。
        </el-alert>
        </section>
        <section v-else class="step-panel">
          <h3>预览并提交</h3>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="投放模板">{{ selectedTemplate?.name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="目标账户">{{ form.ad_account_ids.length }} 个</el-descriptions-item>
            <el-descriptions-item label="部署结构">每个账户 1 个 Campaign → {{ adsetCount(selectedTemplate) }} 个 AdSet → {{ creativeCount(selectedTemplate) * adsetCount(selectedTemplate) }} 个 Ad</el-descriptions-item>
            <el-descriptions-item label="预算">{{ form.budget_override ? form.budget_override + ' 美元/天（本次覆盖）' : templateBudget + '（沿用模板）' }}</el-descriptions-item>
            <el-descriptions-item label="初始状态">{{ form.status === 'ACTIVE' ? '立即启用' : '暂停' }}</el-descriptions-item>
          </el-descriptions>
          <el-table :data="selectedAccountRows" size="small" style="margin-top: 12px">
            <el-table-column prop="account_name" label="账户" show-overflow-tooltip />
            <el-table-column prop="account_id" label="Account ID" show-overflow-tooltip />
            <el-table-column prop="payment_status" label="支付状态" width="140" />
            <el-table-column prop="business.name" label="归属 BM" show-overflow-tooltip />
            <el-table-column v-if="preflightBlockedAccounts.length" label="预检结果" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="preflightReasonByAccount[row.id] || preflightReasonByAccount[row.account_id]" class="preflight-blocked">
                  {{ preflightReasonByAccount[row.id] || preflightReasonByAccount[row.account_id] }}
                </span>
                <span v-else class="preflight-ready">可投放</span>
              </template>
            </el-table-column>
          </el-table>
          <el-alert type="warning" :closable="false" show-icon title="提交后将创建异步投放任务">
            系统会逐账户执行，失败账户不会影响已成功账户，可在任务中心重试失败项。
          </el-alert>
          <el-alert v-if="preflightResult" :type="preflightResult.passed ? 'success' : 'error'" :closable="false" show-icon style="margin-top:12px">
            <template #title>{{ preflightResult.passed ? `预检通过：${preflightResult.ready_account_ids.length} 个账户可投放` : '预检未通过，暂不能提交' }}</template>
            <div v-for="item in preflightResult.errors" :key="`error-${item.code}`" class="preflight-error-item">{{ item.message }}</div>
            <div v-for="item in preflightResult.warnings" :key="`warning-${item.code}`" class="preflight-warning">
              <div>{{ item.message }}</div>
              <div v-for="blocked in (item.items || [])" :key="`${item.code}-${blocked.account_id}-${blocked.reason}`" class="preflight-detail">
                账户 {{ blocked.account_id }}：{{ blocked.reason }}
              </div>
            </div>
            <el-button v-if="missingAssetAccounts.length" type="primary" size="small" style="margin-top:8px" :loading="syncingAssets" @click="syncMissingAssets">
              立即同步缺失素材
            </el-button>
          </el-alert>
        </section>
        <div class="step-actions">
          <el-button v-if="activeStep > 0" @click="activeStep--">{{ t('pages.previous') }}</el-button>
          <el-button v-if="activeStep < 3" type="primary" :loading="preflighting" :disabled="!canNext" @click="nextStep">{{ t('pages.next') }}</el-button>
          <el-button v-else type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">{{ t('pages.submit') }}</el-button>
        </div>
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
            <el-tag v-if="row.response_payload?.cleanup_failed" type="danger" size="small" style="margin-left:4px">待人工清理</el-tag>
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
          <el-table-column label="待清理 Meta 对象" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.response_payload?.cleanup_object_ids?.join(', ') || '-' }}
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
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi, type DeployableAccount } from '@/api/admin'
import { templatesApi, type CampaignTemplate } from '@/api/templates'
import { mediaApi, type MetaAssetBinding } from '@/api/media'
import { useLocale } from '@/stores/localeStore'
const { t } = useLocale()
import {
  jobsApi,
  isFinalStatus,
  type CampaignJob,
} from '@/api/jobs'

const router = useRouter()
const route = useRoute()
const templates = ref<CampaignTemplate[]>([])
const accounts = ref<DeployableAccount[]>([])
const jobs = ref<CampaignJob[]>([])
const currentJob = ref<CampaignJob | null>(null)

const loadingTemplates = ref(false)
const loadingAccounts = ref(false)
const loadingJobs = ref(false)
const submitting = ref(false)
const syncingAssets = ref(false)
const preflighting = ref(false)
const preflightResult = ref<any>(null)
const rateLimitStatus = ref<{ count: number; limit: number; usage_ratio: number } | null>(null)
const assetBindings = ref<MetaAssetBinding[]>([])
const activeStep = ref(0)

let pollTimer: number | null = null
let assetPollTimer: number | null = null

const form = reactive({
  template_id: '',
  ad_account_ids: [] as string[],
  budget_override: 0,
  status: 'PAUSED',
  sinan_promotion_id: String(route.query.sinan_promotion_id || ''),
})

const selectedTemplate = computed(() => templates.value.find(t => t.id === form.template_id) || null)
const templateReady = computed(() => !!selectedTemplate.value?.creative_config_json?.page_id)
const canSubmit = computed(() => !!form.template_id && templateReady.value && form.ad_account_ids.length > 0 && !!preflightResult.value?.passed)
const templateBudget = computed(() => {
  if (!selectedTemplate.value) return '-'
  if (selectedTemplate.value.budget_type === 'LIFETIME') return '$' + (selectedTemplate.value.lifetime_budget ?? '-') + ' 总预算'
  return '$' + (selectedTemplate.value.daily_budget ?? '-') + ' / 天'
})
const accessBusinessIds = reactive<Record<string, string>>({})
const selectedAccountRows = computed(() => accounts.value.filter(account => form.ad_account_ids.includes(account.id)))
const creativeCount = (template: CampaignTemplate | null) => {
  const creatives = template?.creative_config_json?.creatives
  return Array.isArray(creatives) && creatives.length ? creatives.length : template?.creative_config_json ? 1 : 0
}
const adsetCount = (template: CampaignTemplate | null) => {
  const adsets = template?.creative_config_json?.adsets
  return Array.isArray(adsets) && adsets.length ? adsets.length : 1
}
const canNext = computed(() => {
  if (activeStep.value === 0) return !!form.template_id && templateReady.value
  if (activeStep.value === 2) return form.ad_account_ids.length > 0
  return true
})
const goCreateTemplate = () => router.push('/dashboard/templates')

const nextStep = async () => {
  if (activeStep.value === 2) {
    await runPreflight()
    if (!preflightResult.value?.passed) return
  }
  activeStep.value++
}

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
    const { data } = await accountApi.availableForDeployment({ allow_paused_debug: true })
    // 接口返回 { total, accounts }，不能把整个响应对象当成账户数组。
    accounts.value = data.accounts || []
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

const loadRateLimitStatus = async () => {
  const first = selectedAccountRows.value[0]
  if (!first) { rateLimitStatus.value = null; return }
  try {
    const { data } = await accountApi.rateLimitStatus(first.id)
    rateLimitStatus.value = data.rate_limits?.hour || null
  } catch { rateLimitStatus.value = null }
}

const syncAccessBusinessDefaults = () => {
  for (const account of selectedAccountRows.value) {
    if (accessBusinessIds[account.id]) continue
    const owner = account.accessible_businesses?.find(item => item.business_id === account.business?.id)
    const first = owner || account.accessible_businesses?.find(item => item.status === 'ACTIVE')
    if (first) accessBusinessIds[account.id] = first.business_id
  }
  for (const id of Object.keys(accessBusinessIds)) {
    if (!form.ad_account_ids.includes(id)) delete accessBusinessIds[id]
  }
}

const pollAssetBindings = (assetIds: string[]) => {
  if (assetPollTimer !== null) window.clearInterval(assetPollTimer)
  let rounds = 0
  assetPollTimer = window.setInterval(async () => {
    rounds += 1
    try {
      const results = await Promise.all(assetIds.map(id => mediaApi.bindings(String(id))))
      assetBindings.value = results.flatMap(result => result.data)
      const pending = assetBindings.value.some(row => ['PENDING', 'UPLOADING'].includes(row.status))
      if (!pending || rounds >= 30) {
        window.clearInterval(assetPollTimer as number)
        assetPollTimer = null
      }
    } catch {
      if (rounds >= 30) window.clearInterval(assetPollTimer as number)
    }
  }, 2000)
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
    ElMessage.warning(!templateReady.value ? '模板尚未选择有效 Facebook 页面' : '请选择至少一个可投放广告账户')
    return
  }
  // 二次确认前不准备素材、不创建 Job；用户取消时不会产生任何外部副作用。
  try {
    await ElMessageBox.confirm(
      `即将为 ${form.ad_account_ids.length} 个账户创建 ${form.status === 'PAUSED' ? '暂停（调试）' : '立即启用'}广告对象。${form.status === 'PAUSED' ? '暂停状态不会开始投放，但仍可能受 Meta 账户资格限制。' : '立即启用可能产生实际广告费用。'}确认继续吗？`,
      '确认提交广告发布',
      {
        type: form.status === 'ACTIVE' ? 'warning' : 'info',
        confirmButtonText: '确认提交',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  // 预览页停留期间账户状态可能已变化，提交前重新执行只读预检。
  await runPreflight()
  if (!preflightResult.value?.passed) {
    ElMessage.error('提交前预检未通过，请处理阻断项')
    return
  }

  submitting.value = true
  try {
    syncAccessBusinessDefaults()
    // 素材是按广告账户生成 Meta 映射的；先创建映射占位，再提交创建任务。
    // 真正的上传由后端异步投放任务处理，避免前端等待多个账户上传。
    const creatives = selectedTemplate.value?.creative_config_json?.creatives
    const assetIds = Array.isArray(creatives)
      ? [...new Set(creatives.map((item: any) => item?.asset_id).filter(Boolean))]
      : []
    if (assetIds.length) {
      const prepared = await Promise.all(assetIds.map(assetId => mediaApi.prepare(String(assetId), form.ad_account_ids)))
      assetBindings.value = prepared.flatMap(response => response.data.bindings)
      pollAssetBindings(assetIds.map(String))
    }
    const { data } = await jobsApi.createCampaign({
      template_id: form.template_id,
      ad_account_ids: form.ad_account_ids,
      budget_override: form.budget_override || undefined,
      status: form.status,
      sinan_promotion_id: form.sinan_promotion_id || undefined,
      access_business_ids: Object.keys(accessBusinessIds).length ? { ...accessBusinessIds } : undefined,
    })
    if (data.rejected_accounts?.length) {
      ElMessage.warning(`有 ${data.rejected_accounts.length} 个账号未进入任务，请检查账号状态`)
    }
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

const runPreflight = async () => {
  if (!form.template_id || !form.ad_account_ids.length) return
  preflighting.value = true
  try {
  syncAccessBusinessDefaults()
  const { data } = await jobsApi.preflightCampaign({ template_id: form.template_id, ad_account_ids: form.ad_account_ids, budget_override: form.budget_override || undefined, status: form.status, sinan_promotion_id: form.sinan_promotion_id || undefined, access_business_ids: Object.keys(accessBusinessIds).length ? { ...accessBusinessIds } : undefined })
    preflightResult.value = data
    if (!data.passed) ElMessage.error('预检未通过，请处理阻断项')
  } finally { preflighting.value = false }
}

// 账户选择变化后刷新限流水位；这是参考水位，不替代 Meta app-level 限流返回。
watch(form, loadRateLimitStatus, { deep: true })

const missingAssetAccounts = computed(() => (preflightResult.value?.warnings || []).filter((item: any) => item.code === 'ACCOUNTS_REJECTED' && item.items?.some((row: any) => row.reason === '素材尚未同步完成')))
const preflightBlockedAccounts = computed(() => (preflightResult.value?.warnings || []).flatMap((item: any) => item.items || []))
const preflightReasonByAccount = computed<Record<string, string>>(() => Object.fromEntries(preflightBlockedAccounts.value.map((item: any) => [item.account_id, item.reason || '预检未通过'])))

const syncMissingAssets = async () => {
  const rows = missingAssetAccounts.value.flatMap((warning: any) => warning.items || []).filter((row: any) => row.reason === '素材尚未同步完成')
  const assetIds = [...new Set(rows.flatMap((row: any) => row.asset_ids || []))]
  const accountIds = [...new Set(rows.map((row: any) => row.account_id))]
  if (!assetIds.length || !accountIds.length) return
  syncingAssets.value = true
  try {
    await Promise.all(assetIds.map(assetId => mediaApi.prepare(String(assetId), accountIds)))
    ElMessage.success('已提交缺失素材同步任务，请稍后重新预检')
    await runPreflight()
  } finally {
    syncingAssets.value = false
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
  const presetAccounts = String(route.query.account_ids || '').split(',').filter(Boolean)
  if (presetAccounts.length) form.ad_account_ids = presetAccounts
})

onUnmounted(() => {
  if (assetPollTimer !== null) window.clearInterval(assetPollTimer)
})

onUnmounted(stopPolling)
</script>

<style scoped lang="scss">
.preflight-error-item { color: #f56c6c; margin-top: 4px; }
.preflight-warning { color: #e6a23c; margin-top: 4px; }
.preflight-detail { color: #606266; font-size: 12px; margin: 3px 0 0 16px; }
.preflight-blocked { color: #f56c6c; }
.preflight-ready { color: #67c23a; }
.header-bar {
  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; }
}
.tip { color: #909399; font-size: 12px; margin-top: 4px; }
.tip-inline { color: #909399; font-size: 12px; margin-left: 10px; }
.publish-steps { margin: 6px 0 28px; }
.publish-form { max-width: 920px; }
.step-panel { min-height: 270px; padding: 8px 4px; }
.step-panel h3 { margin: 0 0 8px; color: #1f2d3d; }
.step-desc { margin: 0 0 24px; color: #909399; font-size: 13px; }
.step-panel .el-alert { margin-top: 22px; }
.step-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; padding-top: 18px; border-top: 1px solid #ebeef5; }
.template-empty { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; color: #909399; }
.job-line { margin: 8px 0; }
.err-cat { color: #e6a23c; margin-right: 4px; }
</style>

<template>
  <div class="settings">
    <h2>账户设置</h2>
    <p class="sub">配置通知偏好与界面语言</p>

    <div class="card">
      <h3>通知偏好</h3>
      <label class="switch">
        <input type="checkbox" v-model="settings.email_notifications" />
        邮件通知（账户异常 / 风险告警）
      </label>
      <label class="switch">
        <input type="checkbox" v-model="settings.daily_report" />
        每日数据报告
      </label>
      <label class="switch">
        <input type="checkbox" v-model="settings.risk_alert" />
        风险实时告警
      </label>

      <div class="field">
        <label>语言</label>
        <select v-model="settings.language" class="input">
          <option value="zh-CN">简体中文</option>
          <option value="en">English</option>
        </select>
      </div>

      <div class="actions">
        <button class="btn btn-primary" :disabled="saving" @click="save">保存设置</button>
        <span v-if="saved" class="ok">已保存 ✓</span>
      </div>
    </div>

    <div class="card">
      <h3>账户信息</h3>
      <div class="info-row"><span>用户名</span><b>{{ user?.username }}</b></div>
      <div class="info-row"><span>邮箱</span><b>{{ user?.email }}</b></div>
      <div class="info-row"><span>角色</span><b>{{ roleLabel(user?.role) }}</b></div>
    </div>

    <div v-if="userStore.isAdmin" class="card audience-policy-card">
      <h3>Meta 受众资产与强制排除</h3>
      <p class="hint">管理员可按广告账户同步 Custom Audience，并锁定法律/运营要求的排除受众。投放时系统会自动合并这些排除项。</p>
      <div class="field">
        <label>广告账户</label>
        <select v-model="selectedAccountId" class="input" @change="loadAudiences">
          <option value="">请选择广告账户</option>
          <option v-for="account in accounts" :key="account.id" :value="account.id">{{ account.account_name || account.account_id }}（{{ account.account_id }}）</option>
        </select>
      </div>
      <div class="audience-actions">
        <button class="btn" :disabled="!selectedAccountId || syncingAudiences" @click="syncAudiences">{{ syncingAudiences ? '同步中…' : '从 Meta 同步受众' }}</button>
        <span class="hint">只同步受众元数据，不读取受众成员</span>
        <span v-if="syncTaskState" class="sync-state">任务：{{ syncTaskState }}</span>
      </div>
      <div v-if="selectedAccountId" class="policy-fields">
        <div class="field">
          <label>策略原因</label>
          <select v-model="policyReasonCode" class="input">
            <option value="LEGAL">法律 / 合规</option>
            <option value="PRIVACY">隐私 / 用户请求</option>
            <option value="OPERATIONS">运营策略</option>
            <option value="BRAND_SAFETY">品牌安全</option>
            <option value="LEGACY_MIGRATION">历史策略待确认</option>
          </select>
        </div>
        <div class="field">
          <label>策略备注（内部）</label>
          <input v-model="policyReasonNote" class="input" maxlength="2000" placeholder="记录依据或运营说明，不会发送给 Meta" />
        </div>
        <div class="policy-dates">
          <div class="field">
            <label>生效日期</label>
            <input v-model="policyEffectiveFrom" class="input" type="date" />
          </div>
          <div class="field">
            <label>失效日期</label>
            <input v-model="policyEffectiveUntil" class="input" type="date" />
          </div>
        </div>
      </div>
      <div v-if="selectedAccountId && audiences.length" class="audience-list">
        <label v-for="audience in audiences" :key="audience.id" class="audience-row">
          <input v-model="requiredAudienceIds" type="checkbox" :value="audience.meta_audience_id" />
          <span>{{ audience.name }}</span>
          <small>{{ audience.subtype || 'CUSTOM' }} · {{ audience.meta_audience_id }} · 最近同步 {{ formatDate(audience.last_synced_at) }} · {{ audienceStatus(audience) }}</small>
        </label>
        <button class="btn btn-primary" :disabled="savingAudiencePolicy" @click="saveAudiencePolicy">保存强制排除策略</button>
      </div>
      <div v-else-if="selectedAccountId" class="hint audience-empty">暂无已同步受众，请先点击“从 Meta 同步受众”。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useUserStore } from '../../stores/userStore'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { metaAudiencesApi, type MetaAudienceAsset } from '@/api/metaAudiences'

const userStore = useUserStore()
const user = userStore.user

const settings = ref({
  email_notifications: true,
  daily_report: true,
  risk_alert: true,
  language: 'zh-CN',
})
const saving = ref(false)
const saved = ref(false)
const accounts = ref<AdAccountItem[]>([])
const selectedAccountId = ref('')
const audiences = ref<MetaAudienceAsset[]>([])
const requiredAudienceIds = ref<string[]>([])
const syncingAudiences = ref(false)
const savingAudiencePolicy = ref(false)
const syncTaskState = ref('')
const policyReasonCode = ref('LEGACY_MIGRATION')
const policyReasonNote = ref('')
const policyEffectiveFrom = ref('')
const policyEffectiveUntil = ref('')

function roleLabel(r?: string) {
  return { admin: '管理员', manager: '经理', user: '普通用户' }[r || ''] || r || '-'
}

onMounted(() => {
  const s = (userStore.user?.settings as Record<string, any>) || {}
  settings.value = { ...settings.value, ...s }
  if (userStore.isAdmin) void loadAccounts()
})

async function loadAccounts() {
  try {
    const { data } = await accountApi.list({ page: 1, page_size: 100 })
    accounts.value = Array.isArray(data) ? data : (data?.items || [])
  } catch { accounts.value = [] }
}

async function loadAudiences() {
  audiences.value = []
  requiredAudienceIds.value = []
  if (!selectedAccountId.value) return
  try {
    const { data } = await metaAudiencesApi.list(selectedAccountId.value)
    audiences.value = data || []
    requiredAudienceIds.value = audiences.value.filter(item => item.is_required_exclusion).map(item => item.meta_audience_id)
    const activePolicy = audiences.value.find(item => item.is_required_exclusion && item.policy_reason_code)
    policyReasonCode.value = activePolicy?.policy_reason_code || 'LEGACY_MIGRATION'
    policyReasonNote.value = activePolicy?.policy_reason_note || ''
    policyEffectiveFrom.value = activePolicy?.policy_effective_from?.slice(0, 10) || ''
    policyEffectiveUntil.value = activePolicy?.policy_effective_until?.slice(0, 10) || ''
  } catch { audiences.value = [] }
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '未同步'
}

function audienceStatus(audience: MetaAudienceAsset) {
  const status = String(audience.sync_status || '').toUpperCase()
  if (status === 'MISSING') return 'Meta 未返回，发布将阻断'
  if (['DELETED', 'EXPIRED', 'UNAVAILABLE'].includes(status)) return '已失效，发布将阻断'
  return status === 'ACTIVE' ? '可用' : (status || '待同步')
}

async function waitForAudienceSync(taskId: string) {
  for (let round = 0; round < 45; round += 1) {
    const { data } = await metaAudiencesApi.taskStatus(taskId)
    syncTaskState.value = data.state
    if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(data.state)) {
      if (data.state !== 'SUCCESS' || String(data.result?.status || '').toUpperCase() === 'FAILED') {
        throw new Error(data.error || 'Meta 受众同步任务失败')
      }
      return
    }
    await new Promise(resolve => setTimeout(resolve, 2000))
  }
  throw new Error('同步任务等待超时，请到任务中心查看')
}

async function syncAudiences() {
  if (!selectedAccountId.value) return
  syncingAudiences.value = true
  syncTaskState.value = 'PENDING'
  try {
    const { data } = await metaAudiencesApi.sync(selectedAccountId.value)
    await waitForAudienceSync(data.task_id)
    await loadAudiences()
    alert('Meta 受众同步完成')
  } catch (e: any) {
    alert('受众同步失败：' + (e.response?.data?.detail || e.message))
  } finally { syncingAudiences.value = false }
}

async function saveAudiencePolicy() {
  if (!selectedAccountId.value) return
  savingAudiencePolicy.value = true
  try {
    await metaAudiencesApi.setRequiredExclusions(selectedAccountId.value, {
      audience_ids: requiredAudienceIds.value,
      reason_code: policyReasonCode.value,
      reason_note: policyReasonNote.value || undefined,
      effective_from: policyEffectiveFrom.value ? `${policyEffectiveFrom.value}T00:00:00` : undefined,
      effective_until: policyEffectiveUntil.value ? `${policyEffectiveUntil.value}T23:59:59` : undefined,
    })
    await loadAudiences()
    alert('强制排除策略已保存')
  } catch (e: any) {
    alert('保存失败：' + (e.response?.data?.detail || e.message))
  } finally { savingAudiencePolicy.value = false }
}

async function save() {
  saving.value = true
  saved.value = false
  try {
    await userStore.updateSettings({ ...settings.value })
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } catch (e: any) {
    alert('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.settings {
  padding: 24px;
  max-width: 640px;
  color: #1f2937;
}
.settings h2 {
  margin: 0;
  font-size: 20px;
}
.sub {
  color: #6b7280;
  font-size: 13px;
  margin-top: 4px;
}
.card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  margin-top: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.card h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.switch {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  font-size: 14px;
  cursor: pointer;
}
.field {
  margin-top: 8px;
}
.field label {
  display: block;
  font-size: 13px;
  color: #4b5563;
  margin-bottom: 4px;
}
.input {
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  min-width: 200px;
}
.input:focus {
  border-color: #4f46e5;
}
.actions {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn {
  padding: 8px 16px;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.btn-primary {
  background: #4f46e5;
  color: #fff;
  border-color: #4f46e5;
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.ok {
  color: #15803d;
  font-size: 13px;
}
.hint { color: #6b7280; font-size: 12px; line-height: 1.5; }
.audience-policy-card { max-width: 760px; }
.audience-actions { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.sync-state { color: #409eff; font-size: 12px; }
.audience-list { margin-top: 14px; border-top: 1px solid #f3f4f6; }
.audience-row { display: flex; align-items: center; gap: 8px; padding: 10px 0; border-bottom: 1px solid #f3f4f6; font-size: 13px; }
.audience-row small { margin-left: auto; color: #9ca3af; }
.audience-empty { margin-top: 16px; }
.info-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f3f4f6;
  font-size: 14px;
}
.info-row:last-child {
  border-bottom: none;
}
.info-row span {
  color: #6b7280;
}
</style>

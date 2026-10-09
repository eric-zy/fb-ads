<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">运维中心</h2>
        <p class="page-subtitle">系统依赖、同步任务、投放告警、投放操作和操作审计</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert v-if="connectorMode" type="info" :closable="false" show-icon style="margin-bottom: 12px">
      当前使用海外 Connector，凭据健康由 Connector 托管；本页展示国内同步任务、投放告警、投放操作和操作审计。
    </el-alert>

    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="系统健康" name="health">
        <template v-if="health">
          <div class="health-summary">
            <el-tag :type="health.status === 'ready' ? 'success' : 'warning'" effect="dark">
              {{ health.status === 'ready' ? '运行正常' : '存在异常' }}
            </el-tag>
            <span class="health-time">检查时间：{{ formatDateTimeCell(null, null, health.checked_at) }}</span>
          </div>
          <el-row :gutter="12">
            <el-col v-for="(status, name) in health.checks" :key="name" :xs="24" :sm="12" :lg="6">
              <el-card shadow="never" class="health-card">
                <div class="health-name">{{ healthLabel(String(name)) }}</div>
                <el-tag :type="status === 'ok' ? 'success' : status === 'not_required' ? 'info' : 'danger'">
                  {{ healthStatusLabel(status) }}
                </el-tag>
                <div v-if="name === 'celery_workers'" class="health-detail">
                  {{ health.celery_workers.join('、') || '未发现在线 Worker' }}
                </div>
              </el-card>
            </el-col>
          </el-row>
          <el-card v-if="connectorMode" shadow="never" class="connector-health">
            <template #header>海外 Connector</template>
            <div class="health-summary">
              <el-tag :type="health.connector.status === 'ok' ? 'success' : 'danger'">
                {{ healthStatusLabel(health.connector.status) }}
              </el-tag>
              <span v-for="(status, name) in health.connector.checks" :key="name" class="health-detail">
                {{ healthLabel(String(name)) }}：{{ healthStatusLabel(status) }}
              </span>
            </div>
          </el-card>
        </template>
        <el-empty v-else-if="!loading" description="暂无健康检查结果" />
      </el-tab-pane>
      <el-tab-pane label="同步任务" name="tasks">
        <el-table :data="tasks" stripe>
          <el-table-column prop="sync_type" label="类型" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="结果"><template #default="{ row }">{{ row.success_count }} / {{ row.total_count }}</template></el-table-column>
          <el-table-column prop="error_message" label="错误" show-overflow-tooltip />
          <el-table-column prop="created_at" label="创建时间" :formatter="formatDateTimeCell" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="凭据健康" name="credentials">
        <el-table :data="credentials" stripe>
          <el-table-column prop="meta_account_id" label="BM" />
          <el-table-column prop="token_type" label="类型" />
          <el-table-column prop="health" label="健康状态" />
          <el-table-column prop="expires_at" label="过期时间" :formatter="formatDateTimeCell" />
          <el-table-column prop="last_error" label="错误" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="投放告警" name="alerts">
        <el-table :data="alerts" stripe>
          <el-table-column prop="title" label="告警" />
          <el-table-column prop="alert_type" label="类型" />
          <el-table-column prop="ad_account_id" label="广告账户" />
          <el-table-column prop="message" label="详情" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间" :formatter="formatDateTimeCell" />
          <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="resolveAlert(row as TableRow<typeof alerts>)">处理</el-button></template></el-table-column>
        </el-table>
        <el-empty v-if="!alerts.length" description="暂无未处理投放告警" />
      </el-tab-pane>

      <el-tab-pane label="投放操作" name="delivery-actions">
        <div class="filters"><el-select v-model="actionStatus" placeholder="操作状态" clearable @change="load"><el-option label="执行中" value="RUNNING" /><el-option label="成功" value="SUCCESS" /><el-option label="失败" value="FAILED" /></el-select><el-button @click="load">筛选</el-button></div>
        <el-table :data="deliveryActions" stripe>
          <el-table-column prop="action" label="动作" />
          <el-table-column prop="object_type" label="对象" />
          <el-table-column prop="object_id" label="对象 ID" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" />
          <el-table-column prop="desired_status" label="目标状态" />
          <el-table-column prop="error_message" label="错误" show-overflow-tooltip />
          <el-table-column prop="created_at" label="提交时间" :formatter="formatDateTimeCell" />
        </el-table>
        <el-empty v-if="!deliveryActions.length" description="暂无投放操作记录" />
      </el-tab-pane>

      <el-tab-pane label="操作审计" name="audit">
        <div class="filters"><el-input v-model="auditResourceId" clearable placeholder="资源 ID（可选）" /><el-input v-model="auditAction" clearable placeholder="动作（可选）" /><el-select v-model="auditResourceType" clearable placeholder="资源类型"><el-option label="素材" value="creative_asset" /><el-option label="素材分组" value="creative_asset_group" /></el-select><el-button @click="load">筛选</el-button></div>
        <el-table :data="audits" stripe>
          <el-table-column prop="action" label="操作" />
          <el-table-column prop="resource_type" label="资源类型" />
          <el-table-column prop="resource_id" label="资源 ID" />
          <el-table-column prop="user_id" label="操作人" />
          <el-table-column prop="created_at" label="时间" :formatter="formatDateTimeCell" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { formatDateTimeCell } from '@/utils/dateTime'
import { onMounted, ref } from 'vue'
import { operationsApi, credentialApi } from '@/api/admin'
import { campaignsApi, type DeliveryAction, type SyncAlert } from '@/api/campaigns'
import { ElMessage, ElMessageBox } from 'element-plus'

const tab = ref('health')
const loading = ref(false)
const health = ref<{ status: string; checked_at: string; checks: Record<string, string>; celery_workers: string[]; connector: { status: string; checks: Record<string, string> } } | null>(null)
const tasks = ref<any[]>([])
const credentials = ref<any[]>([])
const audits = ref<any[]>([])
const alerts = ref<SyncAlert[]>([])
const deliveryActions = ref<DeliveryAction[]>([])
const actionStatus = ref('')
const connectorMode = ref(false)
const auditResourceId = ref('')
const auditAction = ref('')
const auditResourceType = ref('')

async function load() {
  loading.value = true
  try {
    connectorMode.value = (await credentialApi.accessMode()).data?.access_mode === 'connector'
    if (tab.value === 'health') health.value = (await operationsApi.health()).data
    if (tab.value === 'tasks') tasks.value = (await operationsApi.syncTasks()).data
    if (tab.value === 'credentials') credentials.value = (await operationsApi.credentialHealth()).data
    if (tab.value === 'audit') audits.value = (await operationsApi.auditLogs({ resource_id: auditResourceId.value || undefined, action: auditAction.value || undefined, resource_type: auditResourceType.value || undefined })).data
    if (tab.value === 'alerts') alerts.value = (await campaignsApi.alerts(100)).data
    if (tab.value === 'delivery-actions') deliveryActions.value = (await campaignsApi.deliveryActions(100, actionStatus.value || undefined)).data
  } catch {
    if (tab.value === 'health') health.value = null
    ElMessage.error('运维数据加载失败，请检查服务状态后重试')
  } finally {
    loading.value = false
  }
}

function healthLabel(name: string) {
  return ({ database: '数据库', redis: 'Redis', celery_workers: 'Celery Worker', connector: 'Connector', oauth_receipt_signing: 'OAuth 回执签名', service_auth: '服务签名与鉴权通信' } as Record<string, string>)[name] || name
}
function healthStatusLabel(status: string) {
  return ({ ok: '正常', ready: '正常', unavailable: '不可用', degraded: '异常', not_required: '不需要' } as Record<string, string>)[status] || status
}

async function resolveAlert(row: SyncAlert) {
  try {
    await ElMessageBox.confirm(`确认将告警「${row.title}」标记为已处理？`, '确认处理', { type: 'warning' })
    await campaignsApi.resolveAlert(row.id)
    ElMessage.success('告警已处理')
    await load()
  } catch {}
}

onMounted(load)
</script>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.filters .el-select {
  width: 160px;
}
.health-summary { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.health-time, .health-detail { color: #718096; font-size: 13px; }
.health-card { margin-bottom: 12px; min-height: 104px; }
.health-name { margin-bottom: 12px; font-weight: 600; }
.connector-health { margin-top: 8px; }
</style>

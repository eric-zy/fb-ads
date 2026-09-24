<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">运维中心</h2>
        <p class="page-subtitle">同步任务、投放告警、投放操作和操作审计</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-alert v-if="connectorMode" type="info" :closable="false" show-icon style="margin-bottom: 12px">
      当前使用海外 Connector，凭据健康由 Connector 托管；本页展示国内同步任务、投放告警、投放操作和操作审计。
    </el-alert>

    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane label="同步任务" name="tasks">
        <el-table :data="tasks" stripe>
          <el-table-column prop="sync_type" label="类型" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="结果"><template #default="{ row }">{{ row.success_count }} / {{ row.total_count }}</template></el-table-column>
          <el-table-column prop="error_message" label="错误" show-overflow-tooltip />
          <el-table-column prop="created_at" label="创建时间" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane v-if="!connectorMode" label="凭据健康" name="credentials">
        <el-table :data="credentials" stripe>
          <el-table-column prop="meta_account_id" label="BM" />
          <el-table-column prop="token_type" label="类型" />
          <el-table-column prop="health" label="健康状态" />
          <el-table-column prop="expires_at" label="过期时间" />
          <el-table-column prop="last_error" label="错误" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="投放告警" name="alerts">
        <el-table :data="alerts" stripe>
          <el-table-column prop="title" label="告警" />
          <el-table-column prop="alert_type" label="类型" />
          <el-table-column prop="ad_account_id" label="广告账户" />
          <el-table-column prop="message" label="详情" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间" />
          <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click="resolveAlert(row)">处理</el-button></template></el-table-column>
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
          <el-table-column prop="created_at" label="提交时间" />
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
          <el-table-column prop="created_at" label="时间" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { operationsApi, credentialApi } from '@/api/admin'
import { campaignsApi, type DeliveryAction, type SyncAlert } from '@/api/campaigns'
import { ElMessage, ElMessageBox } from 'element-plus'

const tab = ref('tasks')
const loading = ref(false)
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
    if (tab.value === 'credentials' && connectorMode.value) tab.value = 'tasks'
    if (tab.value === 'tasks') tasks.value = (await operationsApi.syncTasks()).data
    if (tab.value === 'credentials') credentials.value = (await operationsApi.credentialHealth()).data
    if (tab.value === 'audit') audits.value = (await operationsApi.auditLogs({ resource_id: auditResourceId.value || undefined, action: auditAction.value || undefined, resource_type: auditResourceType.value || undefined })).data
    if (tab.value === 'alerts') alerts.value = (await campaignsApi.alerts(100)).data
    if (tab.value === 'delivery-actions') deliveryActions.value = (await campaignsApi.deliveryActions(100, actionStatus.value || undefined)).data
  } finally {
    loading.value = false
  }
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
</style>

<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">Meta 授权</h2>
        <p class="page-subtitle">一次授权，统一同步 BM、广告账户和 Facebook Page</p>
      </div>
      <div class="head-actions">
        <el-button type="primary" @click="authorize">Meta OAuth 授权</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="connectorMode" type="info" :closable="false" show-icon class="mb12">
      当前使用海外 Connector OAuth。本页展示海外授权的状态、权限和有效期，可同步资产或重新授权。
      使用 Instagram 身份时，还需授权专业账户及其关联 Page；权限缺失时，请管理员更新 Meta 应用的授权配置后重新授权。
    </el-alert>
    <el-alert v-else type="info" :closable="false" show-icon class="mb12">
      连接页只负责授权和连接健康检查；BM、广告账户和投放权限请在对应资产页面管理。Access Token 仅在服务端加密保存。
    </el-alert>

    <el-card shadow="never" class="card-shadow">
      <el-table :data="connections" v-loading="loading" stripe>
        <el-table-column label="Meta 用户" min-width="180">
          <template #default="{ row }">{{ row.meta_user_id }}</template>
        </el-table-column>
        <el-table-column label="授权状态" width="120">
          <template #default="{ row }">
            <el-tag :type="connectionType(row.status)">{{ connectionLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="business_count" label="BM" width="90" />
        <el-table-column prop="account_count" label="广告账户" width="110" />
        <el-table-column prop="page_count" label="Page" width="90" />
        <el-table-column label="权限" min-width="240">
          <template #default="{ row }">{{ row.scopes?.join(', ') || '-' }}</template>
        </el-table-column>
        <el-table-column label="最近同步" width="180">
          <template #default="{ row }">{{ formatTime(row.last_synced_at) }}</template>
        </el-table-column>
        <el-table-column label="有效期" width="150">
          <template #default="{ row }">{{ formatTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="syncingId === row.id" @click="sync(row as TableRow<typeof connections>)">立即同步</el-button>
            <el-button link type="warning" @click="reauthorize">重新授权</el-button>
          </template>
        </el-table-column>
        <el-table-column label="最近错误" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.last_error || '-' }}</template>
        </el-table-column>
        <template #empty><el-empty description="暂无 Meta 授权，请先完成 OAuth" /></template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { metaConnectionsApi, type MetaConnection } from '@/api/metaConnections'
import { credentialApi } from '@/api/admin'

const connections = ref<MetaConnection[]>([])
const loading = ref(false)
const syncingId = ref<string | null>(null)
const connectorMode = ref(false)
const formatTime = (value?: string | null) => value ? new Date(value).toLocaleString() : '-'
const connectionLabel = (status: string) => ({ ACTIVE: '正常', EXPIRED: '已过期', REVOKED: '已撤销', DISABLED: '已停用', EXPIRING: '即将过期', PERMISSION_MISSING: '缺少权限', UNAVAILABLE: '暂不可用', MISSING: '未找到' } as Record<string, string>)[status] || status
const connectionType = (status: string): 'success' | 'danger' | 'warning' | 'info' => status === 'ACTIVE' ? 'success' : (status === 'EXPIRED' || status === 'REVOKED' ? 'danger' : 'warning')

async function load() {
  loading.value = true
  try {
    const mode = await credentialApi.accessMode()
    connectorMode.value = mode.data?.access_mode === 'connector'
    connections.value = (await metaConnectionsApi.list()).data
  } finally { loading.value = false }
}

async function authorize() {
  const { data } = await credentialApi.oauthAuthorizeFirst()
  window.location.assign(data.authorization_url)
}
async function reauthorize() { await authorize() }

async function sync(row: MetaConnection) {
  syncingId.value = row.id
  try { await metaConnectionsApi.sync(row.id); ElMessage.success('同步任务已提交') } finally { syncingId.value = null }
}

onMounted(load)
</script>

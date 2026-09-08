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

    <el-alert type="info" :closable="false" show-icon class="mb12">
      Access Token 由系统加密管理，不在页面展示。投放时自动使用对应授权连接。
    </el-alert>

    <el-card shadow="never" class="card-shadow">
      <el-table :data="connections" v-loading="loading" stripe>
        <el-table-column label="Meta 用户" min-width="180">
          <template #default="{ row }">{{ row.meta_user_id }}</template>
        </el-table-column>
        <el-table-column label="授权状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'danger'">{{ row.status }}</el-tag>
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
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="syncingId === row.id" @click="sync(row)">立即同步</el-button>
          </template>
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
const formatTime = (value?: string | null) => value ? new Date(value).toLocaleString() : '-'

async function load() {
  loading.value = true
  try { connections.value = (await metaConnectionsApi.list()).data } finally { loading.value = false }
}

async function authorize() {
  const { data } = await credentialApi.oauthAuthorizeFirst()
  window.location.assign(data.authorization_url)
}

async function sync(row: MetaConnection) {
  syncingId.value = row.id
  try { await metaConnectionsApi.sync(row.id); ElMessage.success('同步任务已提交') } finally { syncingId.value = null }
}

onMounted(load)
</script>

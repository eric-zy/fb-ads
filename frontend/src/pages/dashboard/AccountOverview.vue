<template>
  <div class="page"><div class="head"><div><div class="eyebrow">数据中心</div><h2>广告账户消耗总览</h2><p>按账户和币种查看消耗，数据不会跨币种直接相加。</p></div><el-button v-if="userStore.isAdmin" type="primary" :loading="syncing" @click="sync">回补最近 3 天</el-button></div>
    <el-card shadow="never" class="filters"><el-date-picker v-model="range" type="daterange" single-panel value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="load"/><el-button @click="load">刷新</el-button></el-card>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <el-card v-for="total in currencyTotals" :key="total.currency" shadow="never" class="currency"><template #header>{{ total.currency }} 汇总</template><span>消耗 {{ money(total.spend) }}</span><span>展示 {{ total.impressions }}</span><span>点击 {{ total.clicks }}</span><span>转化 {{ total.conversions }}</span><span>CPA {{ money(total.cpa) }}</span></el-card>
    <el-card shadow="never"><template #header>账户消耗排名</template><el-table v-loading="loading" :data="items" stripe><el-table-column prop="account_name" label="广告账户" min-width="180"/><el-table-column prop="meta_account_id" label="Meta ID"/><el-table-column prop="currency" label="币种"/><el-table-column prop="spend" label="消耗"/><el-table-column prop="impressions" label="展示"/><el-table-column prop="clicks" label="点击"/><el-table-column prop="conversions" label="转化"/><el-table-column prop="sync_status" label="同步状态"><template #default="scope"><el-tag :type="scope.row.sync_status === 'FRESH' ? 'success' : scope.row.sync_status === 'STALE' ? 'warning' : 'info'">{{ scope.row.sync_status === 'FRESH' ? '正常' : scope.row.sync_status === 'STALE' ? '延迟' : '未同步' }}</el-tag></template></el-table-column><el-table-column prop="latest_synced_at" label="最后同步"/></el-table></el-card>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { reportsApi } from '@/api/reports'
import { useUserStore } from '@/stores/userStore'
function formatDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const today = new Date()
const defaultStart = new Date(today)
defaultStart.setDate(today.getDate() - 2)
const range = ref<string[]>([formatDate(defaultStart), formatDate(today)]), items = ref<any[]>([]), currencyTotals = ref<any[]>([]), loading = ref(false), syncing = ref(false), error = ref('')
const userStore = useUserStore()
const params = computed(() => range.value?.length === 2 ? { start_date: range.value[0], end_date: range.value[1] } : undefined)
const money = (value: number) => Number(value || 0).toFixed(2)
async function load() { loading.value = true; error.value = ''; try { const { data } = await reportsApi.accountOverview(params.value); items.value = data.items || []; currencyTotals.value = data.currency_totals || [] } catch { error.value = '消耗数据加载失败，请检查同步状态' } finally { loading.value = false } }
let syncTimer: ReturnType<typeof setTimeout> | undefined
async function waitForSync(taskIds: string[], round = 0): Promise<void> {
  const statuses = await Promise.all(taskIds.map(id => reportsApi.taskStatus(id).then(({ data }) => data).catch(() => ({ state: 'UNKNOWN' }))))
  const finished = statuses.filter(item => ['SUCCESS', 'FAILURE', 'REVOKED'].includes(item.state))
  if (finished.length === statuses.length || round >= 60) {
    if (finished.some(item => item.state !== 'SUCCESS')) error.value = '同步任务部分失败，请查看任务中心或重试'
    await load()
    return
  }
  await new Promise<void>(resolve => { syncTimer = setTimeout(resolve, 2000) })
  return waitForSync(taskIds, round + 1)
}
async function sync() { syncing.value = true; error.value = ''; try { const { data } = await reportsApi.sync({ days: 3 }); if (data.task_ids?.length) await waitForSync(data.task_ids); else await load() } catch { error.value = '回补任务提交失败' } finally { syncing.value = false } }
onMounted(load)
onUnmounted(() => { if (syncTimer) clearTimeout(syncTimer) })
</script>
<style scoped>.page{padding:4px}.head{display:flex;justify-content:space-between;margin-bottom:18px}.eyebrow{color:#829ab1;font-size:12px}.head h2{margin:6px 0;color:#102a43}.head p{margin:0;color:#627d98;font-size:13px}.filters{display:flex;gap:12px;margin-bottom:16px}.currency{display:inline-block;width:calc(33.333% - 12px);margin:0 12px 16px 0}.currency span{display:inline-block;margin-right:18px;color:#486581}@media(max-width:1000px){.currency{width:100%}}</style>

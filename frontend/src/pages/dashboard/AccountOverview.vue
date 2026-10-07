<template>
  <div class="page"><div class="head"><div><div class="eyebrow">数据中心</div><h2>广告账户消耗总览</h2><p>按账户和币种查看消耗，数据不会跨币种直接相加。</p></div><el-button v-if="userStore.isAdmin" type="primary" :disabled="!rangeValid" :loading="syncing" @click="sync">同步所选日期</el-button></div>
    <el-card shadow="never" class="filters"><DateRangeFields v-model="range" :disabled="syncing" @validity-change="rangeValid = $event" @change="load"/><el-button :disabled="!rangeValid" @click="load">刷新</el-button></el-card>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <el-alert v-if="incompleteCount" class="quality-note" :title="`${incompleteCount} 个账户的所选日期报表尚未完整同步，当前汇总可能不完整；显示 0 不代表实际消耗为 0。`" type="warning" :closable="false" show-icon/>
    <el-card v-for="total in currencyTotals" :key="total.currency" shadow="never" class="currency"><template #header>{{ total.currency }} 汇总</template><span>消耗 {{ money(total.spend) }}</span><span>展示 {{ total.impressions }}</span><span>点击 {{ total.clicks }}</span><span>转化 {{ total.conversions }}</span><span>CPA {{ money(total.cpa) }}</span></el-card>
    <el-card shadow="never"><template #header>账户消耗排名</template><el-table v-loading="loading" :data="items" stripe><el-table-column prop="account_name" label="广告账户" min-width="180"/><el-table-column prop="meta_account_id" label="Meta ID"/><el-table-column prop="currency" label="币种"/><el-table-column prop="spend" label="消耗"/><el-table-column prop="impressions" label="展示"/><el-table-column prop="clicks" label="点击"/><el-table-column prop="conversions" label="转化"/><el-table-column prop="sync_status" label="同步状态"><template #default="scope"><el-tooltip v-if="scope.row.sync_error" :content="scope.row.sync_error" placement="top"><el-tag :type="syncType(scope.row.sync_status)">{{ syncLabel(scope.row.sync_status) }}</el-tag></el-tooltip><el-tag v-else :type="syncType(scope.row.sync_status)">{{ syncLabel(scope.row.sync_status) }}</el-tag></template></el-table-column><el-table-column prop="latest_synced_at" label="最后同步"/></el-table></el-card>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import DateRangeFields from '@/components/DateRangeFields.vue'
import { reportsApi } from '@/api/reports'
import { waitForReportSync } from '@/utils/reportSync'
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
const rangeValid = ref(true)
const params = computed(() => range.value?.length === 2 ? { start_date: range.value[0], end_date: range.value[1] } : undefined)
const incompleteCount = computed(() => items.value.filter(item => item.data_quality?.complete === false || ['NEVER', 'INCOMPLETE'].includes(item.sync_status)).length)
const money = (value: number | null | undefined) => value == null ? '—' : Number(value).toFixed(2)
const syncLabel = (status: string) => ({ FRESH: '正常', STALE: '延迟', FAILED: '失败', SYNCING: '同步中', PENDING: '待同步', NEVER: '未同步', INCOMPLETE: '日期未补全' } as Record<string, string>)[status] || status || '未同步'
const syncType = (status: string): 'success' | 'warning' | 'danger' | 'info' => status === 'FRESH' ? 'success' : ['STALE', 'SYNCING'].includes(status) ? 'warning' : status === 'FAILED' ? 'danger' : 'info'
async function load() { if (!rangeValid.value) return; loading.value = true; error.value = ''; try { const { data } = await reportsApi.accountOverview(params.value); items.value = data.items || []; currencyTotals.value = data.currency_totals || [] } catch { error.value = '消耗数据加载失败，请检查同步状态' } finally { loading.value = false } }
let reportController: AbortController | undefined
async function sync() {
  if (!rangeValid.value) return
  syncing.value = true; error.value = ''
  reportController = new AbortController()
  let syncError = ''
  try {
    const { data } = await reportsApi.sync(params.value || { days: 3 })
    await waitForReportSync(data.task_ids || [], reportController.signal)
  } catch (err) {
    if (!reportController.signal.aborted) syncError = err instanceof Error ? err.message : '回补任务提交失败'
  } finally {
    if (!reportController.signal.aborted) {
      await load()
      if (syncError) error.value = syncError
    }
    syncing.value = false
  }
}
onMounted(load)
onUnmounted(() => reportController?.abort())
</script>
<style scoped>.page{padding:4px}.head{display:flex;justify-content:space-between;margin-bottom:18px}.eyebrow{color:#829ab1;font-size:12px}.head h2{margin:6px 0;color:#102a43}.head p{margin:0;color:#627d98;font-size:13px}.filters{margin-bottom:16px}.filters :deep(.el-card__body){display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px}.quality-note{margin-bottom:16px}.currency{display:inline-block;width:calc(33.333% - 12px);margin:0 12px 16px 0}.currency span{display:inline-block;margin-right:18px;color:#486581}@media(max-width:1000px){.currency{width:100%}}</style>

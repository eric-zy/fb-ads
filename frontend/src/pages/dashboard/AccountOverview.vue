<template>
  <div class="page"><div class="head"><div><div class="eyebrow">数据中心</div><h2>广告账户消耗总览</h2><p>按账户和币种查看消耗，数据不会跨币种直接相加。</p></div><el-button v-if="userStore.isAdmin" type="primary" :loading="syncing" @click="sync">回补最近 3 天</el-button></div>
    <el-card shadow="never" class="filters"><el-date-picker v-model="range" type="daterange" single-panel value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="load"/><el-button @click="load">刷新</el-button></el-card>
    <el-alert v-if="error" :title="error" type="warning" :closable="false"/>
    <el-card v-for="total in currencyTotals" :key="total.currency" shadow="never" class="currency"><template #header>{{ total.currency }} 汇总</template><span>消耗 {{ money(total.spend) }}</span><span>展示 {{ total.impressions }}</span><span>点击 {{ total.clicks }}</span><span>转化 {{ total.conversions }}</span><span>CPA {{ money(total.cpa) }}</span></el-card>
    <el-card shadow="never"><template #header>账户消耗排名</template><el-table v-loading="loading" :data="items" stripe><el-table-column prop="account_name" label="广告账户" min-width="180"/><el-table-column prop="meta_account_id" label="Meta ID"/><el-table-column prop="currency" label="币种"/><el-table-column prop="spend" label="消耗"/><el-table-column prop="impressions" label="展示"/><el-table-column prop="clicks" label="点击"/><el-table-column prop="conversions" label="转化"/><el-table-column prop="sync_status" label="同步状态"><template #default="scope"><el-tag :type="scope.row.sync_status === 'FRESH' ? 'success' : scope.row.sync_status === 'STALE' ? 'warning' : 'info'">{{ scope.row.sync_status === 'FRESH' ? '正常' : scope.row.sync_status === 'STALE' ? '延迟' : '未同步' }}</el-tag></template></el-table-column><el-table-column prop="latest_synced_at" label="最后同步"/></el-table></el-card>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { reportsApi } from '@/api/reports'
import { useUserStore } from '@/stores/userStore'
const range = ref<string[]>([]), items = ref<any[]>([]), currencyTotals = ref<any[]>([]), loading = ref(false), syncing = ref(false), error = ref('')
const userStore = useUserStore()
const params = computed(() => range.value?.length === 2 ? { start_date: range.value[0], end_date: range.value[1] } : undefined)
const money = (value: number) => Number(value || 0).toFixed(2)
async function load() { loading.value = true; error.value = ''; try { const { data } = await reportsApi.accountOverview(params.value); items.value = data.items || []; currencyTotals.value = data.currency_totals || [] } catch { error.value = '消耗数据加载失败，请检查同步状态' } finally { loading.value = false } }
async function sync() { syncing.value = true; try { await reportsApi.sync({ days: 3 }); await load() } catch { error.value = '回补任务提交失败' } finally { syncing.value = false } }
onMounted(load)
</script>
<style scoped>.page{padding:4px}.head{display:flex;justify-content:space-between;margin-bottom:18px}.eyebrow{color:#829ab1;font-size:12px}.head h2{margin:6px 0;color:#102a43}.head p{margin:0;color:#627d98;font-size:13px}.filters{display:flex;gap:12px;margin-bottom:16px}.currency{display:inline-block;width:calc(33.333% - 12px);margin:0 12px 16px 0}.currency span{display:inline-block;margin-right:18px;color:#486581}@media(max-width:1000px){.currency{width:100%}}</style>

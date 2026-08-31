<template>
  <div class="mgmt">
    <div class="header">
      <div>
        <h2>我的广告账户</h2>
        <p class="sub">以下为分配给你的 Facebook 广告账户</p>
      </div>
    </div>

    <div v-if="loading" class="tip">加载中…</div>
    <div v-else-if="accounts.length === 0" class="tip empty">暂无分配给你的账户</div>

    <div v-else class="grid">
      <div v-for="a in accounts" :key="a.id" class="card" :class="{ disabled: !isActive(a) }">
        <div class="card-top">
          <span class="name">{{ a.account_name || a.account_id }}</span>
          <span class="status" :class="isActive(a) ? 'good' : 'bad'">
            {{ isActive(a) ? '正常' : '已停用' }}
          </span>
        </div>
        <div class="meta">ID: {{ a.account_id }}</div>
        <div class="meta" v-if="a.business_name">BM: {{ a.business_name }}</div>
        <div class="meta" v-if="a.account_status">Meta 状态: {{ a.account_status }}</div>
        <div class="rows">
          <div><span>日限额</span><b>{{ formatMoney(a.daily_spend_limit, a.currency) }}</b></div>
          <div><span>月限额</span><b>{{ formatMoney(a.monthly_spend_limit, a.currency) }}</b></div>
          <div><span>已消费</span><b>{{ formatMoney(a.amount_spent, a.currency) }}</b></div>
          <div><span>余额</span><b>{{ formatMoney(a.balance, a.currency) }}</b></div>
          <div><span>风险</span><b :class="riskClass(a.risk_score)">{{ riskLabel(a.risk_score) }}</b></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { accountApi, type AdAccountItem } from '@/api/admin'
import { formatMoney } from '@/utils/money'

const accounts = ref<AdAccountItem[]>([])
const loading = ref(false)

/** 系统侧是否允许参与投放 */
function isActive(a: AdAccountItem) {
  return a.system_status === 'ACTIVE'
}

function riskClass(score?: number) {
  const s = score ?? 0
  if (s >= 0.7) return 'r-high'
  if (s >= 0.4) return 'r-medium'
  return 'r-low'
}

function riskLabel(score?: number) {
  const s = score ?? 0
  if (s >= 0.7) return '高'
  if (s >= 0.4) return '中'
  return '低'
}

async function load() {
  loading.value = true
  try {
    const { data } = await accountApi.list({ page: 1, page_size: 100 })
    accounts.value = data
  } catch (e: any) {
    // request.ts 已统一提取后端原因（detail 字段）
    alert('加载失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<style scoped>
.mgmt {
  padding: 24px;
  color: #1f2937;
}
.header h2 {
  margin: 0;
  font-size: 20px;
}
.sub {
  color: #6b7280;
  font-size: 13px;
  margin-top: 4px;
}
.tip {
  margin-top: 16px;
  color: #6b7280;
}
.empty {
  padding: 40px;
  text-align: center;
  background: #fff;
  border-radius: 12px;
}
.grid {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.card {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  border-left: 4px solid #22c55e;
}
.card.disabled {
  border-left-color: #ef4444;
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.name {
  font-weight: 600;
}
.status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
}
.status.good {
  background: #dcfce7;
  color: #15803d;
}
.status.bad {
  background: #fee2e2;
  color: #b91c1c;
}
.meta {
  color: #9ca3af;
  font-size: 12px;
  margin-top: 4px;
}
.rows {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.rows > div {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #4b5563;
}
.rows b {
  color: #111827;
}
.r-low {
  color: #15803d;
}
.r-medium {
  color: #a16207;
}
.r-high {
  color: #b91c1c;
}
</style>

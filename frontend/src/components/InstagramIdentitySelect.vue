<template>
  <div class="instagram-selector">
    <div class="selector-row">
      <el-select :model-value="modelValue" clearable filterable :disabled="!pageId" :loading="loading" placeholder="不指定 Instagram 身份" @update:model-value="emit('update:modelValue', $event || '')">
        <el-option v-if="modelValue && !choices.some(item => item.id === modelValue)" :value="modelValue" :label="`${modelValue}（当前不可用，请同步或重新选择）`" disabled />
        <el-option v-for="item in choices" :key="item.id" :value="item.id" :label="`@${item.username} (${item.id})`" />
      </el-select>
      <el-button v-if="canSync" :disabled="!pageId || !accounts.length" :loading="syncing" @click="sync">同步 Instagram 身份</el-button>
    </div>
    <div class="hint">可选；仅展示关联当前 Page 的身份。批量投放时，指定身份须对所有目标账户可用。</div>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" />
    <el-alert v-else-if="modelValue && !choices.some(item => item.id === modelValue)" title="所选 Instagram 身份当前不可用；请同步或清除选择，预检会验证实际授权。" type="warning" :closable="false" />
    <div v-if="unhealthy.length" class="hint">{{ unhealthy.length }} 个账户需要同步身份快照（未同步、过期、授权变更或同步失败）。</div>
    <details v-if="accounts.length" class="hint">
      <summary>查看账户身份状态</summary>
      <div v-for="account in accounts" :key="account.account_pk">{{ account.account_name }}：{{ statusLabel(account.sync_status) }}{{ account.page_error ? `；${account.page_error}` : '' }}</div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { metaInstagramApi, type InstagramAccountHealth, type InstagramIdentity } from '@/api/metaInstagram'
import { useUserStore } from '@/stores/userStore'

const props = defineProps<{ modelValue: string; pageId: string; accountIds?: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const store = useUserStore()
const canSync = computed(() => store.isAdmin || store.hasPermission('meta_asset:manage'))
const items = ref<InstagramIdentity[]>([])
const accounts = ref<InstagramAccountHealth[]>([])
const loading = ref(false)
const syncing = ref(false)
const loadError = ref('')
const key = computed(() => JSON.stringify([props.pageId, [...(props.accountIds || [])].sort()]))
const choices = computed(() => items.value.filter(item => (props.accountIds || []).every(id => item.account_ids.includes(id))))
const unhealthy = computed(() => accounts.value.filter(item => item.sync_status !== 'HEALTHY'))
const statusLabel = (status: InstagramAccountHealth['sync_status']) => ({ HEALTHY: '已同步', NEVER: '未同步', STALE: '快照过期', ERROR: '同步失败', AUTH_CHANGED: '授权已变更' })[status]
let mounted = true
let generation = 0
onBeforeUnmount(() => { mounted = false; generation++ })

async function load() {
  const requestGeneration = ++generation
  items.value = []; accounts.value = []; loadError.value = ''
  if (!props.pageId) { loading.value = false; return }
  loading.value = true
  try {
    const result = await metaInstagramApi.list(props.pageId, props.accountIds)
    if (requestGeneration !== generation) return
    items.value = result.items; accounts.value = result.accounts
  } catch {
    if (requestGeneration === generation) loadError.value = 'Instagram 身份读取失败，请检查 Page 授权后重试'
  } finally {
    if (requestGeneration === generation) loading.value = false
  }
}
watch(key, load, { immediate: true })

async function sync() {
  const originalKey = key.value
  syncing.value = true
  try {
    const taskIds = []
    for (const account of accounts.value.filter(item => !item.page_error)) {
      if (!mounted || key.value !== originalKey) return
      const { data } = await metaInstagramApi.sync(account.account_pk)
      taskIds.push(data.task_id)
    }
    if (!taskIds.length) { ElMessage.warning('当前 Page 没有可同步的授权账户'); return }
    const pending = new Set(taskIds)
    for (let attempt = 0; attempt < 45 && pending.size; attempt++) {
      if (!mounted || key.value !== originalKey) return
      const results = await Promise.all([...pending].map(id => metaInstagramApi.taskStatus(id)))
      for (const { data } of results) {
        if (data.state === 'FAILURE' || data.error) throw new Error(data.error || 'Instagram 身份同步失败')
        if (data.state === 'SUCCESS') pending.delete(data.task_id)
      }
      if (pending.size) await new Promise(resolve => setTimeout(resolve, 2000))
    }
    if (pending.size) throw new Error('Instagram 同步尚未完成，请稍后重新打开选择器查看结果')
    if (mounted && key.value === originalKey) { await load(); ElMessage.success('Instagram 身份同步完成') }
  } catch (error) {
    if (mounted && key.value === originalKey) { await load(); ElMessage.error(error instanceof Error ? error.message : 'Instagram 身份同步失败') }
  } finally { syncing.value = false }
}
</script>

<style scoped>
.instagram-selector { width: 100%; }
.selector-row { display: flex; gap: 8px; }
.selector-row .el-select { flex: 1; min-width: 0; }
.hint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; margin-top: 6px; }
</style>

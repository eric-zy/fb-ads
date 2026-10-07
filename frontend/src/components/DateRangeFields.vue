<template>
  <div class="date-range-fields">
    <div class="date-range-inputs">
      <label class="date-range-field">
        <span>开始日期</span>
        <el-date-picker v-model="start" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD"
          placeholder="选择或输入开始日期" aria-label="开始日期" :clearable="clearable" :disabled="disabled"
          popper-class="date-single-popper" placement="bottom-start" @change="commit" />
      </label>
      <label class="date-range-field">
        <span>结束日期</span>
        <el-date-picker v-model="end" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD"
          placeholder="选择或输入结束日期" aria-label="结束日期" :clearable="clearable" :disabled="disabled"
          popper-class="date-single-popper" placement="bottom-start" @change="commit" />
      </label>
    </div>
    <div class="date-range-shortcuts" aria-label="常用日期范围">
      <el-button v-for="shortcut in shortcuts" :key="shortcut.label" size="small" :disabled="disabled"
        :type="isSelected(shortcut.range) ? 'primary' : undefined" plain @click="apply(shortcut.range)">{{ shortcut.label }}</el-button>
      <el-button v-if="clearable" size="small" :disabled="disabled" @click="clear">重置日期</el-button>
    </div>
    <span v-if="error" class="date-range-error" role="alert">{{ error }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { dateOnly, rangeError, rangeForDays, shiftDateOnly } from '@/utils/dateRange'

const props = withDefaults(defineProps<{
  modelValue: string[] | null
  disabled?: boolean
  clearable?: boolean
  maxDays?: number
  today?: string
}>(), { disabled: false, clearable: false, maxDays: 90, today: '' })
const emit = defineEmits<{
  (event: 'update:modelValue', value: [string, string] | null): void
  (event: 'change', value: [string, string] | null): void
  (event: 'validity-change', value: boolean): void
}>()
const start = ref(''), end = ref('')
watch(() => props.modelValue, value => { start.value = value?.[0] || ''; end.value = value?.[1] || '' }, { immediate: true })
const error = computed(() => rangeError(start.value || '', end.value || '', props.maxDays))
watch([start, end, error], () => emit('validity-change', !error.value && (!!start.value && !!end.value || props.clearable && !start.value && !end.value)), { immediate: true })
const shortcuts = computed(() => {
  const today = props.today || dateOnly(), yesterday = shiftDateOnly(today, -1)
  return [{ label: '今天', range: [today, today] as [string, string] },
    { label: '昨天', range: [yesterday, yesterday] as [string, string] },
    ...[3, 7, 30, 90].filter(days => days <= props.maxDays).map(days => ({ label: `近 ${days} 天`, range: rangeForDays(days, today) }))]
})
function apply(value: [string, string]) {
  start.value = value[0]; end.value = value[1]
  emit('validity-change', true)
  emit('update:modelValue', value); emit('change', value)
}
function clear() { start.value = ''; end.value = ''; emit('validity-change', true); emit('update:modelValue', null); emit('change', null) }
function commit() {
  if (!start.value && !end.value && props.clearable) { clear(); return }
  if (!error.value && start.value && end.value) apply([start.value, end.value])
}
function isSelected(value: [string, string]) { return start.value === value[0] && end.value === value[1] }
</script>

<style scoped>
.date-range-fields { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px 14px; max-width: 100%; }
.date-range-inputs { display: flex; flex-wrap: wrap; gap: 12px; }
.date-range-field { display: flex; flex-direction: column; gap: 5px; color: #486581; font-size: 12px; }
.date-range-field :deep(.el-date-editor) { width: 170px; max-width: 100%; }
.date-range-shortcuts { display: flex; flex-wrap: wrap; gap: 6px; padding-bottom: 2px; }
.date-range-shortcuts :deep(.el-button + .el-button) { margin-left: 0; }
.date-range-error { flex-basis: 100%; color: var(--el-color-danger); font-size: 12px; }
@media (max-width: 600px) { .date-range-inputs { width: 100%; } .date-range-field { flex: 1; min-width: 145px; } .date-range-field :deep(.el-date-editor) { width: 100%; } }
</style>

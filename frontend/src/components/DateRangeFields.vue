<template>
  <div class="date-range-fields">
    <el-select :model-value="selectedMode" class="date-range-select" :disabled="disabled" placeholder="选择时间范围"
      aria-label="时间范围" popper-class="date-range-menu" @change="selectRange">
      <template #prefix><el-icon><Calendar /></el-icon></template>
      <el-option v-if="clearable" label="默认日期" value="default" />
      <el-option v-for="preset in presets" :key="preset.key" :label="preset.label" :value="preset.key" />
      <el-option label="自定义时间" value="custom" class="date-range-custom-option" @click="openCustom" />
    </el-select>
    <el-popover v-model:visible="customVisible" placement="bottom-start" trigger="click" :width="380"
      :disabled="disabled" :persistent="false" popper-class="date-range-custom-popper">
      <template #reference>
        <button type="button" class="date-range-summary" :disabled="disabled" aria-label="编辑自定义时间">
          {{ rangeLabel }}
        </button>
      </template>
      <div class="date-range-panel" role="dialog" aria-label="自定义时间" @keydown.esc.stop="cancelCustom">
        <div class="date-range-panel-title">自定义时间</div>
        <p class="date-range-hint">选择开始和结束日期，最多 {{ maxDays }} 天</p>
        <div class="date-range-inputs">
          <label class="date-range-field">
            <span>开始日期</span>
            <el-date-picker v-model="start" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD"
              placeholder="选择或输入开始日期" aria-label="开始日期" clearable :disabled="disabled"
              popper-class="date-single-popper" placement="bottom-start" :teleported="false" />
          </label>
          <label class="date-range-field">
            <span>结束日期</span>
            <el-date-picker v-model="end" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD"
              placeholder="选择或输入结束日期" aria-label="结束日期" clearable :disabled="disabled"
              popper-class="date-single-popper" placement="bottom-start" :teleported="false" />
          </label>
        </div>
        <p v-if="error" class="date-range-error" role="alert">{{ error }}</p>
        <p v-else class="date-range-hint date-range-duration">共 {{ inclusiveDays(start, end) }} 天，包含起止日期</p>
        <div class="date-range-panel-footer">
          <el-button @click="cancelCustom">取消</el-button>
          <el-button type="primary" :disabled="disabled || !!error" @click="commit">应用时间</el-button>
        </div>
      </div>
    </el-popover>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Calendar } from '@element-plus/icons-vue'
import { dateOnly, inclusiveDays, rangeError, rangeForDays, shiftDateOnly } from '@/utils/dateRange'

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
const start = ref(''), end = ref(''), customVisible = ref(false)
const error = computed(() => !start.value || !end.value ? '请选择开始日期和结束日期' : rangeError(start.value, end.value, props.maxDays))
const presets = computed(() => {
  const today = props.today || dateOnly(), yesterday = shiftDateOnly(today, -1)
  return [{ key: 'today', label: '今天', range: [today, today] as [string, string] },
    { key: 'yesterday', label: '昨天', range: [yesterday, yesterday] as [string, string] },
    ...[3, 7, 30, 90].filter(days => days <= props.maxDays).map(days => ({ key: `last-${days}`, label: `近${days}天`, range: rangeForDays(days, today) }))]
})
const selectedMode = computed(() => {
  const value = props.modelValue
  if (!value?.length) return props.clearable ? 'default' : ''
  return presets.value.find(preset => preset.range[0] === value[0] && preset.range[1] === value[1])?.key || 'custom'
})
const rangeLabel = computed(() => props.modelValue?.length === 2 ? `${props.modelValue[0]} 至 ${props.modelValue[1]}` : '设置自定义时间')
watch(customVisible, visible => {
  if (visible) {
    const value = props.modelValue?.length === 2 ? props.modelValue : rangeForDays(Math.min(7, props.maxDays), props.today || dateOnly())
    start.value = value[0]; end.value = value[1]
  }
})
watch([() => props.modelValue, customVisible], () => {
  const value = props.modelValue
  const appliedValid = value?.length === 2 ? !rangeError(value[0], value[1], props.maxDays) : props.clearable
  emit('validity-change', appliedValid && !customVisible.value)
}, { immediate: true, deep: true })
watch(() => props.disabled, disabled => { if (disabled) customVisible.value = false })
function selectRange(key: string) {
  if (key === 'custom') { openCustom(); return }
  customVisible.value = false
  if (key === 'default') { emit('validity-change', true); emit('update:modelValue', null); emit('change', null); return }
  const preset = presets.value.find(item => item.key === key)
  if (preset) apply(preset.range)
}
function openCustom() { if (!props.disabled) customVisible.value = true }
function cancelCustom() { customVisible.value = false }
function apply(value: [string, string]) {
  customVisible.value = false
  emit('validity-change', true)
  emit('update:modelValue', value); emit('change', value)
}
function commit() {
  if (!props.disabled && !error.value) apply([start.value, end.value])
}
</script>

<style scoped>
.date-range-fields { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; max-width: 100%; }
.date-range-select { width: 140px; }
.date-range-summary { max-width: 100%; overflow: hidden; text-overflow: ellipsis; border: 0; border-radius: 5px; padding: 6px 4px; background: transparent; color: #627d98; font: inherit; font-size: 12px; line-height: 20px; cursor: pointer; white-space: nowrap; }
.date-range-summary:hover, .date-range-summary:focus-visible { color: var(--el-color-primary); background: #edf6fd; }
.date-range-summary:disabled { cursor: default; opacity: .6; }
.date-range-panel-title { color: #102a43; font-size: 15px; font-weight: 600; }
.date-range-hint { margin: 6px 0 16px; color: #829ab1; font-size: 12px; line-height: 18px; }
.date-range-inputs { display: flex; gap: 12px; }
.date-range-field { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 7px; color: #486581; font-size: 12px; }
.date-range-field :deep(.el-date-editor) { width: 100%; }
.date-range-duration, .date-range-error { margin: 12px 0 0; min-height: 18px; font-size: 12px; line-height: 18px; }
.date-range-error { color: var(--el-color-danger); }
.date-range-panel-footer { display: flex; justify-content: flex-end; gap: 8px; border-top: 1px solid #edf1f7; margin-top: 16px; padding-top: 14px; }
.date-range-panel-footer :deep(.el-button + .el-button) { margin-left: 0; }
@media (max-width: 600px) { .date-range-fields { gap: 4px 8px; } .date-range-summary { font-size: 11px; } }
</style>

<template>
  <div class="language-select">
    <el-select
      v-model="selected"
      multiple
      filterable
      remote
      reserve-keyword
      :remote-method="search"
      :loading="loading"
      collapse-tags
      collapse-tags-tooltip
      clearable
      style="width: 100%"
      placeholder="不限制语言"
      @change="emitValue"
    >
      <el-option v-for="item in options" :key="item.id" :label="`${item.name} · ${item.name_en}`" :value="item.id">
        <span>{{ item.name }}</span>
        <span class="language-meta">{{ item.name_en }} · {{ item.code }}</span>
      </el-option>
    </el-select>
    <div class="language-tip">留空表示不限制语言；输入会自动匹配 Meta 语言目录，不接受自定义文本。</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { metaTargetingApi, type MetaLanguageOption } from '@/api/metaTargeting'

const props = defineProps<{ modelValue: string[] }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: string[]): void }>()
const selected = ref<string[]>([...(props.modelValue || [])])
const options = ref<MetaLanguageOption[]>([])
const loading = ref(false)

watch(() => props.modelValue, value => { selected.value = [...(value || [])] })

const search = async (query = '') => {
  loading.value = true
  try {
    const { data } = await metaTargetingApi.languages(query)
    options.value = data.items || []
  } finally {
    loading.value = false
  }
}
const emitValue = (value: string[]) => emit('update:modelValue', [...value])
onMounted(() => search())
</script>

<style scoped>
.language-tip { color: #909399; font-size: 12px; line-height: 1.5; margin-top: 4px; }
.language-meta { float: right; color: #909399; font-size: 12px; margin-left: 16px; }
</style>

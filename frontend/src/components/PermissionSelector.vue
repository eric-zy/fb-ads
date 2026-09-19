<template>
  <div class="permission-selector">
    <div class="selector-toolbar">
      <el-input
        v-model="keyword"
        class="permission-search"
        clearable
        placeholder="搜索功能或权限编码"
        :prefix-icon="Search"
      />
      <div class="selector-actions">
        <span class="selected-count">已选 {{ selectedCount }} / {{ allPermissionValues.length }}</span>
        <el-button link type="primary" @click="selectVisible">全选当前</el-button>
        <el-button link @click="clearAll">清空</el-button>
      </div>
    </div>

    <div v-if="visibleGroups.length" class="permission-groups">
      <section v-for="group in visibleGroups" :key="group.key" class="permission-group">
        <div class="group-header">
          <div class="group-title-row">
            <el-checkbox
              :model-value="isGroupChecked(group)"
              :indeterminate="isGroupIndeterminate(group)"
              @change="toggleGroup(group, Boolean($event))"
            >
              {{ group.label }}
            </el-checkbox>
            <span class="group-count">{{ groupSelectedCount(group) }} / {{ group.permissions.length }}</span>
          </div>
          <span class="group-description">{{ group.description }}</span>
        </div>

        <div class="permission-grid">
          <div v-for="permission in group.permissions" :key="permission.value" class="permission-item">
            <el-checkbox
              :model-value="isSelected(permission.value)"
              @change="togglePermission(permission.value, Boolean($event))"
            >
              <span class="permission-copy">
                <span class="permission-label">{{ permission.label }}</span>
                <span class="permission-description">{{ permission.description }}</span>
              </span>
            </el-checkbox>
          </div>
        </div>
      </section>
    </div>

    <el-empty v-else :image-size="64" description="没有匹配的权限" />

    <div v-if="unknownPermissions.length" class="unknown-permissions">
      <div class="unknown-title">未归类权限</div>
      <div class="unknown-list">
        <el-tag v-for="permission in unknownPermissions" :key="permission" closable @close="togglePermission(permission, false)">
          {{ permission }}
        </el-tag>
      </div>
      <p>这些权限来自历史配置，保存时会继续保留。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import {
  allPermissionValues,
  permissionGroups,
  type PermissionGroup,
} from '@/config/permissions'

const props = defineProps<{ modelValue: string[] }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: string[]): void }>()

const keyword = ref('')

const visibleGroups = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return permissionGroups

  return permissionGroups
    .map(group => ({
      ...group,
      permissions: group.permissions.filter(permission =>
        `${permission.label} ${permission.value} ${permission.description}`.toLowerCase().includes(query),
      ),
    }))
    .filter(group => group.permissions.length)
})

const selectedCount = computed(() => (props.modelValue || []).filter(permission => allPermissionValues.includes(permission)).length)
const unknownPermissions = computed(() => (props.modelValue || []).filter(permission => !allPermissionValues.includes(permission)))

function isSelected(permission: string) {
  return (props.modelValue || []).includes(permission)
}

function groupSelectedCount(group: PermissionGroup) {
  return group.permissions.filter(permission => isSelected(permission.value)).length
}

function isGroupChecked(group: PermissionGroup) {
  return group.permissions.length > 0 && groupSelectedCount(group) === group.permissions.length
}

function isGroupIndeterminate(group: PermissionGroup) {
  const count = groupSelectedCount(group)
  return count > 0 && count < group.permissions.length
}

function emitPermissions(values: string[]) {
  emit('update:modelValue', Array.from(new Set(values)))
}

function togglePermission(permission: string, checked: boolean) {
  const current = new Set(props.modelValue || [])
  if (checked) current.add(permission)
  else current.delete(permission)
  emitPermissions(Array.from(current))
}

function toggleGroup(group: PermissionGroup, checked: boolean) {
  const current = new Set(props.modelValue || [])
  group.permissions.forEach(permission => {
    if (checked) current.add(permission.value)
    else current.delete(permission.value)
  })
  emitPermissions(Array.from(current))
}

function selectVisible() {
  const current = new Set(props.modelValue || [])
  visibleGroups.value.forEach(group => group.permissions.forEach(permission => current.add(permission.value)))
  emitPermissions(Array.from(current))
}

function clearAll() {
  emitPermissions([])
}
</script>

<style scoped>
.permission-selector {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: #fbfcfe;
  overflow: hidden;
}

.selector-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
  background: #fff;
}

.permission-search {
  max-width: 300px;
}

.selector-actions {
  display: flex;
  align-items: center;
  white-space: nowrap;
}

.selected-count,
.group-count {
  color: var(--text-secondary);
  font-size: 12px;
}

.permission-groups {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 14px;
  max-height: 430px;
  overflow-y: auto;
}

.permission-group {
  border: 1px solid #e9edf3;
  border-radius: 9px;
  background: #fff;
}

.group-header {
  padding: 11px 12px 9px;
  border-bottom: 1px solid #eef1f5;
}

.group-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.group-description {
  display: block;
  margin: 3px 0 0 24px;
  color: var(--text-secondary);
  font-size: 12px;
}

.permission-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 2px;
  padding: 8px 12px 10px;
}

.permission-item {
  display: block;
  padding: 4px 0;
  cursor: pointer;
}

.permission-copy {
  display: inline-flex;
  flex-direction: column;
  vertical-align: top;
  line-height: 18px;
}

.permission-label {
  color: var(--text-regular);
  font-size: 13px;
}

.permission-description {
  color: var(--text-secondary);
  font-size: 11px;
}

.unknown-permissions {
  margin: 0 14px 14px;
  padding: 10px 12px;
  border: 1px dashed #e6a23c;
  border-radius: 8px;
  background: #fffbf2;
}

.unknown-title {
  margin-bottom: 8px;
  color: #9a6700;
  font-size: 12px;
  font-weight: 600;
}

.unknown-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.unknown-permissions p {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 11px;
}

@media (max-width: 760px) {
  .selector-toolbar {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .permission-search {
    max-width: none;
  }

  .permission-groups {
    grid-template-columns: 1fr;
  }
}
</style>

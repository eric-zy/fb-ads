<template>
  <div class="page-container role-page">
    <div class="page-head">
      <div>
        <h2 class="page-title">角色与权限</h2>
        <p class="page-subtitle">按功能模块组合权限，再将角色模板分配给团队成员</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建角色</el-button>
    </div>

    <div class="summary-grid">
      <div class="summary-card">
        <span class="summary-label">角色总数</span>
        <strong>{{ roles.length }}</strong>
        <span class="summary-note">系统角色与自定义角色</span>
      </div>
      <div class="summary-card">
        <span class="summary-label">自定义角色</span>
        <strong>{{ customRoleCount }}</strong>
        <span class="summary-note">可按团队职责复用</span>
      </div>
      <div class="summary-card accent-card">
        <span class="summary-label">可配置权限</span>
        <strong>{{ allPermissionValues.length }}</strong>
        <span class="summary-note">分布在 {{ permissionGroups.length }} 个功能组</span>
      </div>
    </div>

    <el-card class="card-shadow role-card" shadow="never">
      <div class="toolbar">
        <el-input
          v-model="search"
          class="role-search"
          clearable
          placeholder="搜索角色名称、编码或说明"
          :prefix-icon="Search"
        />
        <el-select v-model="typeFilter" clearable placeholder="角色类型" class="role-filter">
          <el-option label="系统角色" value="system" />
          <el-option label="自定义角色" value="custom" />
        </el-select>
        <span class="list-hint">共 {{ filteredRoles.length }} 个角色</span>
      </div>

      <el-table :data="filteredRoles" v-loading="loading" stripe>
        <el-table-column label="角色" min-width="210">
          <template #default="{ row }">
            <div class="role-name-cell">
              <span class="role-avatar">{{ (row.name || '角').slice(0, 1) }}</span>
              <div>
                <div class="role-name-line">
                  <span class="role-name">{{ row.name }}</span>
                  <el-tag v-if="row.is_system" size="small" type="info" effect="plain">系统</el-tag>
                </div>
                <span class="role-code">{{ row.code }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || '暂无说明' }}</template>
        </el-table-column>
        <el-table-column label="功能权限" min-width="330">
          <template #default="{ row }">
            <div class="permission-summary">
              <template v-if="row.permissions?.length">
                <el-tag
                  v-for="item in permissionSummary(row).slice(0, 3)"
                  :key="item.key"
                  size="small"
                  effect="light"
                >
                  {{ item.label }} {{ item.count }}
                </el-tag>
                <el-tag v-if="permissionSummary(row).length > 3" size="small" type="info" effect="plain">
                  +{{ permissionSummary(row).length - 3 }} 组
                </el-tag>
              </template>
              <el-tag v-else size="small" type="info" effect="plain">未分配权限</el-tag>
              <span class="permission-total">{{ row.permissions?.length || 0 }} 项</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">{{ formatDate(row.updated_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑权限</el-button>
            <el-button v-if="!row.is_system" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无匹配角色" />
        </template>
      </el-table>
    </el-card>

    <el-dialog
      v-model="visible"
      :title="editing ? `编辑角色：${editing.name}` : '新建角色'"
      width="900px"
      top="5vh"
      destroy-on-close
      class="role-dialog"
    >
      <el-form :model="form" label-position="top">
        <div class="basic-form-grid">
          <el-form-item label="角色名称" required>
            <el-input v-model="form.name" placeholder="例如：投放专员" maxlength="128" show-word-limit />
          </el-form-item>
          <el-form-item label="角色编码" required>
            <el-input v-model="form.code" :disabled="!!editing" placeholder="例如：campaign_operator" maxlength="64" />
          </el-form-item>
          <el-form-item label="角色说明" class="description-field">
            <el-input v-model="form.description" placeholder="说明这个角色主要负责什么工作" maxlength="500" />
          </el-form-item>
        </div>

        <div class="permission-heading">
          <div>
            <h3>分配功能权限</h3>
            <p>勾选功能组可快速全选，也可以在组内精确选择单项权限。</p>
          </div>
          <el-tag type="primary" effect="light">已选 {{ form.permissions.length }} 项</el-tag>
        </div>

        <PermissionSelector v-model="form.permissions" />
      </el-form>

      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存角色</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { roleApi } from '@/api/admin'
import PermissionSelector from '@/components/PermissionSelector.vue'
import {
  allPermissionValues,
  permissionGroups,
  permissionGroupLabel,
} from '@/config/permissions'

interface RoleItem {
  id: string
  code: string
  name: string
  description?: string
  permissions: string[]
  is_system: boolean
  created_at?: string | null
  updated_at?: string | null
}

const roles = ref<RoleItem[]>([])
const loading = ref(false)
const saving = ref(false)
const visible = ref(false)
const editing = ref<RoleItem | null>(null)
const search = ref('')
const typeFilter = ref('')

const form = ref({
  code: '',
  name: '',
  description: '',
  permissions: [] as string[],
})

const customRoleCount = computed(() => roles.value.filter(role => !role.is_system).length)

const filteredRoles = computed(() => {
  const query = search.value.trim().toLowerCase()
  return roles.value.filter(role => {
    const matchesType = !typeFilter.value || (typeFilter.value === 'system' ? role.is_system : !role.is_system)
    const text = `${role.name} ${role.code} ${role.description || ''}`.toLowerCase()
    return matchesType && (!query || text.includes(query))
  })
})

function formatDate(value?: string | null) {
  return value ? value.slice(0, 10) : '-'
}

function permissionSummary(role: RoleItem) {
  const counts = new Map<string, number>()
  for (const permission of role.permissions || []) {
    const group = permissionGroupLabel(permission)
    counts.set(group, (counts.get(group) || 0) + 1)
  }
  return Array.from(counts.entries()).map(([label, count]) => ({ key: label, label, count }))
}

async function load() {
  loading.value = true
  try {
    roles.value = (await roleApi.list()).data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  form.value = { code: '', name: '', description: '', permissions: [] }
  visible.value = true
}

function openEdit(role: RoleItem) {
  editing.value = role
  form.value = {
    code: role.code,
    name: role.name,
    description: role.description || '',
    permissions: [...(role.permissions || [])],
  }
  visible.value = true
}

async function save() {
  if (!form.value.name.trim() || !form.value.code.trim()) {
    ElMessage.warning('请填写角色名称和角色编码')
    return
  }

  saving.value = true
  try {
    const payload = {
      ...form.value,
      code: form.value.code.trim(),
      name: form.value.name.trim(),
      permissions: Array.from(new Set(form.value.permissions)),
    }
    if (editing.value) await roleApi.update(editing.value.id, payload)
    else await roleApi.create(payload)
    visible.value = false
    await load()
    ElMessage.success('角色已保存')
  } finally {
    saving.value = false
  }
}

async function remove(role: RoleItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除角色「${role.name}」？已分配给用户的角色关系也会失效。`,
      '删除角色',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await roleApi.remove(role.id)
    await load()
    ElMessage.success('角色已删除')
  } catch {
    // 用户取消或请求失败由统一拦截器处理。
  }
}

onMounted(load)
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-height: 106px;
  padding: 18px 20px;
  border: 1px solid #e8edf4;
  border-radius: 12px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}

.summary-card strong {
  color: var(--text-primary);
  font-size: 28px;
  line-height: 1;
}

.summary-label {
  color: var(--text-secondary);
  font-size: 13px;
}

.summary-note {
  color: var(--text-secondary);
  font-size: 12px;
}

.accent-card {
  border-color: #cfe7fb;
  background: linear-gradient(135deg, #fafdff, #eef8ff);
}

.accent-card strong {
  color: var(--primary-dark);
}

.role-card {
  overflow: hidden;
}

.role-search {
  width: 300px;
}

.role-filter {
  width: 140px;
}

.list-hint {
  margin-left: auto;
  color: var(--text-secondary);
  font-size: 12px;
}

.role-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.role-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  color: #fff;
  background: var(--primary-gradient);
  font-size: 15px;
  font-weight: 600;
}

.role-name-line {
  display: flex;
  align-items: center;
  gap: 7px;
}

.role-name {
  color: var(--text-primary);
  font-weight: 600;
}

.role-code {
  display: block;
  margin-top: 2px;
  color: var(--text-secondary);
  font-family: Consolas, monospace;
  font-size: 11px;
}

.permission-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}

.permission-total {
  margin-left: 3px;
  color: var(--text-secondary);
  font-size: 12px;
}

.basic-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 18px;
}

.description-field {
  grid-column: 1 / -1;
}

.permission-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 5px 0 10px;
}

.permission-heading h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 15px;
}

.permission-heading p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
}

@media (max-width: 760px) {
  .summary-grid,
  .basic-form-grid {
    grid-template-columns: 1fr;
  }

  .description-field {
    grid-column: auto;
  }

  .role-search,
  .role-filter {
    width: 100%;
  }

  .list-hint {
    margin-left: 0;
  }
}
</style>

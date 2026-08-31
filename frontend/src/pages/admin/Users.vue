<template>
  <div class="page-container">
    <div class="page-head">
      <div>
        <h2 class="page-title">用户管理</h2>
        <p class="page-subtitle">管理系统中的所有用户账户与权限</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </div>

    <el-card class="card-shadow" shadow="never">
      <div class="toolbar">
        <el-input
          v-model="search"
          placeholder="搜索邮箱 / 用户名"
          clearable
          style="width: 240px"
          :prefix-icon="Search"
          @input="debouncedLoad"
        />
        <el-select v-model="roleFilter" placeholder="角色" clearable style="width: 140px" @change="loadUsers">
          <el-option label="管理员" value="admin" />
          <el-option label="经理" value="manager" />
          <el-option label="普通用户" value="user" />
        </el-select>
        <el-select v-model="activeFilter" placeholder="状态" clearable style="width: 140px" @change="loadUsers">
          <el-option label="已启用" value="true" />
          <el-option label="已禁用" value="false" />
        </el-select>
      </div>

      <el-table :data="users" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag :type="roleType(row.role)" effect="light" round>{{ roleLabel(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" effect="light" round>
              <span class="status-dot" :class="row.is_active ? 'on' : 'off'"></span>
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="注册时间" min-width="130">
          <template #default="{ row }">{{ row.created_at ? row.created_at.slice(0, 10) : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" size="small" @click="openPwd(row)">改密</el-button>
            <el-button link :type="row.is_active ? 'info' : 'success'" size="small" @click="toggle(row)">
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无用户" />
        </template>
      </el-table>
    </el-card>

    <!-- 新建/编辑弹窗 -->
    <el-dialog v-model="showForm" :title="form.id ? '编辑用户' : '新建用户'" width="440px" destroy-on-close>
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="用户名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="邮箱" type="email" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="初始密码">
          <el-input v-model="form.password" placeholder="初始密码" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="经理" value="manager" />
            <el-option label="普通用户" value="user" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 改密弹窗 -->
    <el-dialog v-model="showPwd" :title="`重置密码 - ${pwdUser?.username}`" width="420px" destroy-on-close>
      <el-form label-width="80px">
        <el-form-item label="新密码">
          <el-input v-model="pwdValue" placeholder="新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPwd = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePwd">重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { userApi, type AdminUser } from '../../api/admin'

const users = ref<AdminUser[]>([])
const loading = ref(false)
const search = ref('')
const roleFilter = ref('')
const activeFilter = ref('')

const showForm = ref(false)
const saving = ref(false)
const form = ref<Partial<AdminUser> & { password?: string }>({
  username: '', email: '', password: '123456', role: 'user', is_active: true,
})

const showPwd = ref(false)
const pwdUser = ref<AdminUser | null>(null)
const pwdValue = ref('')

let timer: number | undefined
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(loadUsers, 300) as unknown as number
}

function roleLabel(r: string) {
  return { admin: '管理员', manager: '经理', user: '普通用户' }[r] || r
}
function roleType(r: string): 'danger' | 'warning' | 'info' {
  return { admin: 'danger', manager: 'warning', user: 'info' }[r] || 'info'
}

async function loadUsers() {
  loading.value = true
  try {
    const params: any = { page: 1, page_size: 100 }
    if (search.value) params.search = search.value
    if (roleFilter.value) params.role = roleFilter.value
    if (activeFilter.value !== '') params.is_active = activeFilter.value === 'true'
    const { data } = await userApi.list(params)
    users.value = data
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    loading.value = false
  }
}

function openCreate() {
  form.value = { username: '', email: '', password: '123456', role: 'user', is_active: true }
  showForm.value = true
}
function openEdit(u: AdminUser) {
  form.value = { ...u }
  showForm.value = true
}
async function save() {
  saving.value = true
  try {
    if (form.value.id) {
      const { id, ...rest } = form.value as any
      await userApi.update(id, rest)
    } else {
      const res = await userApi.create(form.value as any)
      if (res.data.temp_password) ElMessage.success(`创建成功，初始密码：${res.data.temp_password}`)
    }
    showForm.value = false
    await loadUsers()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}
function openPwd(u: AdminUser) {
  pwdUser.value = u
  pwdValue.value = ''
  showPwd.value = true
}
async function savePwd() {
  if (!pwdUser.value) return
  saving.value = true
  try {
    await userApi.resetPassword(pwdUser.value.id, pwdValue.value)
    showPwd.value = false
    ElMessage.success('密码已重置')
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}
async function toggle(u: AdminUser) {
  try {
    await ElMessageBox.confirm(`确认${u.is_active ? '禁用' : '启用'}用户 ${u.username}？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await userApi.toggleActive(u.id)
    await loadUsers()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}
async function remove(u: AdminUser) {
  try {
    await ElMessageBox.confirm(`确认删除用户 ${u.username}？此操作不可恢复。`, '警告', { type: 'error' })
  } catch {
    return
  }
  try {
    await userApi.delete(u.id)
    await loadUsers()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.status-dot.on {
  background: var(--success);
}
.status-dot.off {
  background: var(--text-secondary);
}
</style>

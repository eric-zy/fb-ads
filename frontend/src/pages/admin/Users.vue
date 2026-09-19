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
          placeholder="搜索用户名"
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
        <el-table-column prop="tenant_id" label="租户 ID" min-width="150" show-overflow-tooltip />
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
        <el-table-column label="最后登录" min-width="150">
          <template #default="{ row }">{{ row.last_login ? row.last_login.slice(0, 19).replace('T', ' ') : '从未登录' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="130">
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
          <el-input v-model="form.username" placeholder="3-64 个字符，不含空格" />
        </el-form-item>
        <el-form-item v-if="!form.id" label="初始密码">
          <el-input v-model="form.password" placeholder="至少 6 个字符" show-password />
        </el-form-item>
        <el-form-item v-if="isPlatformAdmin" label="所属租户" required>
          <el-select v-model="form.tenant_id" clearable placeholder="请选择租户" style="width: 100%">
            <el-option v-for="tenant in tenants" :key="tenant.id" :label="`${tenant.name} (${tenant.slug})`" :value="tenant.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option label="租户管理员" value="tenant_admin" />
            <el-option label="经理" value="manager" />
            <el-option label="普通用户" value="user" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色模板">
          <el-select v-model="form.role_id" clearable placeholder="选择角色模板" style="width: 100%">
            <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="权限">
          <el-checkbox-group v-model="form.permissions">
            <el-checkbox label="meta_asset:manage">Meta 资产</el-checkbox>
            <el-checkbox label="ad_account:read">查看账户</el-checkbox>
            <el-checkbox label="ad_account:manage">管理账户</el-checkbox>
            <el-checkbox label="job:create">创建投放</el-checkbox>
            <el-checkbox label="job:retry">重试任务</el-checkbox>
            <el-checkbox label="job:cancel">取消任务</el-checkbox>
            <el-checkbox label="campaign:read">查看已发布广告</el-checkbox>
            <el-checkbox label="campaign:pause">暂停广告</el-checkbox>
            <el-checkbox label="campaign:enable">启用广告</el-checkbox>
            <el-checkbox label="campaign:archive">归档广告</el-checkbox>
            <el-checkbox label="campaign:update_budget">修改预算</el-checkbox>
            <el-checkbox label="campaign:sync">同步 Meta 状态</el-checkbox>
            <el-checkbox label="insight:read">查看报表</el-checkbox>
          </el-checkbox-group>
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
          <el-input v-model="pwdValue" placeholder="至少 6 个字符" show-password />
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
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { userApi, tenantApi, type AdminUser, type TenantItem } from '../../api/admin'
import { roleApi } from '../../api/admin'
import { useUserStore } from '../../stores/userStore'

const users = ref<AdminUser[]>([])
const loading = ref(false)
const search = ref('')
const roleFilter = ref('')
const activeFilter = ref('')

const showForm = ref(false)
const saving = ref(false)
const form = ref<Partial<AdminUser> & { password?: string }>({
  username: '', password: '123456', role: 'user', is_active: true,
})

const showPwd = ref(false)
const pwdUser = ref<AdminUser | null>(null)
const pwdValue = ref('')
const roles = ref<any[]>([])
const tenants = ref<TenantItem[]>([])
const userStore = useUserStore()
const isPlatformAdmin = computed(() => userStore.isPlatformAdmin)
const permissionDefaults = [] as string[]

let timer: number | undefined
function debouncedLoad() {
  clearTimeout(timer)
  timer = setTimeout(loadUsers, 300) as unknown as number
}

function roleLabel(r: string) {
  return { admin: '管理员', tenant_admin: '租户管理员', platform_admin: '平台管理员', manager: '经理', user: '普通用户' }[r] || r
}
function roleType(r: string): 'danger' | 'warning' | 'info' {
  return { admin: 'danger', tenant_admin: 'danger', platform_admin: 'danger', manager: 'warning', user: 'info' }[r] || 'info'
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
async function loadRoles() { try { roles.value = (await roleApi.list()).data } catch { roles.value = [] } }
async function loadTenants() {
  try { tenants.value = (await tenantApi.list({ status: 'ACTIVE', page: 1, page_size: 100 })).data }
  catch { tenants.value = [] }
}

function openCreate() {
  form.value = { username: '', password: '123456', role: 'user', tenant_id: null, is_active: true, permissions: [...permissionDefaults] }
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
      if (isPlatformAdmin.value && !form.value.tenant_id) {
        ElMessage.warning('平台管理员创建普通用户时必须选择所属租户')
        return
      }
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

onMounted(async () => {
  await Promise.all([loadUsers(), loadRoles(), isPlatformAdmin.value ? loadTenants() : Promise.resolve()])
})
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

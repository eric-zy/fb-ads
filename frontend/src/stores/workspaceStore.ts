import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useUserStore } from '@/stores/userStore'
import request from '@/utils/request'

export interface WorkspaceOption {
  id: string
  name: string
  code: string
  roleLabel: string
}

const WORKSPACE_STORAGE_KEY = 'active_workspace_id'

export const useWorkspaceStore = defineStore('workspace', () => {
  const activeWorkspaceId = ref('')
  const tenantOptions = ref<WorkspaceOption[]>([])

  const workspaceOptions = computed<WorkspaceOption[]>(() => {
    const userStore = useUserStore()
    const user = userStore.user

    if (!user) return []

    if (tenantOptions.value.length) return tenantOptions.value
    return [
      {
        id: user.tenant_id || user.company_id || 'default-workspace',
        name: user.tenant_name || user.company_name || '默认工作空间',
        code: user.tenant_id || user.company_id || 'default',
        roleLabel: user.role === 'admin' ? '管理员' : user.role === 'manager' ? '运营经理' : '操作员',
      },
    ]
  })

  const loadPlatformTenants = async () => {
    const userStore = useUserStore()
    if (!userStore.isPlatformAdmin) return
    const response = await request.get('/api/v1/tenants', { params: { status: 'ACTIVE', page: 1, page_size: 100 } })
    tenantOptions.value = response.data.map((tenant: any) => ({ id: tenant.id, name: tenant.name, code: tenant.slug, roleLabel: '租户' }))
  }

  const activeWorkspace = computed(() => {
    return workspaceOptions.value.find((item) => item.id === activeWorkspaceId.value) || workspaceOptions.value[0] || null
  })

  const initWorkspace = () => {
    const saved = localStorage.getItem(WORKSPACE_STORAGE_KEY)
    if (saved) activeWorkspaceId.value = saved
    if (!activeWorkspaceId.value && workspaceOptions.value[0]) {
      activeWorkspaceId.value = workspaceOptions.value[0].id
    }
  }

  const setWorkspace = (id: string) => {
    activeWorkspaceId.value = id
    localStorage.setItem(WORKSPACE_STORAGE_KEY, id)
  }

  return {
    activeWorkspaceId,
    workspaceOptions,
    activeWorkspace,
    initWorkspace,
    setWorkspace,
    loadPlatformTenants,
  }
})

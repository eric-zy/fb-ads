// Pinia用户store
//
// 说明：Token 的注入与失效处理已统一收敛到 utils/request.ts 的拦截器，
// 这里只负责登录态的读写与持久化，不再手工设置 axios.defaults。
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'
import Cookies from 'js-cookie'

export interface User {
  id: string
  email: string
  username: string
  role: 'admin' | 'platform_admin' | 'tenant_admin' | 'manager' | 'user'
  company_id: string
  tenant_id?: string | null
  is_platform_admin?: boolean
  permissions: string[]
  settings: Record<string, any>
}

const TOKEN_KEY = 'auth_token'
const USER_KEY = 'user'

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const token = ref<string>('')
  const isLoading = ref(false)

  const isAuthenticated = computed(() => !!token.value)
  // 兼容多租户角色：platform_admin / tenant_admin 都具备管理员权限；
  // admin 为历史角色值，继续兼容旧账号。
  const isAdmin = computed(() => {
    const role = user.value?.role
    return role === 'admin' || role === 'platform_admin' || role === 'tenant_admin'
  })
  const isManager = computed(() => user.value?.role === 'manager')
  const isPlatformAdmin = computed(() => user.value?.role === 'platform_admin' || user.value?.is_platform_admin === true)

  // 初始化认证状态（从 Cookie / localStorage 恢复）
  const initAuth = () => {
    const storedToken = Cookies.get(TOKEN_KEY)
    const storedUser = localStorage.getItem(USER_KEY)

    if (storedToken) {
      token.value = storedToken

      if (storedUser) {
        try {
          user.value = JSON.parse(storedUser)
        } catch (e) {
          console.error('Failed to parse stored user', e)
        }
      }
    }
  }

  // 登录
  const login = async (email: string, password: string) => {
    isLoading.value = true
    try {
      const response = await request.post('/api/v1/auth/login', {
        email,
        password,
      }, {
        // 登录失败由 Login.vue 页面层弹框提示，避免拦截器全局弹框在此场景不可靠
        skipErrorMessage: true,
      })

      const { access_token, user: userData } = response.data
      token.value = access_token
      user.value = userData

      Cookies.set(TOKEN_KEY, access_token, { expires: 7 })
      localStorage.setItem(USER_KEY, JSON.stringify(userData))

      return true
    } catch (error: any) {
      console.error('Login error:', error)
      throw error
    } finally {
      isLoading.value = false
    }
  }

  // 登出
  const logout = async () => {
    try {
      await request.post('/api/v1/auth/logout')
    } finally {
      token.value = ''
      user.value = null
      Cookies.remove(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    }
  }

  // 更新用户设置
  const updateSettings = async (settings: Record<string, any>) => {
    if (!user.value) return

    try {
      const response = await request.put(`/api/v1/users/${user.value.id}/settings`, {
        settings,
      })

      user.value.settings = response.data.settings
      localStorage.setItem(USER_KEY, JSON.stringify(user.value))
      return true
    } catch (error) {
      console.error('Update settings error:', error)
      return false
    }
  }

  // 检查权限
  const hasPermission = (permission: string): boolean => {
    return user.value?.permissions?.includes(permission) ?? false
  }

  return {
    user,
    token,
    isLoading,
    isAuthenticated,
    isAdmin,
    isManager,
    isPlatformAdmin,
    initAuth,
    login,
    logout,
    updateSettings,
    hasPermission,
  }
})

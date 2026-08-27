// Pinia用户store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import Cookies from 'js-cookie'

export interface User {
  id: string
  email: string
  username: string
  role: 'admin' | 'manager' | 'user'
  company_id: string
  permissions: string[]
  settings: Record<string, any>
}

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const token = ref<string>('')
  const isLoading = ref(false)

  const isAuthenticated = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isManager = computed(() => user.value?.role === 'manager')

  // 初始化认证状态
  const initAuth = () => {
    const storedToken = Cookies.get('auth_token')
    const storedUser = localStorage.getItem('user')
    
    if (storedToken) {
      token.value = storedToken
      axios.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`
      
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
      const response = await axios.post('/api/v1/auth/login', {
        email,
        password,
      })
      
      const { access_token, user: userData } = response.data
      token.value = access_token
      user.value = userData
      
      Cookies.set('auth_token', access_token, { expires: 7 })
      localStorage.setItem('user', JSON.stringify(userData))
      axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
      
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
      await axios.post('/api/v1/auth/logout')
    } finally {
      token.value = ''
      user.value = null
      Cookies.remove('auth_token')
      localStorage.removeItem('user')
      delete axios.defaults.headers.common['Authorization']
    }
  }

  // 更新用户设置
  const updateSettings = async (settings: Record<string, any>) => {
    if (!user.value) return
    
    try {
      const response = await axios.put(`/api/v1/users/${user.value.id}/settings`, {
        settings,
      })
      
      user.value.settings = response.data.settings
      localStorage.setItem('user', JSON.stringify(user.value))
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
    initAuth,
    login,
    logout,
    updateSettings,
    hasPermission,
  }
})

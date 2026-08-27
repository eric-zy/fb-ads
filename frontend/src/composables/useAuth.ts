// 认证模块
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import Cookies from 'js-cookie'

interface LoginPayload {
  email: string
  password: string
}

interface User {
  id: string
  email: string
  username: string
  role: string
  company_id: string
  permissions: string[]
}

export const useAuth = () => {
  const router = useRouter()
  const user = ref<User | null>(null)
  const token = ref<string>('')
  const isLoading = ref(false)
  const error = ref<string>('')

  // 从localStorage加载token
  const loadTokenFromStorage = () => {
    const storedToken = Cookies.get('auth_token')
    const storedUser = localStorage.getItem('user')
    
    if (storedToken) {
      token.value = storedToken
      axios.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`
    }
    
    if (storedUser) {
      try {
        user.value = JSON.parse(storedUser)
      } catch (e) {
        console.error('Failed to parse stored user', e)
      }
    }
  }

  // 登录
  const login = async (payload: LoginPayload) => {
    isLoading.value = true
    error.value = ''
    
    try {
      const response = await axios.post('/api/v1/auth/login', payload)
      const { access_token, user: userData } = response.data
      
      // 保存token和用户信息
      token.value = access_token
      user.value = userData
      
      Cookies.set('auth_token', access_token, { expires: 7 })
      localStorage.setItem('user', JSON.stringify(userData))
      
      // 设置请求头
      axios.defaults.headers.common['Authorization'] = `Bearer ${access_token}`
      
      // 根据角色跳转
      if (userData.role === 'admin') {
        await router.push('/dashboard/admin')
      } else if (userData.role === 'manager') {
        await router.push('/dashboard/manager')
      } else {
        await router.push('/dashboard/user')
      }
      
      return true
    } catch (err: any) {
      error.value = err.response?.data?.detail || '登录失败，请重试'
      return false
    } finally {
      isLoading.value = false
    }
  }

  // 登出
  const logout = async () => {
    try {
      await axios.post('/api/v1/auth/logout')
    } catch (e) {
      console.error('Logout error:', e)
    } finally {
      token.value = ''
      user.value = null
      Cookies.remove('auth_token')
      localStorage.removeItem('user')
      delete axios.defaults.headers.common['Authorization']
      await router.push('/login')
    }
  }

  // 检查权限
  const hasPermission = (permission: string): boolean => {
    return user.value?.permissions?.includes(permission) ?? false
  }

  // 刷新页面时恢复认证状态
  const initAuth = () => {
    loadTokenFromStorage()
  }

  return {
    user,
    token,
    isLoading,
    error,
    login,
    logout,
    hasPermission,
    initAuth,
  }
}

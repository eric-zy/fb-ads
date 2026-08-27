import { ref, computed } from 'vue'
import axios from 'axios'

interface Account {
  id: string
  account_id: string
  account_name: string
  currency: string
  status: string
  daily_spend_limit: number
  risk_score: number
}

export const useAccounts = () => {
  const accounts = ref<Account[]>([])
  const selectedAccount = ref<Account | null>(null)
  const isLoading = ref(false)
  const error = ref<string>('')

  // 获取账户列表
  const fetchAccounts = async (userId: string) => {
    isLoading.value = true
    error.value = ''
    
    try {
      const response = await axios.get(`/api/v1/users/${userId}/accounts`)
      accounts.value = response.data.accounts
      
      // 自动选择第一个账户
      if (accounts.value.length > 0 && !selectedAccount.value) {
        selectedAccount.value = accounts.value[0]
      }
    } catch (err: any) {
      error.value = err.response?.data?.detail || '获取账户列表失败'
    } finally {
      isLoading.value = false
    }
  }

  // 选择账户
  const selectAccount = (account: Account) => {
    selectedAccount.value = account
    localStorage.setItem('selected_account', JSON.stringify(account))
  }

  // 获取账户详情
  const getAccountDetail = async (accountId: string) => {
    try {
      const response = await axios.get(`/api/v1/accounts/${accountId}/account-health-check`)
      return response.data
    } catch (err) {
      error.value = '获取账户详情失败'
      return null
    }
  }

  // 获取账户风险状态
  const getAccountRiskStatus = async (accountId: string) => {
    try {
      const response = await axios.get(`/api/v1/accounts/${accountId}/risk-events`)
      return response.data
    } catch (err) {
      error.value = '获取风险状态失败'
      return null
    }
  }

  return {
    accounts,
    selectedAccount,
    isLoading,
    error,
    fetchAccounts,
    selectAccount,
    getAccountDetail,
    getAccountRiskStatus,
  }
}

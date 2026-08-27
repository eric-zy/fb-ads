// 账户store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export interface Account {
  id: string
  account_id: string
  account_name: string
  currency: string
  status: string
  daily_spend_limit: number
  risk_score: number
  is_frozen: boolean
}

export const useAccountStore = defineStore('account', () => {
  const accounts = ref<Account[]>([])
  const selectedAccountId = ref<string>('')
  const isLoading = ref(false)

  const selectedAccount = computed(() => {
    return accounts.value.find(a => a.id === selectedAccountId.value) || null
  })

  const activeAccounts = computed(() => {
    return accounts.value.filter(a => a.status === 'active' && !a.is_frozen)
  })

  // 获取账户列表
  const fetchAccounts = async (userId: string) => {
    isLoading.value = true
    try {
      const response = await axios.get(`/api/v1/users/${userId}/accounts`)
      accounts.value = response.data.accounts || []
      
      // 自动选择第一个账户
      if (accounts.value.length > 0 && !selectedAccountId.value) {
        selectedAccountId.value = accounts.value[0].id
      }
    } catch (error) {
      console.error('Fetch accounts error:', error)
    } finally {
      isLoading.value = false
    }
  }

  // 选择账户
  const selectAccount = (accountId: string) => {
    selectedAccountId.value = accountId
    localStorage.setItem('selected_account_id', accountId)
  }

  // 恢复选中账户
  const restoreSelectedAccount = () => {
    const saved = localStorage.getItem('selected_account_id')
    if (saved && accounts.value.some(a => a.id === saved)) {
      selectedAccountId.value = saved
    }
  }

  return {
    accounts,
    selectedAccountId,
    selectedAccount,
    activeAccounts,
    isLoading,
    fetchAccounts,
    selectAccount,
    restoreSelectedAccount,
  }
})

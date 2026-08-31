// 账户store
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'
import type { AdAccountItem } from '@/api/admin'

// 复用统一的账户类型：/api/v1/users/{id}/accounts 与 /api/v1/accounts
// 现在共用后端 account_to_dict()，避免"同一资源两套字段契约"
export type Account = AdAccountItem

export const useAccountStore = defineStore('account', () => {
  const accounts = ref<Account[]>([])
  const selectedAccountId = ref<string>('')
  const isLoading = ref(false)

  const selectedAccount = computed(() => {
    return accounts.value.find(a => a.id === selectedAccountId.value) || null
  })

  const activeAccounts = computed(() => {
    return accounts.value.filter(a => a.system_status === 'ACTIVE')
  })

  // 获取账户列表
  const fetchAccounts = async (userId: string) => {
    isLoading.value = true
    try {
      const response = await request.get(`/api/v1/users/${userId}/accounts`)
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

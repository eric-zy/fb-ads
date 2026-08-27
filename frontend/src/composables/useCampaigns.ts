import { ref, computed } from 'vue'
import axios from 'axios'
import dayjs from 'dayjs'

export interface Campaign {
  id: string
  campaign_id: string
  name: string
  status: string
  objective: string
  budget?: number
  daily_budget?: number
  spend: number
  impressions: number
  clicks: number
  ctr: number
  cpc: number
  cpm: number
  start_time?: string
  stop_time?: string
}

export interface BatchPublishConfig {
  account_id: string
  campaigns: Campaign[]
  publish_type: 'immediate' | 'scheduled' | 'staggered'
  start_time?: string
  interval_minutes?: number
  max_daily_campaigns?: number
  enable_risk_check: boolean
  enable_frequency_check: boolean
  notify_on_complete: boolean
  notify_email?: string
}

export const useCampaigns = () => {
  const campaigns = ref<Campaign[]>([])
  const selectedCampaigns = ref<Campaign[]>([])
  const isLoading = ref(false)
  const error = ref<string>('')

  // 获取系列列表
  const fetchCampaigns = async (accountId: string) => {
    isLoading.value = true
    error.value = ''
    
    try {
      const response = await axios.get(`/api/v1/accounts/${accountId}/campaigns`)
      campaigns.value = response.data.campaigns || []
    } catch (err: any) {
      error.value = err.response?.data?.detail || '获取系列列表失败'
    } finally {
      isLoading.value = false
    }
  }

  // 获取系列性能数据
  const getCampaignPerformance = async (accountId: string, days: number = 30) => {
    try {
      const response = await axios.get(
        `/api/v1/accounts/${accountId}/performance?days=${days}`
      )
      return response.data
    } catch (err) {
      error.value = '获取性能数据失败'
      return null
    }
  }

  // 选择系列
  const toggleCampaign = (campaign: Campaign) => {
    const index = selectedCampaigns.value.findIndex(c => c.id === campaign.id)
    if (index > -1) {
      selectedCampaigns.value.splice(index, 1)
    } else {
      selectedCampaigns.value.push(campaign)
    }
  }

  // 批量投放
  const batchPublish = async (config: BatchPublishConfig) => {
    isLoading.value = true
    error.value = ''
    
    try {
      const response = await axios.post('/api/v1/campaigns/batch-publish', config)
      return response.data
    } catch (err: any) {
      error.value = err.response?.data?.detail || '批量投放失败'
      return null
    } finally {
      isLoading.value = false
    }
  }

  // 暂停系列
  const pauseCampaign = async (campaignId: string) => {
    try {
      const response = await axios.post(
        `/api/v1/campaigns/${campaignId}/pause`
      )
      return response.data
    } catch (err) {
      error.value = '暂停系列失败'
      return null
    }
  }

  // 恢复系列
  const resumeCampaign = async (campaignId: string) => {
    try {
      const response = await axios.post(
        `/api/v1/campaigns/${campaignId}/resume`
      )
      return response.data
    } catch (err) {
      error.value = '恢复系列失败'
      return null
    }
  }

  // 同步系列
  const syncCampaigns = async (accountId: string) => {
    try {
      const response = await axios.post(`/api/v1/accounts/${accountId}/sync`)
      await fetchCampaigns(accountId)
      return response.data
    } catch (err) {
      error.value = '同步系列失败'
      return null
    }
  }

  // 获取推荐的发布间隔
  const getPublishInterval = async (accountId: string) => {
    try {
      const response = await axios.get(
        `/api/v1/accounts/${accountId}/safe-publish-interval`
      )
      return response.data
    } catch (err) {
      return null
    }
  }

  // 检查发布频次
  const checkPublishFrequency = async (accountId: string, hours: number = 24) => {
    try {
      const response = await axios.get(
        `/api/v1/accounts/${accountId}/publish-frequency-check?hours=${hours}`
      )
      return response.data
    } catch (err) {
      return null
    }
  }

  return {
    campaigns,
    selectedCampaigns,
    isLoading,
    error,
    fetchCampaigns,
    getCampaignPerformance,
    toggleCampaign,
    batchPublish,
    pauseCampaign,
    resumeCampaign,
    syncCampaigns,
    getPublishInterval,
    checkPublishFrequency,
  }
}

import { ref } from 'vue'
import axios from 'axios'

export interface ScheduledTask {
  id: string
  account_id: string
  task_type: string
  status: string
  publish_type: 'immediate' | 'scheduled' | 'staggered'
  start_time?: string
  interval_minutes?: number
  max_daily_campaigns?: number
  created_at: string
  updated_at: string
  execution_count: number
  last_execution?: string
  next_execution?: string
}

export const useScheduledTasks = () => {
  const tasks = ref<ScheduledTask[]>([])
  const isLoading = ref(false)
  const error = ref<string>('')

  // 获取定时任务列表
  const fetchTasks = async (accountId: string) => {
    isLoading.value = true
    error.value = ''
    
    try {
      const response = await axios.get(`/api/v1/accounts/${accountId}/scheduled-tasks`)
      tasks.value = response.data.tasks || []
    } catch (err: any) {
      error.value = err.response?.data?.detail || '获取任务列表失败'
    } finally {
      isLoading.value = false
    }
  }

  // 创建定时任务
  const createTask = async (taskConfig: any) => {
    isLoading.value = true
    error.value = ''
    
    try {
      const response = await axios.post('/api/v1/scheduled-tasks', taskConfig)
      await fetchTasks(taskConfig.account_id)
      return response.data
    } catch (err: any) {
      error.value = err.response?.data?.detail || '创建任务失败'
      return null
    } finally {
      isLoading.value = false
    }
  }

  // 更新任务
  const updateTask = async (taskId: string, updates: any) => {
    try {
      const response = await axios.put(`/api/v1/scheduled-tasks/${taskId}`, updates)
      return response.data
    } catch (err: any) {
      error.value = err.response?.data?.detail || '更新任务失败'
      return null
    }
  }

  // 删除任务
  const deleteTask = async (taskId: string) => {
    try {
      await axios.delete(`/api/v1/scheduled-tasks/${taskId}`)
      tasks.value = tasks.value.filter(t => t.id !== taskId)
      return true
    } catch (err: any) {
      error.value = err.response?.data?.detail || '删除任务失败'
      return false
    }
  }

  // 暂停任务
  const pauseTask = async (taskId: string) => {
    try {
      const response = await axios.post(`/api/v1/scheduled-tasks/${taskId}/pause`)
      return response.data
    } catch (err) {
      error.value = '暂停任务失败'
      return null
    }
  }

  // 恢复任务
  const resumeTask = async (taskId: string) => {
    try {
      const response = await axios.post(`/api/v1/scheduled-tasks/${taskId}/resume`)
      return response.data
    } catch (err) {
      error.value = '恢复任务失败'
      return null
    }
  }

  // 立即执行任务
  const executeTask = async (taskId: string) => {
    try {
      const response = await axios.post(`/api/v1/scheduled-tasks/${taskId}/execute`)
      return response.data
    } catch (err) {
      error.value = '执行任务失败'
      return null
    }
  }

  return {
    tasks,
    isLoading,
    error,
    fetchTasks,
    createTask,
    updateTask,
    deleteTask,
    pauseTask,
    resumeTask,
    executeTask,
  }
}

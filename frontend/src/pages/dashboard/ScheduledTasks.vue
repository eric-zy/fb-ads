<template>
  <div class="scheduled-tasks-page">
    <el-row :gutter="20" class="header-row">
      <el-col :span="24">
        <div class="header-actions">
          <el-button type="primary" @click="goToBatchPublish">
            <el-icon><Plus /></el-icon>
            创建定时任务
          </el-button>
          <el-space>
            <el-select v-model="filterStatus" placeholder="筛选状态" clearable>
              <el-option label="运行中" value="running" />
              <el-option label="已暂停" value="paused" />
              <el-option label="已完成" value="completed" />
            </el-select>
          </el-space>
        </div>
      </el-col>
    </el-row>

    <el-table
      :data="filteredTasks"
      style="width: 100%; margin-top: 20px"
      :loading="isLoading"
    >
      <el-table-column prop="id" label="任务ID" width="150" />
      <el-table-column prop="task_type" label="类型" width="100" />
      <el-table-column prop="publish_type" label="投放方式" width="100">
        <template #default="{ row }">
          <el-tag>{{ getPublishTypeLabel(row.publish_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="getStatusType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="execution_count" label="执行次数" width="100" />
      <el-table-column prop="start_time" label="开始时间" width="150" />
      <el-table-column prop="next_execution" label="下次执行" width="150" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button-group>
            <el-button
              v-if="row.status === 'paused'"
              type="success"
              text
              size="small"
              @click="handleResumeTask(row)"
            >
              继续
            </el-button>
            <el-button
              v-else-if="row.status === 'running'"
              type="warning"
              text
              size="small"
              @click="handlePauseTask(row)"
            >
              暂停
            </el-button>
            <el-button
              type="primary"
              text
              size="small"
              @click="handleExecuteTask(row)"
            >
              立即执行
            </el-button>
            <el-popconfirm
              confirm-button-text="确定"
              cancel-button-text="取消"
              icon-color="#f56c6c"
              title="确定删除该任务吗?"
              @confirm="handleDeleteTask(row)"
            >
              <template #reference>
                <el-button type="danger" text size="small">删除</el-button>
              </template>
            </el-popconfirm>
          </el-button-group>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useScheduledTasks } from '@/composables/useScheduledTasks'
import { useAccountStore } from '@/stores/accountStore'

const router = useRouter()
const accountStore = useAccountStore()
const { tasks, fetchTasks, pauseTask, resumeTask, executeTask, deleteTask } =
  useScheduledTasks()

const filterStatus = ref<string>('')
const isLoading = ref(false)

const filteredTasks = computed(() => {
  if (!filterStatus.value) return tasks.value
  return tasks.value.filter(t => t.status === filterStatus.value)
})

const getStatusType = (status: string) => {
  const typeMap: Record<string, string> = {
    running: 'success',
    paused: 'warning',
    completed: 'info',
    failed: 'danger',
  }
  return typeMap[status] || 'info'
}

const getPublishTypeLabel = (type: string) => {
  const labels: Record<string, string> = {
    immediate: '立即投放',
    scheduled: '定时投放',
    staggered: '分散投放',
  }
  return labels[type] || type
}

const handlePauseTask = async (row: any) => {
  const result = await pauseTask(row.id)
  if (result) {
    ElMessage.success('任务已暂停')
    await loadTasks()
  }
}

const handleResumeTask = async (row: any) => {
  const result = await resumeTask(row.id)
  if (result) {
    ElMessage.success('任务已恢复')
    await loadTasks()
  }
}

const handleExecuteTask = async (row: any) => {
  const result = await executeTask(row.id)
  if (result) {
    ElMessage.success('任务已执行')
    await loadTasks()
  }
}

const handleDeleteTask = async (row: any) => {
  const success = await deleteTask(row.id)
  if (success) {
    ElMessage.success('任务已删除')
    await loadTasks()
  }
}

const goToBatchPublish = () => {
  router.push('/dashboard/batch-publish')
}

const loadTasks = async () => {
  if (!accountStore.selectedAccount) return
  isLoading.value = true
  try {
    await fetchTasks(accountStore.selectedAccount.id)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  loadTasks()
})
</script>

<style scoped lang="scss">
.scheduled-tasks-page {
  .header-row {
    margin-bottom: 20px;

    .header-actions {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }
}
</style>

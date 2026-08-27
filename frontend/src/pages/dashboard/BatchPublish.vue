<template>
  <div class="batch-publish-page">
    <el-row :gutter="20">
      <!-- 左侧：系列选择 -->
      <el-col :xs="24" :md="12">
        <el-card class="selection-card">
          <template #header>
            <div class="card-header">
              <span>选择要投放的广告系列</span>
              <el-button
                type="text"
                @click="syncCampaigns"
                :loading="syncing"
              >
                同步系列
              </el-button>
            </div>
          </template>

          <el-tree
            ref="campaignTree"
            :data="campaignTreeData"
            node-key="id"
            show-checkbox
            @check="handleCampaignCheck"
            :props="{ children: 'children', label: 'label' }"
            default-expand-all
          />

          <div class="selected-stats">
            <p>已选择: {{ selectedCampaigns.length }} 个系列</p>
            <el-button
              v-if="selectedCampaigns.length > 0"
              type="danger"
              text
              @click="clearSelection"
            >
              清空选择
            </el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧：投放配置 -->
      <el-col :xs="24" :md="12">
        <el-card class="config-card">
          <template #header>
            <div class="card-header">
              <span>投放配置</span>
            </div>
          </template>

          <el-form
            ref="configForm"
            :model="publishConfig"
            :rules="configRules"
            label-width="120px"
          >
            <!-- 投放方式 -->
            <el-form-item label="投放方式" prop="publish_type">
              <el-radio-group v-model="publishConfig.publish_type">
                <el-radio label="immediate">立即投放</el-radio>
                <el-radio label="scheduled">定时投放</el-radio>
                <el-radio label="staggered">分散投放</el-radio>
              </el-radio-group>
            </el-form-item>

            <!-- 开始时间 -->
            <el-form-item
              v-if="publishConfig.publish_type !== 'immediate'"
              label="开始时间"
              prop="start_time"
            >
              <el-date-picker
                v-model="publishConfig.start_time"
                type="datetime"
                placeholder="选择开始时间"
                format="YYYY-MM-DD HH:mm:ss"
              />
            </el-form-item>

            <!-- 投放间隔 -->
            <el-form-item
              v-if="publishConfig.publish_type === 'staggered'"
              label="投放间隔(分钟)"
              prop="interval_minutes"
            >
              <el-input
                v-model.number="publishConfig.interval_minutes"
                type="number"
                min="5"
                max="1440"
              />
              <div class="form-tip">建议间隔: {{ suggestedInterval }} 分钟</div>
            </el-form-item>

            <!-- 每日最大投放数 -->
            <el-form-item label="每日最大投放数" prop="max_daily_campaigns">
              <el-input
                v-model.number="publishConfig.max_daily_campaigns"
                type="number"
                min="1"
                max="50"
              />
            </el-form-item>

            <!-- 风险检测 -->
            <el-form-item label="风险检测">
              <el-switch v-model="publishConfig.enable_risk_check" />
              <span class="form-tip">启用后会自动检测账户风险</span>
            </el-form-item>

            <!-- 频次检测 -->
            <el-form-item label="频次检测">
              <el-switch v-model="publishConfig.enable_frequency_check" />
              <span class="form-tip">启用后会检查投放频次限制</span>
            </el-form-item>

            <!-- 完成通知 -->
            <el-form-item label="完成时通知">
              <el-switch v-model="publishConfig.notify_on_complete" />
            </el-form-item>

            <el-form-item
              v-if="publishConfig.notify_on_complete"
              label="通知邮箱"
              prop="notify_email"
            >
              <el-input
                v-model="publishConfig.notify_email"
                placeholder="请输入邮箱地址"
              />
            </el-form-item>

            <!-- 操作按钮 -->
            <el-form-item>
              <el-button
                type="primary"
                :disabled="selectedCampaigns.length === 0"
                :loading="publishing"
                @click="submitPublish"
              >
                确认投放
              </el-button>
              <el-button @click="resetForm">重置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCampaigns } from '@/composables/useCampaigns'
import { useAccountStore } from '@/stores/accountStore'
import type { FormInstance } from 'element-plus'

const accountStore = useAccountStore()
const { campaigns, fetchCampaigns, batchPublish, checkPublishFrequency, getPublishInterval } =
  useCampaigns()

const configForm = ref<FormInstance>()
const campaignTree = ref()
const syncing = ref(false)
const publishing = ref(false)
const selectedCampaigns = ref<any[]>([])
const suggestedInterval = ref(30)

const publishConfig = ref({
  publish_type: 'immediate',
  start_time: undefined,
  interval_minutes: 30,
  max_daily_campaigns: 10,
  enable_risk_check: true,
  enable_frequency_check: true,
  notify_on_complete: false,
  notify_email: '',
})

const configRules = {
  publish_type: [{ required: true, message: '请选择投放方式' }],
  start_time: [{ required: true, message: '请选择开始时间' }],
  interval_minutes: [{ required: true, message: '请输入投放间隔' }],
  max_daily_campaigns: [{ required: true, message: '请输入每日最大投放数' }],
  notify_email: [
    {
      type: 'email',
      message: '请输入正确的邮箱地址',
      trigger: 'blur',
    },
  ],
}

const campaignTreeData = computed(() => {
  const grouped: Record<string, any> = {}
  campaigns.value.forEach(campaign => {
    const objective = campaign.objective || 'Other'
    if (!grouped[objective]) {
      grouped[objective] = {
        id: objective,
        label: objective,
        children: [],
      }
    }
    grouped[objective].children.push({
      id: campaign.id,
      label: campaign.name,
      campaign,
    })
  })
  return Object.values(grouped)
})

const handleCampaignCheck = (node: any) => {
  const checkedNodes = campaignTree.value?.getCheckedNodes()
  selectedCampaigns.value = checkedNodes?.filter((n: any) => n.campaign) || []
}

const syncCampaigns = async () => {
  if (!accountStore.selectedAccount) return
  syncing.value = true
  try {
    await fetchCampaigns(accountStore.selectedAccount.id)
    ElMessage.success('系列已同步')
  } finally {
    syncing.value = false
  }
}

const clearSelection = () => {
  selectedCampaigns.value = []
  campaignTree.value?.setCheckedNodes([])
}

const submitPublish = async () => {
  if (!configForm.value) return
  if (!accountStore.selectedAccount) {
    ElMessage.error('请先选择账户')
    return
  }

  try {
    await configForm.value.validate()

    // 风险检测
    if (publishConfig.value.enable_risk_check) {
      const riskCheck = await checkPublishFrequency(
        accountStore.selectedAccount.id,
        24
      )
      if (riskCheck?.frequency_report?.frequency_status === 'critical') {
        await ElMessageBox.confirm(
          '检测到高风险发布频次，是否继续？',
          '风险提示',
          { confirmButtonText: '继续', cancelButtonText: '取消' }
        )
      }
    }

    // 获取推荐间隔
    if (publishConfig.value.publish_type === 'staggered') {
      const interval = await getPublishInterval(
        accountStore.selectedAccount.id
      )
      if (interval?.recommended_interval_seconds) {
        suggestedInterval.value = Math.ceil(
          interval.recommended_interval_seconds / 60
        )
      }
    }

    publishing.value = true
    const config = {
      account_id: accountStore.selectedAccount.id,
      campaigns: selectedCampaigns.value.map((n: any) => n.campaign),
      ...publishConfig.value,
    }

    const result = await batchPublish(config)
    if (result) {
      ElMessage.success('投放任务已创建')
      clearSelection()
      resetForm()
    }
  } catch (error: any) {
    if (error.response?.status !== 401) {
      ElMessage.error(error.message || '投放失败')
    }
  } finally {
    publishing.value = false
  }
}

const resetForm = () => {
  publishConfig.value = {
    publish_type: 'immediate',
    start_time: undefined,
    interval_minutes: 30,
    max_daily_campaigns: 10,
    enable_risk_check: true,
    enable_frequency_check: true,
    notify_on_complete: false,
    notify_email: '',
  }
}

onMounted(() => {
  if (accountStore.selectedAccount) {
    fetchCampaigns(accountStore.selectedAccount.id)
  }
})
</script>

<style scoped lang="scss">
.batch-publish-page {
  .selection-card,
  .config-card {
    min-height: 500px;

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  }

  .selected-stats {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid #e4e7eb;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .form-tip {
    margin-left: 10px;
    color: #909399;
    font-size: 12px;
  }
}
</style>

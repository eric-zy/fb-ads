<template>
  <div class="templates-page">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">投放模板</h2>
            <p class="page-desc">
              投放模板是系统最核心的业务对象：配置一次，即可批量部署到任意数量的广告账户。
              模板保存目标、预算、定向与素材文案，部署时按「模板 → 账户」生成 Campaign / AdSet / Ad。
            </p>
          </div>
          <el-button type="primary" @click="openCreate">新建模板</el-button>
        </div>
      </template>

      <el-table :data="templates" v-loading="loading" size="small">
        <el-table-column prop="name" label="模板名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="objective" label="目标" width="150" show-overflow-tooltip />
        <el-table-column label="预算" width="140">
          <template #default="{ row }">
            <span v-if="row.budget_type === 'LIFETIME'">
              ${{ row.lifetime_budget ?? '-' }} 总
            </span>
            <span v-else>${{ row.daily_budget ?? '-' }}/天</span>
          </template>
        </el-table-column>
        <el-table-column prop="optimization_goal" label="优化目标" width="160" show-overflow-tooltip />
        <el-table-column label="定向" width="120">
          <template #default="{ row }">
            <span>{{ geoSummary(row.targeting_json) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创意数" width="90">
          <template #default="{ row }">
            {{ creativeCount(row.creative_config_json) }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="handleClone(row)">复制</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建 / 编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑模板' : '新建模板'"
      width="720px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="120px">
        <el-divider content-position="left">基本信息</el-divider>
        <el-form-item label="模板名称" required>
          <el-input v-model="form.name" placeholder="如 US Sales V1" />
        </el-form-item>
        <el-form-item label="推广目标">
          <el-select v-model="form.objective" filterable allow-create style="width: 100%">
            <el-option label="销售 (OUTCOME_SALES)" value="OUTCOME_SALES" />
            <el-option label="流量 (OUTCOME_TRAFFIC)" value="OUTCOME_TRAFFIC" />
            <el-option label="互动 (OUTCOME_ENGAGEMENT)" value="OUTCOME_ENGAGEMENT" />
            <el-option label="潜在客户 (OUTCOME_LEADS)" value="OUTCOME_LEADS" />
            <el-option label="知名度 (OUTCOME_AWARENESS)" value="OUTCOME_AWARENESS" />
          </el-select>
        </el-form-item>
        <el-form-item label="购买类型">
          <el-input v-model="form.buying_type" placeholder="AUCTION" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="启用 ACTIVE" value="ACTIVE" />
            <el-option label="停用 DISABLED" value="DISABLED" />
            <el-option label="归档 ARCHIVED" value="ARCHIVED" />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">预算</el-divider>
        <el-form-item label="预算类型">
          <el-select v-model="form.budget_type" style="width: 100%">
            <el-option label="日预算 DAILY" value="DAILY" />
            <el-option label="总预算 LIFETIME" value="LIFETIME" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.budget_type === 'DAILY'" label="日预算(美元)">
          <el-input-number v-model="form.daily_budget" :min="0" :step="10" />
        </el-form-item>
        <el-form-item v-else label="总预算(美元)">
          <el-input-number v-model="form.lifetime_budget" :min="0" :step="100" />
        </el-form-item>

        <el-divider content-position="left">优化与计费</el-divider>
        <el-form-item label="优化目标">
          <el-select v-model="form.optimization_goal" filterable allow-create style="width: 100%">
            <el-option label="链接点击 LINK_CLICKS" value="LINK_CLICKS" />
            <el-option label="站外转化 OFFSITE_CONVERSIONS" value="OFFSITE_CONVERSIONS" />
            <el-option label="展示 IMPRESSIONS" value="IMPRESSIONS" />
            <el-option label="覆盖 REACH" value="REACH" />
            <el-option label="落地页浏览 LANDING_PAGE_VIEWS" value="LANDING_PAGE_VIEWS" />
          </el-select>
        </el-form-item>
        <el-form-item label="计费事件">
          <el-select v-model="form.billing_event" filterable allow-create style="width: 100%">
            <el-option label="展示 IMPRESSIONS" value="IMPRESSIONS" />
            <el-option label="链接点击 LINK_CLICKS" value="LINK_CLICKS" />
          </el-select>
        </el-form-item>
        <el-form-item label="出价策略">
          <el-input v-model="form.bid_strategy" placeholder="可留空，如 LOWEST_COST_WITHOUT_CAP" />
        </el-form-item>

        <el-divider content-position="left">定向与创意（JSON）</el-divider>
        <el-form-item label="定向配置">
          <el-input
            v-model="form.targeting_json"
            type="textarea"
            :rows="4"
            placeholder='{"geo_locations":{"countries":["US"]},"age_min":18,"age_max":65,"genders":[1,2]}'
          />
        </el-form-item>
        <el-form-item label="创意配置">
          <el-input
            v-model="form.creative_config_json"
            type="textarea"
            :rows="7"
            placeholder='{"page_id":"","creatives":[{"headline":"","primary_text":"","cta":"LEARN_MORE","landing_url":""}]}'
          />
          <div class="tip">
            结构：{ page_id, creatives: [{ headline, primary_text, description, cta, landing_url, image_hash | video_id, asset_id }] }
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { templatesApi, type CampaignTemplate } from '@/api/templates'

const templates = ref<CampaignTemplate[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const editingId = ref('')

const DEFAULT_TARGETING = JSON.stringify(
  { geo_locations: { countries: ['US'] }, age_min: 18, age_max: 65, genders: [1, 2] },
  null,
  2
)
const DEFAULT_CREATIVE = JSON.stringify(
  {
    page_id: '',
    creatives: [
      { headline: '', primary_text: '', description: '', cta: 'LEARN_MORE', landing_url: '' },
    ],
  },
  null,
  2
)

const form = reactive({
  name: '',
  objective: 'OUTCOME_SALES',
  buying_type: 'AUCTION',
  status: 'ACTIVE',
  budget_type: 'DAILY',
  daily_budget: 50,
  lifetime_budget: 0,
  optimization_goal: 'LINK_CLICKS',
  billing_event: 'IMPRESSIONS',
  bid_strategy: '',
  targeting_json: DEFAULT_TARGETING,
  creative_config_json: DEFAULT_CREATIVE,
})

const loadTemplates = async () => {
  loading.value = true
  try {
    const { data } = await templatesApi.list()
    templates.value = data
  } finally {
    loading.value = false
  }
}

const resetForm = () => {
  isEdit.value = false
  editingId.value = ''
  form.name = ''
  form.objective = 'OUTCOME_SALES'
  form.buying_type = 'AUCTION'
  form.status = 'ACTIVE'
  form.budget_type = 'DAILY'
  form.daily_budget = 50
  form.lifetime_budget = 0
  form.optimization_goal = 'LINK_CLICKS'
  form.billing_event = 'IMPRESSIONS'
  form.bid_strategy = ''
  form.targeting_json = DEFAULT_TARGETING
  form.creative_config_json = DEFAULT_CREATIVE
}

const openCreate = () => {
  resetForm()
  dialogVisible.value = true
}

const openEdit = (row: CampaignTemplate) => {
  isEdit.value = true
  editingId.value = row.id
  form.name = row.name
  form.objective = row.objective || 'OUTCOME_SALES'
  form.buying_type = row.buying_type || 'AUCTION'
  form.status = row.status || 'ACTIVE'
  form.budget_type = row.budget_type || 'DAILY'
  form.daily_budget = row.daily_budget ?? 50
  form.lifetime_budget = row.lifetime_budget ?? 0
  form.optimization_goal = row.optimization_goal || 'LINK_CLICKS'
  form.billing_event = row.billing_event || 'IMPRESSIONS'
  form.bid_strategy = row.bid_strategy || ''
  form.targeting_json = JSON.stringify(row.targeting_json ?? {}, null, 2)
  form.creative_config_json = JSON.stringify(row.creative_config_json ?? {}, null, 2)
  dialogVisible.value = true
}

// 解析 JSON 字段，失败时提示
const parseJsonField = (text: string, label: string) => {
  if (!text || !text.trim()) return {}
  try {
    return JSON.parse(text)
  } catch (e) {
    ElMessage.error(`${label} 不是合法的 JSON，请检查后重试`)
    throw new Error(`invalid json: ${label}`)
  }
}

const submit = async () => {
  if (!form.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }

  let targeting: Record<string, any>
  let creative: Record<string, any>
  try {
    targeting = parseJsonField(form.targeting_json, '定向配置')
    creative = parseJsonField(form.creative_config_json, '创意配置')
  } catch {
    return
  }

  saving.value = true
  try {
    const payload = {
      name: form.name,
      objective: form.objective,
      buying_type: form.buying_type,
      status: form.status,
      budget_type: form.budget_type,
      daily_budget: form.budget_type === 'DAILY' ? form.daily_budget : undefined,
      lifetime_budget: form.budget_type === 'LIFETIME' ? form.lifetime_budget : undefined,
      optimization_goal: form.optimization_goal,
      billing_event: form.billing_event,
      bid_strategy: form.bid_strategy || undefined,
      targeting_json: targeting,
      creative_config_json: creative,
    }

    if (isEdit.value) {
      await templatesApi.update(editingId.value, payload)
      ElMessage.success('模板已更新')
    } else {
      await templatesApi.create(payload as any)
      ElMessage.success('模板已创建')
    }

    dialogVisible.value = false
    await loadTemplates()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    saving.value = false
  }
}

const handleClone = async (row: CampaignTemplate) => {
  try {
    await templatesApi.clone(row.id)
    ElMessage.success('模板已复制')
    await loadTemplates()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const handleDelete = async (row: CampaignTemplate) => {
  try {
    await ElMessageBox.confirm(
      `确定删除模板「${row.name}」？该操作为软删除（置为 ARCHIVED），已部署的实例不受影响。`,
      '删除确认',
      { type: 'warning' }
    )
  } catch {
    return // 用户取消
  }

  try {
    await templatesApi.remove(row.id)
    ElMessage.success('模板已删除')
    await loadTemplates()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

// 摘要展示
const geoSummary = (targeting: any) => {
  const countries = targeting?.geo_locations?.countries
  if (!countries?.length) return '-'
  return countries.slice(0, 3).join(', ') + (countries.length > 3 ? ' …' : '')
}

const creativeCount = (cfg: any) => {
  if (Array.isArray(cfg?.creatives)) return cfg.creatives.length
  return cfg && Object.keys(cfg).length ? 1 : 0
}

onMounted(loadTemplates)
</script>

<style scoped lang="scss">
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;

  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; max-width: 760px; }
}
.tip { color: #909399; font-size: 12px; margin-top: 4px; line-height: 1.5; }
</style>

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
      <el-steps :active="templateStep" simple class="template-steps">
        <el-step title="基础信息" />
        <el-step title="广告系列" />
        <el-step title="广告组与定向" />
        <el-step title="广告创意" />
      </el-steps>
      <el-form :model="form" label-width="120px">
        <section v-if="templateStep === 0">
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
        <el-form-item label="特殊广告类别">
          <el-checkbox-group v-model="form.special_ad_categories">
            <el-checkbox label="HOUSING">住房</el-checkbox>
            <el-checkbox label="EMPLOYMENT">就业</el-checkbox>
            <el-checkbox label="CREDIT">信贷</el-checkbox>
            <el-checkbox label="ISSUES_ELECTIONS_POLITICS">社会议题/选举/政治</el-checkbox>
          </el-checkbox-group>
          <div class="tip">如广告涉及以上类别，必须选择对应类别；不涉及则保持为空。</div>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" style="width: 100%">
            <el-option label="启用 ACTIVE" value="ACTIVE" />
            <el-option label="停用 DISABLED" value="DISABLED" />
            <el-option label="归档 ARCHIVED" value="ARCHIVED" />
          </el-select>
        </el-form-item>

        </section>
        <section v-if="templateStep === 1">
        <el-divider content-position="left">广告系列与预算</el-divider>
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
        <el-form-item label="广告组预算共享">
          <el-switch v-model="form.is_adset_budget_sharing_enabled" />
          <span class="tip-inline">关闭时使用广告组独立预算；Meta 要求明确传入 True/False</span>
        </el-form-item>
        <template v-if="form.budget_type === 'LIFETIME'">
          <el-form-item label="开始时间">
            <el-date-picker v-model="form.schedule_start" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="可选，默认立即开始" style="width:100%" />
          </el-form-item>
          <el-form-item label="结束时间" required>
            <el-date-picker v-model="form.schedule_end" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="总预算必须设置结束时间" style="width:100%" />
          </el-form-item>
        </template>

        </section>
        <section v-if="templateStep === 2">
        <el-divider content-position="left">广告组优化与定向</el-divider>
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
        <template v-if="['OFFSITE_CONVERSIONS', 'VALUE'].includes(form.optimization_goal)">
          <el-form-item label="Pixel ID" required>
            <el-input v-model="form.pixel_id" placeholder="Meta Pixel ID" />
          </el-form-item>
          <el-form-item label="转化事件" required>
            <el-input v-model="form.custom_event_type" placeholder="例如 PURCHASE / LEAD" />
          </el-form-item>
        </template>
        <el-divider content-position="left">受众定向</el-divider>
        <el-form-item label="国家/地区">
          <el-input v-model="targetingForm.countries" placeholder="多个国家用逗号分隔，例如 US,CA,GB" />
        </el-form-item>
        <el-form-item label="年龄范围">
          <div class="inline-fields"><el-input-number v-model="targetingForm.age_min" :min="13" :max="65" /><span>至</span><el-input-number v-model="targetingForm.age_max" :min="13" :max="65" /></div>
        </el-form-item>
        <el-form-item label="性别">
          <el-checkbox-group v-model="targetingForm.genders"><el-checkbox :label="1">男性</el-checkbox><el-checkbox :label="2">女性</el-checkbox></el-checkbox-group>
        </el-form-item>
        <el-form-item label="兴趣">
          <el-input v-model="targetingForm.interests" placeholder="多个兴趣用逗号分隔（可选）" />
        </el-form-item>
        <el-form-item label="版位">
          <el-select v-model="targetingForm.placements" multiple collapse-tags style="width:100%" placeholder="默认自动版位">
            <el-option label="Facebook 信息流" value="facebook_feed" />
            <el-option label="Instagram 信息流" value="instagram_stream" />
            <el-option label="Facebook 快拍" value="facebook_story" />
            <el-option label="Instagram 快拍" value="instagram_story" />
          </el-select>
        </el-form-item>

        </section>
        <section v-if="templateStep === 3">
        <el-divider content-position="left">广告创意</el-divider>
        <el-form-item label="Facebook 页面" required>
          <el-select v-model="creativeForm.page_id" filterable style="width:100%" placeholder="选择已授权的 Facebook 页面">
            <el-option v-for="page in metaPages" :key="page.page_id" :label="`${page.page_name} (${page.page_id})`" :value="page.page_id" />
          </el-select>
          <div v-if="!metaPages.length" class="tip">暂无已同步页面，请先完成 Meta OAuth 授权后刷新页面。</div>
        </el-form-item>
        <div v-for="(creative, index) in creativeForm.creatives" :key="index" class="creative-block">
          <div class="creative-head"><b>创意 {{ index + 1 }}</b><el-button v-if="creativeForm.creatives.length > 1" link type="danger" @click="removeCreative(index)">删除</el-button></div>
          <el-form-item label="素材类型">
            <el-radio-group v-model="creative.asset_type"><el-radio value="image">图片</el-radio><el-radio value="video">视频</el-radio></el-radio-group>
          </el-form-item>
          <el-form-item label="素材库素材" required>
            <el-select v-model="creative.asset_id" filterable style="width:100%" placeholder="选择已上传素材">
              <el-option v-for="asset in availableAssets(creative.asset_type)" :key="asset.id" :label="asset.name" :value="asset.id">
                <span>{{ asset.name }}</span><small class="asset-option-meta">{{ asset.asset_type === 'image' ? '图片' : '视频' }} · {{ asset.fb_hash || asset.fb_video_id || '待同步' }}</small>
              </el-option>
            </el-select>
            <div v-if="selectedAsset(creative.asset_id)" class="asset-selected">已选择：{{ selectedAsset(creative.asset_id)?.name }}</div>
            <div v-else class="tip">请先在“内容管理 → 素材库”上传并完成 Meta 同步。</div>
          </el-form-item>
          <el-form-item label="主文案" required><el-input v-model="creative.primary_text" type="textarea" :rows="3" maxlength="500" show-word-limit /></el-form-item>
          <el-form-item label="标题"><el-input v-model="creative.headline" maxlength="100" show-word-limit /></el-form-item>
          <el-form-item label="描述"><el-input v-model="creative.description" maxlength="200" show-word-limit /></el-form-item>
          <el-form-item label="行动按钮"><el-select v-model="creative.cta" style="width:100%"><el-option label="了解更多" value="LEARN_MORE" /><el-option label="立即购买" value="SHOP_NOW" /><el-option label="注册" value="SIGN_UP" /><el-option label="下载" value="DOWNLOAD" /><el-option label="联系我们" value="CONTACT_US" /></el-select></el-form-item>
          <el-form-item label="落地页" required><el-input v-model="creative.landing_url" placeholder="https://example.com/landing" /></el-form-item>
        </div>
        <el-button class="add-creative" plain type="primary" @click="addCreative">+ 添加创意</el-button>
        </section>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button v-if="templateStep > 0" @click="templateStep--">上一步</el-button>
        <el-button v-if="templateStep < 3" type="primary" @click="templateStep++">下一步</el-button>
        <el-button v-else type="primary" :loading="saving" @click="submit">保存模板</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { templatesApi, type CampaignTemplate } from '@/api/templates'
import { mediaApi, type MediaItem } from '@/api/media'
import { metaPagesApi, type MetaPage } from '@/api/metaPages'

const templates = ref<CampaignTemplate[]>([])
const mediaAssets = ref<MediaItem[]>([])
const metaPages = ref<MetaPage[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const editingId = ref('')
const templateStep = ref(0)

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
  special_ad_categories: [] as string[],
  is_adset_budget_sharing_enabled: false,
  status: 'ACTIVE',
  budget_type: 'DAILY',
  daily_budget: 50,
  lifetime_budget: 0,
  schedule_start: '',
  schedule_end: '',
  optimization_goal: 'LINK_CLICKS',
  pixel_id: '',
  custom_event_type: 'PURCHASE',
  billing_event: 'IMPRESSIONS',
  bid_strategy: '',
  targeting_json: DEFAULT_TARGETING,
  creative_config_json: DEFAULT_CREATIVE,
})
const targetingForm = reactive({
  countries: 'US',
  age_min: 18,
  age_max: 65,
  genders: [1, 2] as number[],
  interests: '',
  placements: [] as string[],
})
type CreativeForm = { asset_type: 'image' | 'video'; image_hash: string; video_id: string; headline: string; primary_text: string; description: string; cta: string; landing_url: string; asset_id: string }
const newCreative = (): CreativeForm => ({ asset_type: 'image', image_hash: '', video_id: '', headline: '', primary_text: '', description: '', cta: 'LEARN_MORE', landing_url: '', asset_id: '' })
const creativeForm = reactive<{ page_id: string; creatives: CreativeForm[] }>({ page_id: '', creatives: [newCreative()] })
// 异步素材流程使用大写 READY；兼容历史数据中的小写 ready。
const availableAssets = (type: string) => mediaAssets.value.filter(
  asset => asset.asset_type === type && String(asset.status).toUpperCase() === 'READY',
)
const selectedAsset = (id: string) => mediaAssets.value.find(asset => asset.id === id)
const addCreative = () => creativeForm.creatives.push(newCreative())
const removeCreative = (index: number) => creativeForm.creatives.splice(index, 1)
const buildCreativeJson = () => {
  const config: Record<string, any> = {
    page_id: creativeForm.page_id,
    creatives: creativeForm.creatives.map(item => {
      const asset = selectedAsset(item.asset_id)
      return { ...item, image_hash: asset?.fb_hash || item.image_hash, video_id: asset?.fb_video_id || item.video_id }
    }),
  }
  if (form.budget_type === 'LIFETIME') {
    config.schedule = { start_time: form.schedule_start || undefined, end_time: form.schedule_end }
  }
  if (['OFFSITE_CONVERSIONS', 'VALUE'].includes(form.optimization_goal)) {
    config.promoted_object = {
      pixel_id: form.pixel_id,
      custom_event_type: form.custom_event_type,
    }
  }
  form.creative_config_json = JSON.stringify(config, null, 2)
}
const loadCreativeForm = (value: Record<string, any> | null | undefined) => {
  const cfg = value || {}
  creativeForm.page_id = cfg.page_id || ''
  form.schedule_start = cfg.schedule?.start_time || ''
  form.schedule_end = cfg.schedule?.end_time || ''
  form.pixel_id = cfg.promoted_object?.pixel_id || ''
  form.custom_event_type = cfg.promoted_object?.custom_event_type || 'PURCHASE'
  creativeForm.creatives.splice(0, creativeForm.creatives.length, ...(Array.isArray(cfg.creatives) && cfg.creatives.length ? cfg.creatives.map((item: any) => ({ ...newCreative(), ...item })) : [newCreative()]))
}
const buildTargetingJson = () => {
  const targeting: Record<string, any> = {
    geo_locations: { countries: targetingForm.countries.split(',').map(v => v.trim()).filter(Boolean) },
    age_min: targetingForm.age_min,
    age_max: targetingForm.age_max,
    genders: targetingForm.genders,
  }
  if (targetingForm.interests.trim()) targeting.flexible_spec = [{ interests: targetingForm.interests.split(',').map(v => ({ name: v.trim() })).filter(v => v.name) }]
  if (targetingForm.placements.length) {
    const facebook = targetingForm.placements.filter(v => v.startsWith('facebook_')).map(v => v.replace('facebook_', ''))
    const instagram = targetingForm.placements.filter(v => v.startsWith('instagram_')).map(v => v.replace('instagram_', ''))
    targeting.publisher_platforms = [facebook.length ? 'facebook' : '', instagram.length ? 'instagram' : ''].filter(Boolean)
    if (facebook.length) targeting.facebook_positions = facebook
    if (instagram.length) targeting.instagram_positions = instagram
  }
  form.targeting_json = JSON.stringify(targeting, null, 2)
}
const loadTargetingForm = (value: Record<string, any> | null | undefined) => {
  const targeting = value || {}
  targetingForm.countries = targeting.geo_locations?.countries?.join(',') || 'US'
  targetingForm.age_min = targeting.age_min || 18
  targetingForm.age_max = targeting.age_max || 65
  targetingForm.genders = targeting.genders?.length ? targeting.genders : [1, 2]
  targetingForm.interests = (targeting.flexible_spec?.[0]?.interests || []).map((v: any) => v.name || '').filter(Boolean).join(',')
  targetingForm.placements = [
    ...(targeting.facebook_positions || []).map((v: string) => `facebook_${v}`),
    ...(targeting.instagram_positions || []).map((v: string) => `instagram_${v}`),
  ]
}

const loadTemplates = async () => {
  loading.value = true
  try {
    const { data } = await templatesApi.list()
    templates.value = data
  } finally {
    loading.value = false
  }
}
const loadMediaAssets = async () => {
  try {
    const { data } = await mediaApi.list()
    // 素材主表的 status 可能仍是 PENDING；模板投放实际使用账户级 binding。
    // 用 READY binding 回填 Meta ID，避免素材库已映射但模板仍显示“待同步”。
    mediaAssets.value = await Promise.all(data.map(async asset => {
      try {
        const bindingRes = await mediaApi.bindings(asset.id)
        const ready = bindingRes.data.find(binding => String(binding.status).toUpperCase() === 'READY' && binding.meta_asset_id)
        if (!ready) return asset
        return {
          ...asset,
          status: 'READY',
          fb_hash: asset.asset_type === 'image' ? (asset.fb_hash || ready.meta_asset_id) : asset.fb_hash,
          fb_video_id: asset.asset_type === 'video' ? (asset.fb_video_id || ready.meta_asset_id) : asset.fb_video_id,
        }
      } catch {
        return asset
      }
    }))
  } catch { mediaAssets.value = [] }
}
const loadMetaPages = async () => {
  try { const { data } = await metaPagesApi.list(); metaPages.value = data } catch { metaPages.value = [] }
}

const resetForm = () => {
  templateStep.value = 0
  isEdit.value = false
  editingId.value = ''
  form.name = ''
  form.objective = 'OUTCOME_SALES'
  form.buying_type = 'AUCTION'
  form.special_ad_categories = []
  form.status = 'ACTIVE'
  form.budget_type = 'DAILY'
  form.daily_budget = 50
  form.lifetime_budget = 0
  form.schedule_start = ''
  form.schedule_end = ''
  form.optimization_goal = 'LINK_CLICKS'
  form.pixel_id = ''
  form.custom_event_type = 'PURCHASE'
  form.billing_event = 'IMPRESSIONS'
  form.bid_strategy = ''
  form.targeting_json = DEFAULT_TARGETING
  form.creative_config_json = DEFAULT_CREATIVE
  loadCreativeForm(JSON.parse(DEFAULT_CREATIVE))
  loadTargetingForm(JSON.parse(DEFAULT_TARGETING))
}

const openCreate = () => {
  resetForm()
  loadMediaAssets()
  loadMetaPages()
  dialogVisible.value = true
}

const openEdit = (row: CampaignTemplate) => {
  templateStep.value = 0
  isEdit.value = true
  editingId.value = row.id
  form.name = row.name
  form.objective = row.objective || 'OUTCOME_SALES'
  form.buying_type = row.buying_type || 'AUCTION'
  form.special_ad_categories = [...(row.special_ad_categories || [])]
  form.is_adset_budget_sharing_enabled = row.is_adset_budget_sharing_enabled ?? false
  form.status = row.status || 'ACTIVE'
  form.budget_type = row.budget_type || 'DAILY'
  form.daily_budget = row.daily_budget ?? 50
  form.lifetime_budget = row.lifetime_budget ?? 0
  form.optimization_goal = row.optimization_goal || 'LINK_CLICKS'
  form.billing_event = row.billing_event || 'IMPRESSIONS'
  form.bid_strategy = row.bid_strategy || ''
  form.targeting_json = JSON.stringify(row.targeting_json ?? {}, null, 2)
  loadTargetingForm(row.targeting_json)
  form.creative_config_json = JSON.stringify(row.creative_config_json ?? {}, null, 2)
  loadCreativeForm(row.creative_config_json)
  loadMediaAssets()
  loadMetaPages()
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
  if (form.budget_type === 'LIFETIME' && !form.schedule_end) {
    ElMessage.warning('总预算模板必须设置结束时间')
    templateStep.value = 1
    return
  }
  if (!creativeForm.page_id) {
    ElMessage.warning('请选择已授权的 Facebook 页面')
    templateStep.value = 3
    return
  }
  for (let i = 0; i < creativeForm.creatives.length; i++) {
    const creative = creativeForm.creatives[i]
    const asset = selectedAsset(creative.asset_id)
    if (!asset || String(asset.status).toUpperCase() !== 'READY') {
      ElMessage.warning(`创意 ${i + 1} 必须选择已同步完成的素材`)
      templateStep.value = 3
      return
    }
    if (!creative.primary_text.trim()) {
      ElMessage.warning(`请填写创意 ${i + 1} 的主文案`)
      templateStep.value = 3
      return
    }
    try {
      const url = new URL(creative.landing_url)
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error('invalid')
    } catch {
      ElMessage.warning(`创意 ${i + 1} 的落地页必须是有效的 http/https URL`)
      templateStep.value = 3
      return
    }
  }
  if (['OFFSITE_CONVERSIONS', 'VALUE'].includes(form.optimization_goal) && (!form.pixel_id.trim() || !form.custom_event_type.trim())) {
    ElMessage.warning('转化优化必须填写 Pixel ID 和转化事件')
    templateStep.value = 2
    return
  }

  buildTargetingJson()
  buildCreativeJson()
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
      special_ad_categories: form.special_ad_categories,
      is_adset_budget_sharing_enabled: form.is_adset_budget_sharing_enabled,
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
.inline-fields { display: flex; align-items: center; gap: 10px; }
.template-steps { margin-bottom: 20px; }
.creative-block { margin: 14px 0 20px; padding: 16px 18px 6px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafcff; }
.creative-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; color: #243b53; }
.add-creative { margin-left: 120px; margin-bottom: 8px; }
.asset-option-meta { float: right; margin-left: 18px; color: #909399; }
.asset-selected { margin-top: 6px; color: #67c23a; font-size: 12px; }
</style>

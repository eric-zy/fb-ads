<template>
  <div class="targeting-page">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">定向资产</h2>
            <p class="page-desc">集中管理地区组与定向包，保存后可在批量投放的广告组中直接复用。</p>
          </div>
          <div class="header-actions">
            <el-button :loading="loading" @click="loadAll">刷新</el-button>
            <el-button type="primary" @click="openCreatePackage">新建定向包</el-button>
            <el-button type="primary" plain @click="openCreateRegion">新建地区组</el-button>
          </div>
        </div>
      </template>

      <el-alert type="info" :closable="false" show-icon>
        定向包保存的是投放时使用的 Meta targeting 配置；地区组只负责复用包含/排除地区。保存后仍会在投放预检阶段校验账户权限与 Meta 参数。
      </el-alert>

      <el-tabs v-model="activeTab" class="targeting-tabs">
        <el-tab-pane label="地区组" name="regions">
          <div class="table-toolbar">
            <span class="toolbar-hint">共 {{ regionGroups.length }} 个地区组</span>
            <el-button type="primary" plain @click="openCreateRegion">新建地区组</el-button>
          </div>
          <el-table :data="regionGroups" v-loading="loading" size="small" row-key="id">
            <el-table-column prop="name" label="名称" min-width="170" show-overflow-tooltip />
            <el-table-column label="包含地区" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">{{ geoSummary(row.geo_locations) }}</template>
            </el-table-column>
            <el-table-column label="排除地区" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">{{ geoSummary(row.excluded_geo_locations) || '—' }}</template>
            </el-table-column>
            <el-table-column label="适用账户" width="110">
              <template #default="{ row }">{{ row.account_ids?.length || '全部可见' }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="最近更新" width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openEditRegion(row)">编辑</el-button>
                <el-button link type="danger" @click="archiveRegion(row)">归档</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !regionGroups.length" description="暂无地区组" />
        </el-tab-pane>

        <el-tab-pane label="定向包" name="packages">
          <div class="table-toolbar">
            <span class="toolbar-hint">共 {{ targetingPackages.length }} 个定向包</span>
            <el-button type="primary" @click="openCreatePackage">新建定向包</el-button>
          </div>
          <el-table :data="targetingPackages" v-loading="loading" size="small" row-key="id">
            <el-table-column prop="name" label="名称" min-width="170" show-overflow-tooltip />
            <el-table-column label="地区" min-width="210" show-overflow-tooltip>
              <template #default="{ row }">{{ geoSummary(row.targeting_json?.geo_locations) || '未设置' }}</template>
            </el-table-column>
            <el-table-column label="受众" width="100">
              <template #default="{ row }">{{ audienceCount(row.targeting_json) }}</template>
            </el-table-column>
            <el-table-column label="年龄/性别" width="150">
              <template #default="{ row }">{{ targetingSummary(row.targeting_json) }}</template>
            </el-table-column>
            <el-table-column label="版位" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ (row.placement_json?.publisher_platforms || []).join(', ') || '未设置' }}</template>
            </el-table-column>
            <el-table-column label="适用账户" width="110">
              <template #default="{ row }">{{ row.account_ids?.length || '全部可见' }}</template>
            </el-table-column>
            <el-table-column prop="updated_at" label="最近更新" width="180" show-overflow-tooltip />
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openEditPackage(row)">编辑</el-button>
                <el-button link type="danger" @click="archivePackage(row)">归档</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !targetingPackages.length" description="暂无定向包" />
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="regionDialogVisible" :title="editingRegion ? '编辑地区组' : '新建地区组'" width="680px" :close-on-click-modal="false">
      <el-form label-width="110px">
        <el-form-item label="名称" required>
          <el-input v-model="regionForm.name" maxlength="255" show-word-limit placeholder="例如美国排除加拿大" />
        </el-form-item>
        <el-form-item label="适用账户">
          <el-select v-model="regionForm.account_ids" multiple filterable collapse-tags style="width:100%" placeholder="不选择表示全部可见账户">
            <el-option v-for="account in accounts" :key="account.id" :label="accountLabel(account)" :value="account.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="包含国家/地区" required>
          <el-input v-model="regionForm.countries" placeholder="例如 US,CA；多个值用逗号分隔" />
        </el-form-item>
        <el-form-item label="包含地区 ID">
          <el-input v-model="regionForm.regions" placeholder="可选，例如 Meta region key" />
        </el-form-item>
        <el-form-item label="包含城市 ID">
          <el-input v-model="regionForm.cities" placeholder="可选，多个值用逗号分隔" />
        </el-form-item>
        <el-form-item label="包含邮编">
          <el-input v-model="regionForm.zips" placeholder="可选，多个值用逗号分隔" />
        </el-form-item>
        <el-form-item label="排除国家/地区">
          <el-input v-model="regionForm.excluded_countries" placeholder="例如 CA；多个值用逗号分隔" />
        </el-form-item>
        <div class="inline-fields"><el-form-item label="排除地区 ID"><el-input v-model="regionForm.excluded_regions" placeholder="Meta region key" /></el-form-item><el-form-item label="排除城市 ID"><el-input v-model="regionForm.excluded_cities" placeholder="Meta city key" /></el-form-item></div>
        <el-form-item label="排除邮编"><el-input v-model="regionForm.excluded_zips" placeholder="多个值用逗号分隔" /></el-form-item>
        <el-form-item label="自定义位置 JSON"><el-input v-model="regionForm.custom_locations_json" type="textarea" :rows="2" placeholder='可选，Meta custom_locations 数组 JSON' /></el-form-item>
        <el-form-item label="排除自定义位置 JSON"><el-input v-model="regionForm.excluded_custom_locations_json" type="textarea" :rows="2" placeholder='可选，Meta custom_locations 数组 JSON' /></el-form-item>
        <el-form-item label="位置类型">
          <el-checkbox-group v-model="regionForm.location_types">
            <el-checkbox label="home">居住地</el-checkbox>
            <el-checkbox label="recent">最近位置</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="regionForm.description" type="textarea" :rows="3" maxlength="2000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="regionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRegion">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="packageDialogVisible" :title="editingPackage ? '编辑定向包' : '新建定向包'" width="760px" :close-on-click-modal="false">
      <el-form label-width="118px">
        <el-form-item label="名称" required>
          <el-input v-model="packageForm.name" maxlength="255" show-word-limit placeholder="例如 US 流量定向" />
        </el-form-item>
        <el-form-item label="适用账户">
          <el-select v-model="packageForm.account_ids" multiple filterable collapse-tags style="width:100%" placeholder="不选择表示全部可见账户">
            <el-option v-for="account in accounts" :key="account.id" :label="accountLabel(account)" :value="account.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="地区组">
          <el-select v-model="packageForm.region_group_ids" multiple filterable collapse-tags style="width:100%" placeholder="选择地区组后自动合并地区配置">
            <el-option v-for="group in regionGroups" :key="group.id" :label="group.name" :value="group.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="包含国家/地区">
          <el-input v-model="packageForm.countries" placeholder="不使用地区组时填写，例如 US,GB" />
        </el-form-item>
        <el-form-item label="排除国家/地区">
          <el-input v-model="packageForm.excluded_countries" placeholder="例如 CA；多个值用逗号分隔" />
        </el-form-item>
        <div class="inline-fields"><el-form-item label="包含地区 ID"><el-input v-model="packageForm.regions" placeholder="Meta region key" /></el-form-item><el-form-item label="包含城市 ID"><el-input v-model="packageForm.cities" placeholder="Meta city key" /></el-form-item></div>
        <div class="inline-fields"><el-form-item label="包含邮编"><el-input v-model="packageForm.zips" placeholder="多个值用逗号分隔" /></el-form-item><el-form-item label="排除地区 ID"><el-input v-model="packageForm.excluded_regions" placeholder="Meta region key" /></el-form-item></div>
        <div class="inline-fields"><el-form-item label="排除城市 ID"><el-input v-model="packageForm.excluded_cities" placeholder="Meta city key" /></el-form-item><el-form-item label="排除邮编"><el-input v-model="packageForm.excluded_zips" placeholder="多个值用逗号分隔" /></el-form-item></div>
        <el-form-item label="自定义位置 JSON"><el-input v-model="packageForm.custom_locations_json" type="textarea" :rows="2" placeholder='可选，Meta custom_locations 数组 JSON' /></el-form-item>
        <el-form-item label="排除自定义位置 JSON"><el-input v-model="packageForm.excluded_custom_locations_json" type="textarea" :rows="2" placeholder='可选，Meta custom_locations 数组 JSON' /></el-form-item>
        <el-form-item label="位置类型">
          <el-checkbox-group v-model="packageForm.location_types">
            <el-checkbox label="home">居住地</el-checkbox>
            <el-checkbox label="recent">最近位置</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="年龄范围">
          <el-input-number v-model="packageForm.age_min" :min="13" :max="65" />
          <span class="range-separator">至</span>
          <el-input-number v-model="packageForm.age_max" :min="13" :max="65" />
        </el-form-item>
        <el-form-item label="性别">
          <el-checkbox-group v-model="packageForm.genders">
            <el-checkbox :label="1">男性</el-checkbox>
            <el-checkbox :label="2">女性</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="包含自定义受众">
          <el-input v-model="packageForm.custom_audiences" placeholder="Meta Audience ID；跨账户用 account_id::audience_id" />
        </el-form-item>
        <el-form-item label="排除自定义受众">
          <el-input v-model="packageForm.excluded_custom_audiences" placeholder="Meta Audience ID；跨账户用 account_id::audience_id" />
        </el-form-item>
        <el-form-item label="兴趣">
          <el-input v-model="packageForm.interests" placeholder="兴趣名称，多个值用逗号分隔" />
        </el-form-item>
        <el-form-item label="语言">
          <el-input v-model="packageForm.languages" placeholder="语言 ID，多个值用逗号分隔" />
        </el-form-item>
        <el-form-item label="设备">
          <el-checkbox-group v-model="packageForm.device_platforms">
            <el-checkbox label="mobile">移动端</el-checkbox>
            <el-checkbox label="desktop">桌面端</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="系统">
          <el-input v-model="packageForm.user_os" placeholder="例如 iOS,Android" />
        </el-form-item>
        <el-form-item label="设备型号">
          <el-input v-model="packageForm.user_device" placeholder="例如 iPhone" />
        </el-form-item>
        <el-form-item label="网络">
          <el-input v-model="packageForm.wireless_carrier" placeholder="例如 WIFI" />
        </el-form-item>
        <el-form-item label="版位">
          <el-checkbox-group v-model="packageForm.publisher_platforms">
            <el-checkbox label="facebook">Facebook</el-checkbox>
            <el-checkbox label="instagram">Instagram</el-checkbox>
            <el-checkbox label="audience_network">Audience Network</el-checkbox>
            <el-checkbox label="messenger">Messenger</el-checkbox>
          </el-checkbox-group>
          <div class="tip">不选择平台表示使用自动版位；选择具体位置时会自动包含对应平台。</div>
        </el-form-item>
        <div class="inline-fields"><el-form-item label="Facebook 位置"><el-select v-model="packageForm.facebook_positions" multiple collapse-tags style="width:100%"><el-option label="信息流" value="feed" /><el-option label="快拍" value="story" /><el-option label="Marketplace" value="marketplace" /><el-option label="视频流" value="video_feeds" /><el-option label="右边栏" value="right_hand_column" /><el-option label="搜索结果" value="search" /><el-option label="Reels" value="reels" /><el-option label="插播视频" value="instream_video" /><el-option label="主页动态" value="profile_feed" /></el-select></el-form-item><el-form-item label="Instagram 位置"><el-select v-model="packageForm.instagram_positions" multiple collapse-tags style="width:100%"><el-option label="信息流" value="stream" /><el-option label="快拍" value="story" /><el-option label="Reels" value="reels" /><el-option label="探索" value="explore" /><el-option label="探索首页" value="explore_home" /><el-option label="主页动态" value="profile_feed" /></el-select></el-form-item></div>
        <div class="inline-fields"><el-form-item label="Audience Network"><el-select v-model="packageForm.audience_network_positions" multiple collapse-tags style="width:100%"><el-option label="标准版位" value="classic" /><el-option label="激励视频" value="rewarded_video" /><el-option label="插播视频" value="instream_video" /></el-select></el-form-item><el-form-item label="Messenger 位置"><el-select v-model="packageForm.messenger_positions" multiple collapse-tags style="width:100%"><el-option label="主页" value="messenger_home" /><el-option label="快拍" value="story" /></el-select></el-form-item></div>
        <el-form-item label="说明">
          <el-input v-model="packageForm.description" type="textarea" :rows="3" maxlength="2000" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="packageDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePackage">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi, type DeployableAccount } from '@/api/admin'
import {
  regionGroupsApi,
  targetingPackagesApi,
  type RegionGroup,
  type TargetingPackage,
} from '@/api/targetingPackages'

const activeTab = ref<'regions' | 'packages'>('regions')
const loading = ref(false)
const saving = ref(false)
const accounts = ref<DeployableAccount[]>([])
const regionGroups = ref<RegionGroup[]>([])
const targetingPackages = ref<TargetingPackage[]>([])
const regionDialogVisible = ref(false)
const packageDialogVisible = ref(false)
const editingRegion = ref<RegionGroup | null>(null)
const editingPackage = ref<TargetingPackage | null>(null)

const newRegionForm = () => ({
  name: '', description: '', account_ids: [] as string[], countries: '', regions: '', cities: '', zips: '',
  excluded_countries: '', excluded_regions: '', excluded_cities: '', excluded_zips: '', custom_locations_json: '', excluded_custom_locations_json: '', location_types: ['home', 'recent'] as string[],
})
const newPackageForm = () => ({
  name: '', description: '', account_ids: [] as string[], region_group_ids: [] as string[],
  countries: '', regions: '', cities: '', zips: '', excluded_countries: '', excluded_regions: '', excluded_cities: '', excluded_zips: '', custom_locations_json: '', excluded_custom_locations_json: '', location_types: ['home', 'recent'] as string[],
  age_min: 18, age_max: 65, genders: [1, 2] as number[], custom_audiences: '', excluded_custom_audiences: '',
  interests: '', languages: '', device_platforms: [] as string[], user_os: '', user_device: '', wireless_carrier: '',
  publisher_platforms: [] as string[], facebook_positions: [] as string[], instagram_positions: [] as string[], audience_network_positions: [] as string[], messenger_positions: [] as string[],
})
const regionForm = reactive(newRegionForm())
const packageForm = reactive(newPackageForm())

const splitValues = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean)
const parseJsonArray = (value: string, label: string) => {
  const text = String(value || '').trim()
  if (!text) return []
  try {
    const parsed = JSON.parse(text)
    if (!Array.isArray(parsed)) throw new Error('invalid')
    return parsed
  } catch {
    throw new Error(`${label}必须是数组 JSON`)
  }
}
const joinValues = (value: unknown) => Array.isArray(value)
  ? value.map(item => typeof item === 'object' && item ? ((item as any).key || (item as any).id || (item as any).name || '') : String(item)).filter(Boolean).join(', ')
  : ''
const accountLabel = (account: DeployableAccount) => `${account.account_name || account.account_id} (${account.account_id})`
const errorMessage = (error: any, fallback: string) => error?.response?.data?.detail || fallback
const geoSummary = (geo: Record<string, any> | null | undefined) => {
  if (!geo) return ''
  const parts = [
    geo.countries?.length ? `国家 ${joinValues(geo.countries)}` : '',
    geo.regions?.length ? `地区 ${joinValues(geo.regions)}` : '',
    geo.cities?.length ? `城市 ${joinValues(geo.cities)}` : '',
    geo.zips?.length ? `邮编 ${joinValues(geo.zips)}` : '',
  ].filter(Boolean)
  return parts.join('；')
}
const audienceCount = (targeting: Record<string, any> | undefined) => {
  const included = targeting?.custom_audiences?.length || 0
  const excluded = targeting?.excluded_custom_audiences?.length || targeting?.excluded_audiences?.length || 0
  return `含 ${included} / 排 ${excluded}`
}
const targetingSummary = (targeting: Record<string, any> | undefined) => {
  if (!targeting) return '—'
  const genders = targeting.genders?.length === 2 ? '男女' : targeting.genders?.includes(1) ? '男' : targeting.genders?.includes(2) ? '女' : '—'
  return `${targeting.age_min || 18}-${targeting.age_max || 65} · ${genders}`
}
const loadAccounts = async () => {
  try {
    const { data } = await accountApi.availableForDeployment({ allow_paused_debug: true })
    accounts.value = data.accounts || []
  } catch {
    accounts.value = []
  }
}
const loadAll = async () => {
  loading.value = true
  try {
    const [regions, packages] = await Promise.all([regionGroupsApi.list(), targetingPackagesApi.list()])
    regionGroups.value = regions.data || []
    targetingPackages.value = packages.data || []
  } catch (error: any) {
    ElMessage.error(errorMessage(error, '定向资产加载失败，请确认数据库迁移已执行'))
  } finally {
    loading.value = false
  }
}

const openCreateRegion = () => {
  editingRegion.value = null
  Object.assign(regionForm, newRegionForm())
  regionDialogVisible.value = true
}
const openEditRegion = (row: RegionGroup) => {
  editingRegion.value = row
  const geo = row.geo_locations || {}
  const excluded = row.excluded_geo_locations || {}
  Object.assign(regionForm, {
    name: row.name,
    description: row.description || '',
    account_ids: [...(row.account_ids || [])],
    countries: joinValues(geo.countries), regions: joinValues(geo.regions), cities: joinValues(geo.cities), zips: joinValues(geo.zips),
    excluded_countries: joinValues(excluded.countries), excluded_regions: joinValues(excluded.regions), excluded_cities: joinValues(excluded.cities), excluded_zips: joinValues(excluded.zips),
    custom_locations_json: Array.isArray(geo.custom_locations) ? JSON.stringify(geo.custom_locations) : '',
    excluded_custom_locations_json: Array.isArray(excluded.custom_locations) ? JSON.stringify(excluded.custom_locations) : '',
    location_types: Array.isArray(geo.location_types) && geo.location_types.length ? [...geo.location_types] : ['home', 'recent'],
  })
  regionDialogVisible.value = true
}
const buildRegionPayload = () => {
  const geo: Record<string, any> = {}
  for (const [field, value] of [['countries', regionForm.countries], ['regions', regionForm.regions], ['cities', regionForm.cities], ['zips', regionForm.zips]] as const) {
    const values = splitValues(value)
    if (values.length) geo[field] = values
  }
  if (regionForm.location_types.length) geo.location_types = [...regionForm.location_types]
  if (regionForm.custom_locations_json.trim()) geo.custom_locations = parseJsonArray(regionForm.custom_locations_json, '自定义位置')
  const excluded: Record<string, any> = {}
  for (const [field, value] of [['countries', regionForm.excluded_countries], ['regions', regionForm.excluded_regions], ['cities', regionForm.excluded_cities], ['zips', regionForm.excluded_zips]] as const) {
    const values = splitValues(value)
    if (values.length) excluded[field] = values
  }
  if (regionForm.excluded_custom_locations_json.trim()) excluded.custom_locations = parseJsonArray(regionForm.excluded_custom_locations_json, '排除自定义位置')
  return {
    name: regionForm.name.trim(), description: regionForm.description.trim() || null, account_ids: [...regionForm.account_ids],
    geo_locations: geo, excluded_geo_locations: excluded,
  }
}
const saveRegion = async () => {
  if (!regionForm.name.trim()) { ElMessage.warning('请输入地区组名称'); return }
  let payload
  try { payload = buildRegionPayload() } catch (error: any) {
    ElMessage.warning(error?.message || '地区 JSON 配置无效')
    return
  }
  if (!Object.keys(payload.geo_locations).some(key => ['countries', 'regions', 'cities', 'zips', 'custom_locations'].includes(key))) {
    ElMessage.warning('至少填写一个国家、地区、城市、邮编或自定义位置')
    return
  }
  saving.value = true
  try {
    if (editingRegion.value) await regionGroupsApi.update(editingRegion.value.id, payload)
    else await regionGroupsApi.create(payload)
    regionDialogVisible.value = false
    await loadAll()
    ElMessage.success('地区组已保存')
  } catch (error: any) {
    ElMessage.error(errorMessage(error, '地区组保存失败'))
  } finally { saving.value = false }
}
const archiveRegion = async (row: RegionGroup) => {
  try {
    await ElMessageBox.confirm(`确认归档地区组“${row.name}”吗？归档后不会从历史投放配置中删除。`, '归档确认', { type: 'warning' })
    await regionGroupsApi.remove(row.id)
    await loadAll()
    ElMessage.success('地区组已归档')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error, '地区组归档失败'))
  }
}

const openCreatePackage = () => {
  editingPackage.value = null
  Object.assign(packageForm, newPackageForm())
  packageDialogVisible.value = true
}
const audienceTokens = (values: any[]) => (values || []).map(value => {
  const id = typeof value === 'object' && value ? (value.id || value.meta_audience_id || '') : String(value)
  const account = typeof value === 'object' && value ? (value.ad_account_id || value.account_id || '') : ''
  return account && id ? `${account}::${id}` : id
}).filter(Boolean)
const openEditPackage = (row: TargetingPackage) => {
  editingPackage.value = row
  const targeting = row.targeting_json || {}
  const geo = targeting.geo_locations || {}
  const excluded = targeting.excluded_geo_locations || {}
  const interests = targeting.flexible_spec?.[0]?.interests || []
  Object.assign(packageForm, {
    name: row.name, description: row.description || '', account_ids: [...(row.account_ids || [])], region_group_ids: [...(row.region_group_ids || [])],
    countries: joinValues(geo.countries), regions: joinValues(geo.regions), cities: joinValues(geo.cities), zips: joinValues(geo.zips),
    excluded_countries: joinValues(excluded.countries), excluded_regions: joinValues(excluded.regions), excluded_cities: joinValues(excluded.cities), excluded_zips: joinValues(excluded.zips),
    custom_locations_json: Array.isArray(geo.custom_locations) ? JSON.stringify(geo.custom_locations) : '',
    excluded_custom_locations_json: Array.isArray(excluded.custom_locations) ? JSON.stringify(excluded.custom_locations) : '',
    location_types: Array.isArray(geo.location_types) && geo.location_types.length ? [...geo.location_types] : ['home', 'recent'],
    age_min: Number(targeting.age_min || 18), age_max: Number(targeting.age_max || 65), genders: Array.isArray(targeting.genders) ? [...targeting.genders] : [1, 2],
    custom_audiences: audienceTokens(targeting.custom_audiences).join(','), excluded_custom_audiences: audienceTokens(targeting.excluded_custom_audiences || targeting.excluded_audiences).join(','),
    interests: interests.map((item: any) => item.name || '').filter(Boolean).join(','), languages: joinValues(targeting.languages),
    device_platforms: Array.isArray(targeting.device_platforms) ? [...targeting.device_platforms] : [],
    user_os: joinValues(targeting.user_os), user_device: joinValues(targeting.user_device), wireless_carrier: joinValues(targeting.wireless_carrier),
    publisher_platforms: Array.isArray(row.placement_json?.publisher_platforms) ? [...row.placement_json.publisher_platforms] : [],
    facebook_positions: Array.isArray(row.placement_json?.facebook_positions) ? [...row.placement_json.facebook_positions] : [],
    instagram_positions: Array.isArray(row.placement_json?.instagram_positions) ? [...row.placement_json.instagram_positions] : [],
    audience_network_positions: Array.isArray(row.placement_json?.audience_network_positions) ? [...row.placement_json.audience_network_positions] : [],
    messenger_positions: Array.isArray(row.placement_json?.messenger_positions) ? [...row.placement_json.messenger_positions] : [],
  })
  packageDialogVisible.value = true
}
const mergeGeo = () => {
  const groups = regionGroups.value.filter(group => packageForm.region_group_ids.includes(group.id))
  const geo: Record<string, any> = {}
  const excluded: Record<string, any> = {}
  const append = (target: Record<string, any>, key: string, values: any) => {
    if (!Array.isArray(values) || !values.length) return
    const normalized = values.map((item: any) => typeof item === 'object' && item ? item : String(item).trim()).filter(Boolean)
    const seen = new Set((target[key] || []).map((item: any) => typeof item === 'object' ? JSON.stringify(item) : String(item)))
    target[key] = [...(target[key] || [])]
    for (const item of normalized) {
      const marker = typeof item === 'object' ? JSON.stringify(item) : String(item)
      if (!seen.has(marker)) { target[key].push(item); seen.add(marker) }
    }
  }
  for (const group of groups) {
    for (const key of ['countries', 'regions', 'cities', 'zips', 'custom_locations']) append(geo, key, group.geo_locations?.[key])
    for (const key of ['countries', 'regions', 'cities', 'zips', 'custom_locations']) append(excluded, key, group.excluded_geo_locations?.[key])
  }
  append(geo, 'countries', splitValues(packageForm.countries))
  append(geo, 'regions', splitValues(packageForm.regions))
  append(geo, 'cities', splitValues(packageForm.cities))
  append(geo, 'zips', splitValues(packageForm.zips))
  if (packageForm.custom_locations_json.trim()) append(geo, 'custom_locations', parseJsonArray(packageForm.custom_locations_json, '自定义位置'))
  for (const [field, value] of [['countries', packageForm.excluded_countries], ['regions', packageForm.excluded_regions], ['cities', packageForm.excluded_cities], ['zips', packageForm.excluded_zips]] as const) append(excluded, field, splitValues(value))
  if (packageForm.excluded_custom_locations_json.trim()) append(excluded, 'custom_locations', parseJsonArray(packageForm.excluded_custom_locations_json, '排除自定义位置'))
  if (packageForm.location_types.length) geo.location_types = [...packageForm.location_types]
  return { geo, excluded }
}
const toAudienceRefs = (value: string) => {
  const ids = splitValues(value)
  const account = packageForm.account_ids.length === 1 ? accounts.value.find(item => item.id === packageForm.account_ids[0]) : null
  return ids.map(id => {
    const separator = id.indexOf('::')
    if (separator > 0) return { id: id.slice(separator + 2), ad_account_id: id.slice(0, separator) }
    return account ? { id, ad_account_id: account.account_id } : id
  })
}
const buildPackagePayload = () => {
  const { geo, excluded } = mergeGeo()
  const targeting: Record<string, any> = {
    geo_locations: geo,
    age_min: packageForm.age_min,
    age_max: packageForm.age_max,
    genders: [...packageForm.genders],
  }
  if (Object.keys(excluded).length) targeting.excluded_geo_locations = excluded
  const interests = splitValues(packageForm.interests)
  if (interests.length) targeting.flexible_spec = [{ interests: interests.map(name => ({ name })) }]
  const languages = splitValues(packageForm.languages)
  if (languages.length) targeting.languages = languages
  const included = toAudienceRefs(packageForm.custom_audiences)
  const excludedAudiences = toAudienceRefs(packageForm.excluded_custom_audiences)
  if (included.length) targeting.custom_audiences = included
  if (excludedAudiences.length) targeting.excluded_custom_audiences = excludedAudiences
  if (packageForm.device_platforms.length) targeting.device_platforms = [...packageForm.device_platforms]
  for (const [field, value] of [['user_os', packageForm.user_os], ['user_device', packageForm.user_device], ['wireless_carrier', packageForm.wireless_carrier]] as const) {
    const values = splitValues(value)
    if (values.length) targeting[field] = values
  }
  const positions = [
    ['facebook', 'facebook_positions'],
    ['instagram', 'instagram_positions'],
    ['audience_network', 'audience_network_positions'],
    ['messenger', 'messenger_positions'],
  ] as const
  const platforms = new Set((packageForm.publisher_platforms || []).filter(Boolean))
  const placement: Record<string, any> = {}
  for (const [platform, field] of positions) {
    const values = Array.isArray(packageForm[field]) ? packageForm[field].filter(Boolean) : []
    if (values.length) {
      platforms.add(platform)
      placement[field] = [...values]
    }
  }
  if (platforms.size) placement.publisher_platforms = [...platforms]
  return {
    name: packageForm.name.trim(), description: packageForm.description.trim() || null, account_ids: [...packageForm.account_ids],
    region_group_ids: [...packageForm.region_group_ids], targeting_json: targeting,
    placement_json: placement,
  }
}
const savePackage = async () => {
  if (!packageForm.name.trim()) { ElMessage.warning('请输入定向包名称'); return }
  let payload
  try { payload = buildPackagePayload() } catch (error: any) {
    ElMessage.warning(error?.message || '定向 JSON 配置无效')
    return
  }
  if (!Object.keys(payload.targeting_json.geo_locations).some(key => ['countries', 'regions', 'cities', 'zips', 'custom_locations'].includes(key))) {
    ElMessage.warning('请填写国家/地区或选择地区组')
    return
  }
  saving.value = true
  try {
    if (editingPackage.value) await targetingPackagesApi.update(editingPackage.value.id, payload)
    else await targetingPackagesApi.create(payload)
    packageDialogVisible.value = false
    await loadAll()
    ElMessage.success('定向包已保存')
  } catch (error: any) {
    ElMessage.error(errorMessage(error, '定向包保存失败'))
  } finally { saving.value = false }
}
const archivePackage = async (row: TargetingPackage) => {
  try {
    await ElMessageBox.confirm(`确认归档定向包“${row.name}”吗？`, '归档确认', { type: 'warning' })
    await targetingPackagesApi.remove(row.id)
    await loadAll()
    ElMessage.success('定向包已归档')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error, '定向包归档失败'))
  }
}

onMounted(async () => {
  await Promise.all([loadAccounts(), loadAll()])
})
</script>

<style scoped lang="scss">
.targeting-page { min-height: 100%; }
.header-bar { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.page-title { margin: 0; font-size: 20px; }
.page-desc { margin: 6px 0 0; color: #909399; font-size: 13px; line-height: 1.6; }
.targeting-tabs { margin-top: 18px; }
.table-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; }
.toolbar-hint { color: #909399; font-size: 13px; }
.range-separator { margin: 0 10px; color: #909399; }
</style>

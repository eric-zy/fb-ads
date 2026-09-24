<template>
  <div class="templates-page">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">{{ t('pages.templates') }}</h2>
            <p class="page-desc">
              投放模板是系统最核心的业务对象：配置一次，即可批量部署到任意数量的广告账户。
              模板保存目标、预算、定向与素材文案，部署时按「模板 → 账户」生成 Campaign / AdSet / Ad。
            </p>
          </div>
          <el-button type="primary" @click="openCreate">{{ t('pages.create') }}</el-button>
        </div>
      </template>

      <el-table :data="templates" v-loading="loading" size="small">
        <el-table-column prop="name" :label="t('pages.name')" min-width="160" show-overflow-tooltip />
        <el-table-column prop="objective" label="目标" width="150" show-overflow-tooltip />
        <el-table-column :label="t('pages.budget')" width="140">
          <template #default="{ row }">
            <span v-if="row.budget_type === 'LIFETIME'">
              ${{ row.lifetime_budget ?? '-' }} 总
            </span>
            <span v-else>${{ row.daily_budget ?? '-' }}/天</span>
          </template>
        </el-table-column>
        <el-table-column label="成效目标" width="160" show-overflow-tooltip><template #default="{ row }">{{ optimizationGoalLabel(row.optimization_goal) }}</template></el-table-column>
        <el-table-column label="投放形式" width="150">
          <template #default="{ row }">
            <el-tag size="small" :type="row.creative_config_json?.creative_format === 'CAROUSEL' ? 'warning' : 'success'">
              {{ row.creative_config_json?.creative_format === 'CAROUSEL' ? '轮播' : '单图片或视频' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('pages.targeting')" width="120">
          <template #default="{ row }">
            <span>{{ geoSummary(row.targeting_json) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('pages.creatives')" width="90">
          <template #default="{ row }">
            {{ creativeCount(row.creative_config_json) }}
          </template>
        </el-table-column>
        <el-table-column :label="t('pages.status')" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="updated_at" :label="t('pages.updated')" width="180" show-overflow-tooltip />
        <el-table-column :label="t('pages.actions')" width="200" fixed="right">
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
            <el-date-picker v-model="form.schedule_start" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="可选，默认立即开始" popper-class="date-time-popper" placement="bottom-start" style="width:100%" />
          </el-form-item>
          <el-form-item label="结束时间" required>
            <el-date-picker v-model="form.schedule_end" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="总预算必须设置结束时间" popper-class="date-time-popper" placement="bottom-start" style="width:100%" />
          </el-form-item>
        </template>

        </section>
        <section v-if="templateStep === 2">
        <el-divider content-position="left">广告组优化与定向</el-divider>
        <el-form-item label="成效目标">
          <el-select v-model="form.optimization_goal" filterable allow-create style="width: 100%">
            <el-option v-for="goal in optimizationGoalOptions(form.objective)" :key="goal.value" :label="`${goal.label} ${goal.value}`" :value="goal.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="计费事件">
          <el-select v-model="form.billing_event" filterable allow-create style="width: 100%">
            <el-option label="展示 IMPRESSIONS" value="IMPRESSIONS" />
            <el-option label="链接点击 LINK_CLICKS" value="LINK_CLICKS" />
          </el-select>
        </el-form-item>
        <el-form-item label="出价策略">
          <el-select v-model="form.bid_strategy" style="width:100%" placeholder="选择出价策略">
            <el-option label="最低成本（无上限）" value="LOWEST_COST_WITHOUT_CAP" />
            <el-option label="最低成本 + 竞价上限" value="LOWEST_COST_WITH_BID_CAP" />
            <el-option label="成本上限" value="COST_CAP" />
            <el-option label="最低 ROAS" value="LOWEST_COST_WITH_MIN_ROAS" />
          </el-select>
        </el-form-item>
        <el-alert v-if="form.objective === 'OUTCOME_SALES' && ['LINK_CLICKS', 'LANDING_PAGE_VIEWS'].includes(form.optimization_goal)" type="warning" :closable="false" show-icon title="销售目标不能使用链接点击或落地页浏览，请改用站外转化并配置转化事件" />
        <el-form-item v-if="['LOWEST_COST_WITH_BID_CAP', 'COST_CAP'].includes(form.bid_strategy)" label="竞价金额（最小货币单位）" required>
          <el-input-number v-model="form.bid_amount" :min="1" :step="100" style="width:100%" />
        </el-form-item>
        <el-form-item v-if="form.bid_strategy === 'LOWEST_COST_WITH_MIN_ROAS'" label="ROAS 约束 JSON" required>
          <el-input v-model="form.bid_constraints_json" type="textarea" :rows="3" placeholder='例如 {"roas_average_floor": 1.5}' />
        </el-form-item>
        <template v-if="isConversionOptimizationGoal(form.optimization_goal)">
          <el-alert type="info" :closable="false" show-icon title="转化事件源按发布预检校验">
            Pixel / 数据集仅在转化类优化目标发布时必需；模板可先保存，发布预检会在缺少事件源时拦截。
          </el-alert>
          <el-form-item label="Pixel / 数据集">
            <div class="tracking-source-input">
              <el-select v-model="form.tracking_asset_type" style="width:120px">
                <el-option label="Pixel" value="PIXEL" />
                <el-option label="数据集" value="DATASET" />
              </el-select>
              <el-input v-if="form.tracking_asset_type === 'PIXEL'" v-model="form.pixel_id" placeholder="Meta Pixel ID" />
              <el-input v-else v-model="form.dataset_id" placeholder="Meta Dataset ID" />
            </div>
          </el-form-item>
          <el-form-item label="转化事件">
            <el-select v-model="form.custom_event_type" filterable allow-create default-first-option style="width:100%" placeholder="选择 Meta 转化事件">
              <el-option v-for="event in STANDARD_CONVERSION_EVENTS" :key="event.value" :label="`${event.label} ${event.value}`" :value="event.value" />
            </el-select>
            <div class="tip">支持标准事件或自定义事件；自定义事件需以字母开头，仅允许字母、数字和下划线。</div>
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
        <el-form-item label="语言">
          <MetaLanguageSelect v-model="targetingForm.languages" />
        </el-form-item>
        <el-form-item label="版位">
          <el-select v-model="targetingForm.placements" multiple collapse-tags style="width:100%" placeholder="默认自动版位">
            <el-option label="Facebook 信息流" value="facebook_feed" />
            <el-option label="Instagram 信息流" value="instagram_stream" />
            <el-option label="Facebook 快拍" value="facebook_story" />
            <el-option label="Instagram 快拍" value="instagram_story" />
            <el-option label="Facebook Marketplace" value="facebook_marketplace" />
            <el-option label="Facebook 视频源" value="facebook_video_feeds" />
            <el-option label="Facebook 右侧栏" value="facebook_right_hand_column" />
            <el-option label="Facebook 搜索结果" value="facebook_search" />
            <el-option label="Facebook Reels" value="facebook_reels" />
            <el-option label="Facebook 插播视频" value="facebook_instream_video" />
            <el-option label="Facebook 主页动态" value="facebook_profile_feed" />
            <el-option label="Instagram Reels" value="instagram_reels" />
            <el-option label="Instagram 探索" value="instagram_explore" />
            <el-option label="Instagram 探索主页" value="instagram_explore_home" />
            <el-option label="Instagram 主页动态" value="instagram_profile_feed" />
            <el-option label="Audience Network 原生/横幅" value="audience_network_classic" />
            <el-option label="Audience Network 激励视频" value="audience_network_rewarded_video" />
            <el-option label="Audience Network 插播视频" value="audience_network_instream_video" />
            <el-option label="Messenger 主页" value="messenger_messenger_home" />
            <el-option label="Messenger 快拍" value="messenger_story" />
          </el-select>
        </el-form-item>
        <el-form-item label="多个广告组">
          <div class="adset-editor">
            <div v-for="(adset, index) in adsetForms" :key="index" class="adset-card">
              <div class="creative-head"><b>广告组 {{ index + 1 }}</b><el-button v-if="adsetForms.length > 1" link type="danger" @click="removeAdset(index)">删除</el-button></div>
              <el-form-item label="名称"><el-input v-model="adset.name" placeholder="例如 US 广告组" /></el-form-item>
              <div class="inline-fields"><el-form-item label="预算"><el-input-number v-model="adset.budget" :min="1" :step="10" /><span class="field-code">Meta: daily_budget</span></el-form-item><el-form-item label="国家/地区"><el-input v-model="adset.countries" placeholder="US,CA" /><span class="field-code">Meta: geo_locations</span></el-form-item></div>
              <el-collapse class="adset-advanced-settings">
                <el-collapse-item title="受众、地区排除与设备设置" name="targeting">
                  <div class="inline-fields"><el-form-item label="地区组"><el-select v-model="adset.region_group_id" filterable clearable style="width:100%" placeholder="选择已保存地区组" :loading="targetingResourcesLoading" @change="applyRegionGroup(adset, $event)"><el-option v-for="group in regionGroups" :key="group.id" :label="group.name" :value="group.id" /></el-select></el-form-item><el-form-item label="定向包"><el-select v-model="adset.targeting_package_id" filterable clearable style="width:100%" placeholder="选择已保存定向包" :loading="targetingResourcesLoading" @change="applyTargetingPackage(adset, $event)"><el-option v-for="item in targetingPackages" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item></div>
                  <div class="inline-fields"><el-form-item label="包含州/省"><el-input v-model="adset.regions" placeholder="Meta region key，多个值用逗号分隔" /></el-form-item><el-form-item label="包含城市"><el-input v-model="adset.cities" placeholder="Meta city key，多个值用逗号分隔" /></el-form-item></div>
                  <div class="inline-fields"><el-form-item label="包含邮编"><el-input v-model="adset.zips" placeholder="多个邮编用逗号分隔" /></el-form-item><el-form-item label="排除国家/地区"><el-input v-model="adset.excluded_countries" placeholder="CA,GB" /></el-form-item></div>
                  <div class="inline-fields"><el-form-item label="排除州/省"><el-input v-model="adset.excluded_regions" placeholder="Meta region key，多个值用逗号分隔" /></el-form-item><el-form-item label="排除城市"><el-input v-model="adset.excluded_cities" placeholder="Meta city key，多个值用逗号分隔" /></el-form-item></div>
                  <div class="inline-fields"><el-form-item label="排除邮编"><el-input v-model="adset.excluded_zips" placeholder="多个邮编用逗号分隔" /></el-form-item><el-form-item label="位置类型"><el-checkbox-group v-model="adset.location_types"><el-checkbox label="home">居住地</el-checkbox><el-checkbox label="recent">最近位置</el-checkbox></el-checkbox-group></el-form-item></div>
                  <el-form-item label="自定义位置 JSON"><el-input v-model="adset.custom_locations_json" type="textarea" :rows="2" placeholder='可选，Meta custom_locations 数组 JSON' /></el-form-item>
                  <el-form-item label="排除自定义位置 JSON"><el-input v-model="adset.excluded_custom_locations_json" type="textarea" :rows="2" placeholder='可选，Meta custom_locations 数组 JSON' /></el-form-item>
                  <el-form-item label="包含自定义受众"><el-input v-model="adset.custom_audiences" placeholder="Meta Audience ID；多账户用 account_id::audience_id" /></el-form-item>
                  <el-form-item label="排除自定义受众"><el-input v-model="adset.excluded_custom_audiences" placeholder="Meta Audience ID；多账户用 account_id::audience_id" /></el-form-item>
                  <div class="inline-fields"><el-form-item label="设备"><el-checkbox-group v-model="adset.device_platforms"><el-checkbox label="mobile">移动端</el-checkbox><el-checkbox label="desktop">桌面端</el-checkbox></el-checkbox-group></el-form-item><el-form-item label="系统"><el-input v-model="adset.user_os" placeholder="iOS,Android" /></el-form-item></div>
                  <div class="inline-fields"><el-form-item label="设备型号"><el-input v-model="adset.user_device" placeholder="iPhone 等，可选" /></el-form-item><el-form-item label="网络"><el-input v-model="adset.wireless_carrier" placeholder="WIFI 等，可选" /></el-form-item></div>
                </el-collapse-item>
              </el-collapse>
              <div class="inline-fields"><el-form-item label="年龄"><el-input-number v-model="adset.age_min" :min="13" :max="65" /><span>至</span><el-input-number v-model="adset.age_max" :min="13" :max="65" /></el-form-item><el-form-item label="性别"><el-checkbox-group v-model="adset.genders"><el-checkbox :label="1">男</el-checkbox><el-checkbox :label="2">女</el-checkbox></el-checkbox-group></el-form-item></div>
              <el-form-item label="兴趣"><el-input v-model="adset.interests" placeholder="可选，多个兴趣用逗号分隔" /></el-form-item>
              <el-form-item label="语言"><MetaLanguageSelect v-model="adset.languages" /></el-form-item>
              <div class="inline-fields"><el-form-item label="成效目标"><el-select v-model="adset.optimization_goal" style="width:100%"><el-option v-for="goal in optimizationGoalOptions(form.objective)" :key="goal.value" :label="goal.label" :value="goal.value" /></el-select><span class="field-code">Meta: optimization_goal</span></el-form-item><el-form-item label="计费事件"><el-select v-model="adset.billing_event" style="width:100%"><el-option label="展示次数" value="IMPRESSIONS" /><el-option label="链接点击" value="LINK_CLICKS" /></el-select><span class="field-code">Meta: billing_event</span></el-form-item></div>
              <div class="inline-fields"><el-form-item label="出价策略"><el-select v-model="adset.bid_strategy" style="width:100%"><el-option label="最低成本（无上限）" value="LOWEST_COST_WITHOUT_CAP" /><el-option label="最低成本（含竞价上限）" value="LOWEST_COST_WITH_BID_CAP" /><el-option label="成本上限" value="COST_CAP" /></el-select><span class="field-code">Meta: bid_strategy</span></el-form-item><el-form-item v-if="['LOWEST_COST_WITH_BID_CAP','COST_CAP'].includes(adset.bid_strategy)" label="竞价上限"><el-input-number v-model="adset.bid_amount" :min="1" :step="100" /><span class="field-code">Meta: bid_amount</span></el-form-item></div>
              <el-form-item label="Advantage+ 受众"><el-switch v-model="adset.advantage_audience" :active-value="1" :inactive-value="0" active-text="启用" inactive-text="关闭" /></el-form-item>
              <el-form-item label="版位"><el-select v-model="adset.placements" multiple collapse-tags style="width:100%" placeholder="默认自动版位"><el-option label="Facebook 信息流" value="facebook_feed" /><el-option label="Instagram 信息流" value="instagram_stream" /><el-option label="Facebook 快拍" value="facebook_story" /><el-option label="Instagram 快拍" value="instagram_story" /><el-option label="Facebook Marketplace" value="facebook_marketplace" /><el-option label="Facebook 视频源" value="facebook_video_feeds" /><el-option label="Facebook 右侧栏" value="facebook_right_hand_column" /><el-option label="Facebook 搜索结果" value="facebook_search" /><el-option label="Facebook Reels" value="facebook_reels" /><el-option label="Facebook 插播视频" value="facebook_instream_video" /><el-option label="Facebook 主页动态" value="facebook_profile_feed" /><el-option label="Instagram Reels" value="instagram_reels" /><el-option label="Instagram 探索" value="instagram_explore" /><el-option label="Instagram 探索主页" value="instagram_explore_home" /><el-option label="Instagram 主页动态" value="instagram_profile_feed" /><el-option label="Audience Network 原生/横幅" value="audience_network_classic" /><el-option label="Audience Network 激励视频" value="audience_network_rewarded_video" /><el-option label="Audience Network 插播视频" value="audience_network_instream_video" /><el-option label="Messenger 主页" value="messenger_messenger_home" /><el-option label="Messenger 快拍" value="messenger_story" /></el-select></el-form-item>
            </div>
            <el-button type="primary" plain @click="addAdset">+ 添加广告组</el-button>
          </div>
          <div class="tip">每个广告组独立保存预算、受众和版位；广告创意默认沿用下方创意配置。</div>
        </el-form-item>

        </section>
        <section v-if="templateStep === 3">
        <el-divider content-position="left">广告创意</el-divider>
        <el-form-item label="Facebook 页面" required>
          <div class="page-select-row">
            <el-select v-model="creativeForm.page_id" filterable class="page-select" placeholder="选择已授权的 Facebook 页面">
              <el-option v-for="page in metaPages" :key="page.page_id" :label="`${page.page_name} (${page.page_id})`" :value="page.page_id" />
            </el-select>
            <el-button type="primary" plain :loading="pagesSyncing" @click="syncMetaPages">同步 Facebook 页面</el-button>
          </div>
          <div v-if="!metaPages.length" class="tip page-sync-tip">
            暂无已同步页面，请先完成 Meta OAuth 授权或点击右侧按钮同步。
          </div>
        </el-form-item>
        <el-form-item label="素材形式">
          <el-radio-group v-model="creativeForm.creative_format">
            <el-radio value="SINGLE_IMAGE_VIDEO">单图片或视频</el-radio>
            <el-radio value="CAROUSEL">轮播</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="拆分方式">
          <el-radio-group v-model="creativeForm.delivery.split_level">
            <el-radio value="AD">每个素材生成一个广告</el-radio>
            <el-radio value="ADSET">按广告组拆分</el-radio>
          <el-radio value="CAMPAIGN" disabled>按广告系列拆分（后续开放）</el-radio>
          </el-radio-group>
        </el-form-item>
        <div class="tip">公共配置应用到全部素材；单图/视频会生成独立广告，轮播会把 2-10 张图片组合为 1 个广告。</div>
        <el-form-item label="公共主文案"><el-input v-model="creativeForm.shared.primary_text" type="textarea" :rows="2" placeholder="可不填" /></el-form-item>
        <el-form-item label="默认落地页"><el-input v-model="creativeForm.shared.landing_url" placeholder="https://example.com/landing" /></el-form-item>
        <el-form-item label="公共标题"><el-input v-model="creativeForm.shared.headline" /></el-form-item>
        <el-form-item label="公共描述"><el-input v-model="creativeForm.shared.description" /></el-form-item>
        <el-form-item label="公共行动号召"><el-select v-model="creativeForm.shared.cta" style="width:100%"><el-option v-for="cta in CTA_OPTIONS" :key="cta.value" :label="`${cta.label} ${cta.value}`" :value="cta.value" /></el-select></el-form-item>
        <div v-for="(creative, index) in creativeForm.creatives" :key="index" class="creative-block">
          <div class="creative-head"><b>{{ creativeForm.creative_format === 'CAROUSEL' ? `轮播卡片 ${index + 1}` : `创意 ${index + 1}` }}</b><el-button v-if="creativeForm.creatives.length > 1" link type="danger" @click="removeCreative(index)">删除</el-button></div>
          <el-form-item v-if="creativeForm.creative_format !== 'CAROUSEL'" label="素材类型">
            <el-radio-group v-model="creative.asset_type"><el-radio value="image">图片</el-radio><el-radio value="video">视频</el-radio></el-radio-group>
          </el-form-item>
          <el-form-item label="素材库素材" required>
            <el-select v-model="creative.asset_id" filterable style="width:100%" :placeholder="creativeForm.creative_format === 'CAROUSEL' ? '选择已同步图片' : '选择已上传素材'">
              <el-option v-for="asset in availableAssets(creativeForm.creative_format === 'CAROUSEL' ? 'image' : creative.asset_type)" :key="asset.id" :label="asset.name" :value="asset.id">
                <span>{{ asset.name }}</span><small class="asset-option-meta">{{ asset.asset_type === 'image' ? '图片' : '视频' }} · {{ asset.fb_hash || asset.fb_video_id || '待同步' }}</small>
              </el-option>
            </el-select>
            <div v-if="selectedAsset(creative.asset_id)" class="asset-selected">
              已选择：{{ selectedAsset(creative.asset_id)?.name }}
              <span v-if="!selectedAsset(creative.asset_id)?.fb_hash && !selectedAsset(creative.asset_id)?.fb_video_id" class="asset-sync-hint">模板可先保存，投放前需在素材库完成账户同步</span>
            </div>
            <div v-else class="tip">请先在“内容管理 → 素材库”上传素材；素材同步到广告账户可在投放前完成。</div>
          </el-form-item>
          <template v-if="creativeForm.creative_format !== 'CAROUSEL'">
            <el-form-item label="主文案覆盖"><el-input v-model="creative.primary_text" type="textarea" :rows="2" placeholder="可留空，使用公共主文案" /></el-form-item>
            <el-form-item label="标题覆盖"><el-input v-model="creative.headline" /></el-form-item>
            <el-form-item label="描述覆盖"><el-input v-model="creative.description" /></el-form-item>
            <el-form-item label="行动号召覆盖"><el-select v-model="creative.cta" clearable style="width:100%"><el-option v-for="cta in CTA_OPTIONS" :key="cta.value" :label="`${cta.label} ${cta.value}`" :value="cta.value" /></el-select></el-form-item>
            <el-form-item label="落地页覆盖"><el-input v-model="creative.landing_url" placeholder="可留空，使用公共默认落地页" /></el-form-item>
          </template>
        </div>
        <el-button class="add-creative" plain type="primary" @click="addCreative">{{ creativeForm.creative_format === 'CAROUSEL' ? '+ 添加轮播卡片' : '+ 添加创意' }}</el-button>
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
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { templatesApi, type CampaignTemplate } from '@/api/templates'
import MetaLanguageSelect from '@/components/MetaLanguageSelect.vue'
import { mediaApi, type MediaItem } from '@/api/media'
import { metaPagesApi, type MetaPage } from '@/api/metaPages'
import { regionGroupsApi, targetingPackagesApi, type RegionGroup, type TargetingPackage } from '@/api/targetingPackages'
import { useLocale } from '@/stores/localeStore'
import {
  CTA_OPTIONS,
  defaultOptimizationGoal,
  isConversionOptimizationGoal,
  isOptimizationGoalAllowed,
  optimizationGoalLabel,
  optimizationGoalOptions,
  STANDARD_CONVERSION_EVENTS,
} from '@/config/metaDeliveryRules'
const { t } = useLocale()

const templates = ref<CampaignTemplate[]>([])
const mediaAssets = ref<MediaItem[]>([])
const metaPages = ref<MetaPage[]>([])
const regionGroups = ref<RegionGroup[]>([])
const targetingPackages = ref<TargetingPackage[]>([])
const targetingResourcesLoading = ref(false)
const pagesSyncing = ref(false)
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
  objective: 'OUTCOME_TRAFFIC',
  buying_type: 'AUCTION',
  special_ad_categories: [] as string[],
  is_adset_budget_sharing_enabled: false,
  status: 'ACTIVE',
  budget_type: 'DAILY',
  daily_budget: 50,
  lifetime_budget: 0,
  schedule_start: '',
  schedule_end: '',
  optimization_goal: 'LANDING_PAGE_VIEWS',
  pixel_id: '',
  dataset_id: '',
  tracking_asset_type: 'PIXEL' as 'PIXEL' | 'DATASET',
  custom_event_type: 'PURCHASE',
  billing_event: 'IMPRESSIONS',
  bid_strategy: '',
  bid_amount: 0,
  bid_constraints_json: '',
  targeting_json: DEFAULT_TARGETING,
  creative_config_json: DEFAULT_CREATIVE,
  adsets_json: '[]',
})
const targetingForm = reactive({
  countries: 'US',
  age_min: 18,
  age_max: 65,
  genders: [1, 2] as number[],
  interests: '',
  languages: [] as string[],
  placements: [] as string[],
})
type AdsetForm = { name: string; budget: number; countries: string; regions: string; cities: string; zips: string; excluded_countries: string; excluded_regions: string; excluded_cities: string; excluded_zips: string; custom_locations_json: string; excluded_custom_locations_json: string; region_group_id: string; targeting_package_id: string; location_types: string[]; age_min: number; age_max: number; genders: number[]; interests: string; languages: string[]; custom_audiences: string; excluded_custom_audiences: string; device_platforms: string[]; user_os: string; user_device: string; wireless_carrier: string; placements: string[]; optimization_goal: string; billing_event: string; bid_strategy: string; bid_amount: number; advantage_audience: number }
const newAdset = (): AdsetForm => ({ name: '', budget: 50, countries: 'US', regions: '', cities: '', zips: '', excluded_countries: '', excluded_regions: '', excluded_cities: '', excluded_zips: '', custom_locations_json: '', excluded_custom_locations_json: '', region_group_id: '', targeting_package_id: '', location_types: ['home', 'recent'], age_min: 18, age_max: 65, genders: [1, 2], interests: '', languages: [], custom_audiences: '', excluded_custom_audiences: '', device_platforms: [], user_os: '', user_device: '', wireless_carrier: '', placements: [], optimization_goal: defaultOptimizationGoal(form.objective), billing_event: 'IMPRESSIONS', bid_strategy: 'LOWEST_COST_WITHOUT_CAP', bid_amount: 0, advantage_audience: 1 })
const placementGroups = [
  { platform: 'facebook', prefix: 'facebook', field: 'facebook_positions' },
  { platform: 'instagram', prefix: 'instagram', field: 'instagram_positions' },
  { platform: 'audience_network', prefix: 'audience_network', field: 'audience_network_positions' },
  { platform: 'messenger', prefix: 'messenger', field: 'messenger_positions' },
] as const
const placementPlatform = (value: string) => {
  if (value.startsWith('audience_network_')) return 'audience_network'
  if (value.startsWith('messenger_')) return 'messenger'
  if (value.startsWith('instagram_')) return 'instagram'
  return 'facebook'
}
const placementConfigFromValues = (values: string[]) => {
  const uniqueValues = [...new Set(values)]
  if (!uniqueValues.length) return {}
  const placement: Record<string, any> = { publisher_platforms: [...new Set(uniqueValues.map(placementPlatform))] }
  for (const group of placementGroups) {
    const positions = uniqueValues.filter(value => value.startsWith(`${group.prefix}_`)).map(value => value.slice(group.prefix.length + 1))
    if (positions.length) placement[group.field] = positions
  }
  return placement
}
const placementValuesFromConfig = (placement: Record<string, any> | null | undefined, withDefaults = false) => {
  const config = placement || {}
  const values: string[] = []
  for (const group of placementGroups) {
    const positions = Array.isArray(config[group.field]) ? config[group.field] : []
    if (positions.length) values.push(...positions.map((value: string) => `${group.prefix}_${value}`))
    else if (withDefaults && (config.publisher_platforms || []).includes(group.platform)) {
      if (group.platform === 'facebook') values.push('facebook_feed')
      if (group.platform === 'instagram') values.push('instagram_stream')
    }
  }
  return [...new Set(values)]
}
const adsetForms = reactive<AdsetForm[]>([newAdset()])
const addAdset = () => adsetForms.push(newAdset())
const removeAdset = (index: number) => adsetForms.splice(index, 1)
const splitTargetingValues = (value: string | string[]) => (Array.isArray(value) ? value : value.split(','))
  .map(item => String(item).trim()).filter(Boolean)
const stringifyGeoValues = (value: any) => {
  if (!Array.isArray(value) || !value.length) return ''
  return value.some(item => item && typeof item === 'object') ? JSON.stringify(value) : value.join(',')
}
const parseGeoValues = (value: string, label: string, allowObjects = false) => {
  const text = String(value || '').trim()
  if (!text) return []
  if (!text.startsWith('[')) return splitTargetingValues(text)
  try {
    const parsed = JSON.parse(text)
    if (!Array.isArray(parsed) || (!allowObjects && parsed.some(item => item && typeof item === 'object'))) throw new Error('invalid')
    return parsed
  } catch {
    throw new Error(`${label}必须是数组 JSON`)
  }
}
const audienceToken = (value: any) => {
  const raw = typeof value === 'string' ? value.trim() : ''
  if (raw.includes('::')) return raw
  const id = value?.id || value?.meta_audience_id || value
  const account = value?.ad_account_id || value?.account_id
  return account && id ? `${account}::${id}` : id
}
const audienceRef = (value: any) => {
  const token = String(audienceToken(value) || '')
  const separator = token.indexOf('::')
  return separator > 0
    ? { id: token.slice(separator + 2), ad_account_id: token.slice(0, separator) }
    : token
}
const applyRegionGroup = (adset: AdsetForm, groupId: string) => {
  const group = regionGroups.value.find(item => item.id === groupId)
  if (!group) return
  const geo = group.geo_locations || {}
  if (!Object.keys(geo).some(key => ['countries', 'regions', 'cities', 'zips', 'custom_locations'].includes(key) && Array.isArray(geo[key]) && geo[key].length)) {
    adset.region_group_id = ''
    ElMessage.warning('该地区组没有可用的包含地区配置')
    return
  }
  adset.countries = stringifyGeoValues(geo.countries)
  adset.regions = stringifyGeoValues(geo.regions)
  adset.cities = stringifyGeoValues(geo.cities)
  adset.zips = stringifyGeoValues(geo.zips)
  adset.custom_locations_json = Array.isArray(geo.custom_locations) ? JSON.stringify(geo.custom_locations) : ''
  adset.excluded_countries = stringifyGeoValues(group.excluded_geo_locations?.countries)
  adset.excluded_regions = stringifyGeoValues(group.excluded_geo_locations?.regions)
  adset.excluded_cities = stringifyGeoValues(group.excluded_geo_locations?.cities)
  adset.excluded_zips = stringifyGeoValues(group.excluded_geo_locations?.zips)
  adset.excluded_custom_locations_json = Array.isArray(group.excluded_geo_locations?.custom_locations) ? JSON.stringify(group.excluded_geo_locations.custom_locations) : ''
  adset.location_types = Array.isArray(geo.location_types) && geo.location_types.length ? [...geo.location_types] : ['home', 'recent']
  ElMessage.success(`已加载地区组：${group.name}`)
}
const applyTargetingPackage = (adset: AdsetForm, packageId: string) => {
  const item = targetingPackages.value.find(packageItem => packageItem.id === packageId)
  if (!item) return
  const targeting = item.targeting_json || {}
  const geo = targeting.geo_locations || {}
  const hasGeo = ['countries', 'regions', 'cities', 'zips', 'custom_locations'].some(field => Array.isArray(geo[field]) && geo[field].length)
  adset.region_group_id = item.region_group_ids?.length === 1 ? item.region_group_ids[0] : ''
  adset.countries = stringifyGeoValues(geo.countries) || (hasGeo ? '' : 'US')
  adset.regions = stringifyGeoValues(geo.regions)
  adset.cities = stringifyGeoValues(geo.cities)
  adset.zips = stringifyGeoValues(geo.zips)
  adset.custom_locations_json = Array.isArray(geo.custom_locations) ? JSON.stringify(geo.custom_locations) : ''
  adset.excluded_countries = stringifyGeoValues(targeting.excluded_geo_locations?.countries)
  adset.excluded_regions = stringifyGeoValues(targeting.excluded_geo_locations?.regions)
  adset.excluded_cities = stringifyGeoValues(targeting.excluded_geo_locations?.cities)
  adset.excluded_zips = stringifyGeoValues(targeting.excluded_geo_locations?.zips)
  adset.excluded_custom_locations_json = Array.isArray(targeting.excluded_geo_locations?.custom_locations) ? JSON.stringify(targeting.excluded_geo_locations.custom_locations) : ''
  adset.location_types = Array.isArray(geo.location_types) && geo.location_types.length ? [...geo.location_types] : ['home', 'recent']
  adset.age_min = Number(targeting.age_min || 18)
  adset.age_max = Number(targeting.age_max || 65)
  adset.genders = Array.isArray(targeting.genders) ? [...targeting.genders] : [1, 2]
  adset.interests = (targeting.flexible_spec?.[0]?.interests || []).map((value: any) => value.name || '').filter(Boolean).join(',')
  adset.languages = Array.isArray(targeting.languages) ? [...targeting.languages] : []
  adset.custom_audiences = (targeting.custom_audiences || []).map(audienceToken).filter(Boolean).join(',')
  adset.excluded_custom_audiences = (targeting.excluded_custom_audiences || targeting.excluded_audiences || []).map(audienceToken).filter(Boolean).join(',')
  adset.device_platforms = Array.isArray(targeting.device_platforms) ? [...targeting.device_platforms] : []
  adset.user_os = Array.isArray(targeting.user_os) ? targeting.user_os.join(',') : String(targeting.user_os || '')
  adset.user_device = Array.isArray(targeting.user_device) ? targeting.user_device.join(',') : String(targeting.user_device || '')
  adset.wireless_carrier = Array.isArray(targeting.wireless_carrier) ? targeting.wireless_carrier.join(',') : String(targeting.wireless_carrier || '')
  adset.placements = placementValuesFromConfig(item.placement_json, true)
  ElMessage.success(`已加载定向包：${item.name}`)
}
watch(() => form.objective, objective => {
  if (!isOptimizationGoalAllowed(objective, form.optimization_goal)) form.optimization_goal = defaultOptimizationGoal(objective)
  adsetForms.forEach(item => {
    if (!isOptimizationGoalAllowed(objective, item.optimization_goal)) item.optimization_goal = defaultOptimizationGoal(objective)
  })
})
type CreativeForm = { asset_type: 'image' | 'video'; image_hash: string; video_id: string; headline: string; primary_text: string; description: string; cta: string; landing_url: string; asset_id: string }
const newCreative = (): CreativeForm => ({ asset_type: 'image', image_hash: '', video_id: '', headline: '', primary_text: '', description: '', cta: 'LEARN_MORE', landing_url: '', asset_id: '' })
const creativeForm = reactive<{ page_id: string; creative_format: 'SINGLE_IMAGE_VIDEO' | 'CAROUSEL'; delivery: { split_level: 'AD' | 'ADSET' | 'CAMPAIGN'; combination_mode: string }; shared: Omit<CreativeForm, 'asset_type' | 'asset_id' | 'image_hash' | 'video_id'>; creatives: CreativeForm[] }>({ page_id: '', creative_format: 'SINGLE_IMAGE_VIDEO', delivery: { split_level: 'AD', combination_mode: 'ACCOUNT_X_ADSET_X_CREATIVE' }, shared: { headline: '', primary_text: '', description: '', cta: 'LEARN_MORE', landing_url: '' }, creatives: [newCreative()] })
// 异步素材流程使用大写 READY；兼容历史数据中的小写 ready。
const availableAssets = (type: string) => mediaAssets.value.filter(
  asset => asset.asset_type === type && String(asset.status).toUpperCase() === 'READY',
)
const selectedAsset = (id: string) => mediaAssets.value.find(asset => asset.id === id)
const addCreative = () => creativeForm.creatives.push(newCreative())
const removeCreative = (index: number) => creativeForm.creatives.splice(index, 1)
watch(() => creativeForm.creative_format, format => {
  if (format === 'CAROUSEL') {
    creativeForm.delivery.split_level = 'AD'
    creativeForm.creatives.forEach(item => {
      if (item.asset_type === 'video') {
        item.asset_type = 'image'
        item.asset_id = ''
        item.video_id = ''
      }
    })
  }
})
const buildCreativeJson = () => {
  const creativeItems = creativeForm.creatives.map(item => {
    const asset = selectedAsset(item.asset_id)
    const merged = { ...creativeForm.shared, ...item }
    for (const field of ['headline', 'primary_text', 'description', 'cta', 'landing_url']) if (item[field] === '' || item[field] == null) merged[field] = creativeForm.shared[field]
    const result = { ...merged } as Record<string, any>
    if (asset?.fb_hash || item.image_hash) result.image_hash = asset?.fb_hash || item.image_hash
    else delete result.image_hash
    if (asset?.fb_video_id || item.video_id) result.video_id = asset?.fb_video_id || item.video_id
    else delete result.video_id
    return result
  })
  const config: Record<string, any> = {
    page_id: creativeForm.page_id,
    shared_creative: { ...creativeForm.shared },
    creative_format: creativeForm.creative_format,
    delivery: { ...creativeForm.delivery },
  }
  if (creativeForm.creative_format === 'CAROUSEL') config.carousel_cards = creativeItems
  else config.creatives = creativeItems
  if (form.budget_type === 'LIFETIME') {
    config.schedule = { start_time: form.schedule_start || undefined, end_time: form.schedule_end }
  }
  const trackingAssetId = form.tracking_asset_type === 'DATASET' ? form.dataset_id.trim() : form.pixel_id.trim()
  if (isConversionOptimizationGoal(form.optimization_goal) && trackingAssetId && form.custom_event_type.trim()) {
    config.promoted_object = form.tracking_asset_type === 'DATASET'
      ? { dataset_id: trackingAssetId, conversion_event: form.custom_event_type }
      : { pixel_id: trackingAssetId, custom_event_type: form.custom_event_type }
    if (form.tracking_asset_type === 'DATASET') config.dataset_id = trackingAssetId
  }
  const adsets = adsetForms.map(adset => {
    const geo_locations: Record<string, any> = {}
    for (const [field, value] of [['countries', adset.countries], ['regions', adset.regions], ['cities', adset.cities], ['zips', adset.zips]] as const) {
      const parsed = parseGeoValues(value, `广告组${field}`, field !== 'countries')
      if (parsed.length) geo_locations[field] = parsed
    }
    if (adset.custom_locations_json.trim()) geo_locations.custom_locations = parseGeoValues(adset.custom_locations_json, '自定义位置', true)
    const targeting: Record<string, any> = { geo_locations, age_min: adset.age_min, age_max: adset.age_max, genders: adset.genders }
    if (adset.location_types.length) targeting.geo_locations.location_types = [...adset.location_types]
    const excluded_geo_locations: Record<string, any> = {}
    for (const [field, value] of [['countries', adset.excluded_countries], ['regions', adset.excluded_regions], ['cities', adset.excluded_cities], ['zips', adset.excluded_zips]] as const) {
      const parsed = parseGeoValues(value, `排除广告组${field}`, field !== 'countries')
      if (parsed.length) excluded_geo_locations[field] = parsed
    }
    if (adset.excluded_custom_locations_json.trim()) excluded_geo_locations.custom_locations = parseGeoValues(adset.excluded_custom_locations_json, '排除自定义位置', true)
    if (Object.keys(excluded_geo_locations).length) targeting.excluded_geo_locations = excluded_geo_locations
    if (adset.languages.length) targeting.languages = [...adset.languages]
    if (adset.interests.trim()) targeting.flexible_spec = [{ interests: adset.interests.split(',').map(v => ({ name: v.trim() })).filter(v => v.name) }]
    const audiences = splitTargetingValues(adset.custom_audiences).map(audienceRef)
    const excludedAudiences = splitTargetingValues(adset.excluded_custom_audiences).map(audienceRef)
    if (audiences.length) targeting.custom_audiences = audiences
    if (excludedAudiences.length) targeting.excluded_custom_audiences = excludedAudiences
    if (adset.device_platforms.length) targeting.device_platforms = [...adset.device_platforms]
    if (adset.user_os.trim()) targeting.user_os = splitTargetingValues(adset.user_os)
    if (adset.user_device.trim()) targeting.user_device = splitTargetingValues(adset.user_device)
    if (adset.wireless_carrier.trim()) targeting.wireless_carrier = splitTargetingValues(adset.wireless_carrier)
    const placement = placementConfigFromValues(adset.placements)
    targeting.targeting_automation = { advantage_audience: adset.advantage_audience }
    return { name: adset.name, budget: adset.budget, optimization_goal: adset.optimization_goal, billing_event: adset.billing_event, bid_strategy: adset.bid_strategy, bid_amount: adset.bid_amount || undefined, targeting, placement }
  }).filter(adset => adset.name || Object.keys(adset.targeting?.geo_locations || {}).some(key => key !== 'location_types'))
  if (adsets.length) config.adsets = adsets
  if (form.bid_strategy) {
    config.bidding = { bid_amount: form.bid_amount || undefined }
    if (form.bid_strategy === 'LOWEST_COST_WITH_MIN_ROAS' && form.bid_constraints_json.trim()) {
      try { config.bidding.bid_constraints = JSON.parse(form.bid_constraints_json) } catch { ElMessage.error('ROAS 约束必须是合法 JSON') }
    }
  }
  form.creative_config_json = JSON.stringify(config, null, 2)
}
const loadCreativeForm = (value: Record<string, any> | null | undefined) => {
  const cfg = value || {}
  creativeForm.page_id = cfg.page_id || ''
  creativeForm.creative_format = cfg.creative_format === 'CAROUSEL' ? 'CAROUSEL' : 'SINGLE_IMAGE_VIDEO'
  creativeForm.delivery.split_level = ['AD', 'ADSET', 'CAMPAIGN'].includes(cfg.delivery?.split_level) ? cfg.delivery.split_level : 'AD'
  creativeForm.delivery.combination_mode = cfg.delivery?.combination_mode || 'ACCOUNT_X_ADSET_X_CREATIVE'
  const source = creativeForm.creative_format === 'CAROUSEL'
    ? (Array.isArray(cfg.carousel_cards) ? cfg.carousel_cards : cfg.creatives)
    : cfg.creatives
  const first = Array.isArray(source) && source.length ? source[0] : {}
  creativeForm.shared = { headline: cfg.shared_creative?.headline || first.headline || '', primary_text: cfg.shared_creative?.primary_text || first.primary_text || '', description: cfg.shared_creative?.description || first.description || '', cta: cfg.shared_creative?.cta || first.cta || 'LEARN_MORE', landing_url: cfg.shared_creative?.landing_url || first.landing_url || '' }
  form.schedule_start = cfg.schedule?.start_time || ''
  form.schedule_end = cfg.schedule?.end_time || ''
  const datasetId = cfg.promoted_object?.dataset_id || cfg.dataset_id || ''
  const pixelId = cfg.promoted_object?.pixel_id || cfg.pixel_id || ''
  form.tracking_asset_type = datasetId ? 'DATASET' : 'PIXEL'
  form.dataset_id = datasetId
  form.pixel_id = pixelId
  form.custom_event_type = cfg.promoted_object?.conversion_event || cfg.promoted_object?.custom_event_type || cfg.conversion_event || 'PURCHASE'
  creativeForm.creatives.splice(0, creativeForm.creatives.length, ...(Array.isArray(source) && source.length ? source.map((item: any) => ({ ...newCreative(), ...item })) : [newCreative()]))
}
const buildTargetingJson = () => {
  const targeting: Record<string, any> = {
    geo_locations: { countries: targetingForm.countries.split(',').map(v => v.trim()).filter(Boolean) },
    age_min: targetingForm.age_min,
    age_max: targetingForm.age_max,
    genders: targetingForm.genders,
  }
  if (targetingForm.languages.length) targeting.languages = [...targetingForm.languages]
  if (targetingForm.interests.trim()) targeting.flexible_spec = [{ interests: targetingForm.interests.split(',').map(v => ({ name: v.trim() })).filter(v => v.name) }]
  if (targetingForm.placements.length) {
    Object.assign(targeting, placementConfigFromValues(targetingForm.placements))
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
  targetingForm.languages = Array.isArray(targeting.languages) ? [...targeting.languages] : []
  targetingForm.placements = placementValuesFromConfig(targeting)
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
const loadTargetingResources = async () => {
  targetingResourcesLoading.value = true
  try {
    const [regions, packages] = await Promise.all([
      regionGroupsApi.list(),
      targetingPackagesApi.list(),
    ])
    regionGroups.value = regions.data || []
    targetingPackages.value = packages.data || []
  } catch {
    regionGroups.value = []
    targetingPackages.value = []
  } finally {
    targetingResourcesLoading.value = false
  }
}
const syncMetaPages = async () => {
  pagesSyncing.value = true
  try {
    const { data } = await metaPagesApi.syncAll()
    await loadMetaPages()
    const failed = data?.results?.find((item: any) => item.status === 'FAILED')
    const conflictCount = Number(data?.conflict_count || 0)
    if (data?.status === 'FAILED') ElMessage.error(failed?.error || 'Facebook 页面同步失败，请重新授权')
    else if (conflictCount) ElMessage.warning(`${conflictCount} 个 Facebook 页面已绑定其他授权，请使用对应 Connector 凭据单独同步`)
    else if (data?.status === 'PARTIAL_SUCCESS') ElMessage.warning(failed?.error || '部分 Facebook 页面同步失败，请检查授权状态')
    else if (!metaPages.value.length) ElMessage.warning('当前授权未返回可用的 Facebook 页面')
    else ElMessage.success(`已同步 ${metaPages.value.length} 个 Facebook 页面`)
  } catch (e: any) {
    ElMessage.error(String(e?.response?.data?.detail || e?.message || 'Facebook 页面同步失败，请检查 Meta 授权状态'))
  } finally { pagesSyncing.value = false }
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
  form.optimization_goal = 'OFFSITE_CONVERSIONS'
  form.pixel_id = ''
  form.dataset_id = ''
  form.tracking_asset_type = 'PIXEL'
  form.custom_event_type = 'PURCHASE'
  form.billing_event = 'IMPRESSIONS'
  form.bid_strategy = ''
  form.bid_amount = 0
  form.bid_constraints_json = ''
  form.targeting_json = DEFAULT_TARGETING
  form.creative_config_json = DEFAULT_CREATIVE
  form.adsets_json = '[]'
  adsetForms.splice(0, adsetForms.length, newAdset())
  loadCreativeForm(JSON.parse(DEFAULT_CREATIVE))
  loadTargetingForm(JSON.parse(DEFAULT_TARGETING))
}

const openCreate = () => {
  resetForm()
  loadMediaAssets()
  loadMetaPages()
  loadTargetingResources()
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
  form.optimization_goal = row.optimization_goal || defaultOptimizationGoal(form.objective)
  form.billing_event = row.billing_event || 'IMPRESSIONS'
  form.bid_strategy = row.bid_strategy || ''
  form.bid_amount = row.creative_config_json?.bidding?.bid_amount || 0
  form.bid_constraints_json = row.creative_config_json?.bidding?.bid_constraints ? JSON.stringify(row.creative_config_json.bidding.bid_constraints, null, 2) : ''
  form.targeting_json = JSON.stringify(row.targeting_json ?? {}, null, 2)
  loadTargetingForm(row.targeting_json)
  form.creative_config_json = JSON.stringify(row.creative_config_json ?? {}, null, 2)
  form.adsets_json = JSON.stringify(row.creative_config_json?.adsets ?? [], null, 2)
  const savedAdsets = row.creative_config_json?.adsets
  adsetForms.splice(0, adsetForms.length, ...(Array.isArray(savedAdsets) && savedAdsets.length ? savedAdsets.map((item: any) => {
    const targeting = item.targeting || {}
    const hasGeo = ['countries', 'regions', 'cities', 'zips', 'custom_locations'].some(field => Array.isArray(targeting.geo_locations?.[field]) && targeting.geo_locations[field].length)
    const audiences = (targeting.custom_audiences || []).map(audienceToken).filter(Boolean)
    const excludedAudiences = (targeting.excluded_custom_audiences || targeting.excluded_audiences || []).map(audienceToken).filter(Boolean)
    return {
      ...newAdset(),
      name: item.name || '',
      budget: item.budget || 50,
      countries: stringifyGeoValues(targeting.geo_locations?.countries) || (hasGeo ? '' : 'US'),
      regions: stringifyGeoValues(targeting.geo_locations?.regions),
      cities: stringifyGeoValues(targeting.geo_locations?.cities),
      zips: stringifyGeoValues(targeting.geo_locations?.zips),
      excluded_countries: stringifyGeoValues(targeting.excluded_geo_locations?.countries),
      excluded_regions: stringifyGeoValues(targeting.excluded_geo_locations?.regions),
      excluded_cities: stringifyGeoValues(targeting.excluded_geo_locations?.cities),
      excluded_zips: stringifyGeoValues(targeting.excluded_geo_locations?.zips),
      custom_locations_json: Array.isArray(targeting.geo_locations?.custom_locations) ? JSON.stringify(targeting.geo_locations.custom_locations) : '',
      excluded_custom_locations_json: Array.isArray(targeting.excluded_geo_locations?.custom_locations) ? JSON.stringify(targeting.excluded_geo_locations.custom_locations) : '',
      location_types: Array.isArray(targeting.geo_locations?.location_types) ? [...targeting.geo_locations.location_types] : ['home', 'recent'],
      age_min: targeting.age_min || 18,
      age_max: targeting.age_max || 65,
      genders: targeting.genders || [1, 2],
      interests: (targeting.flexible_spec?.[0]?.interests || []).map((v: any) => v.name || '').join(','),
      languages: Array.isArray(targeting.languages) ? [...targeting.languages] : [],
      custom_audiences: audiences.join(','),
      excluded_custom_audiences: excludedAudiences.join(','),
      device_platforms: Array.isArray(targeting.device_platforms) ? [...targeting.device_platforms] : [],
      user_os: Array.isArray(targeting.user_os) ? targeting.user_os.join(',') : String(targeting.user_os || ''),
      user_device: Array.isArray(targeting.user_device) ? targeting.user_device.join(',') : String(targeting.user_device || ''),
      wireless_carrier: Array.isArray(targeting.wireless_carrier) ? targeting.wireless_carrier.join(',') : String(targeting.wireless_carrier || ''),
      placements: placementValuesFromConfig(item.placement),
    }
  }) : [newAdset()]))
  loadCreativeForm(row.creative_config_json)
  loadMediaAssets()
  loadMetaPages()
  loadTargetingResources()
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

const validateAdsetTargeting = () => {
  for (let index = 0; index < adsetForms.length; index++) {
    const adset = adsetForms[index]
    const label = `广告组 ${index + 1}`
    let geo: Record<string, any> = {}
    let excludedGeo: Record<string, any> = {}
    try {
      for (const [field, value] of [['countries', adset.countries], ['regions', adset.regions], ['cities', adset.cities], ['zips', adset.zips]] as const) {
        const parsed = parseGeoValues(value, `${label} ${field}`, field !== 'countries')
        if (parsed.length) geo[field] = parsed
      }
      if (adset.custom_locations_json.trim()) geo.custom_locations = parseGeoValues(adset.custom_locations_json, `${label} 自定义位置`, true)
      for (const [field, value] of [['countries', adset.excluded_countries], ['regions', adset.excluded_regions], ['cities', adset.excluded_cities], ['zips', adset.excluded_zips]] as const) {
        const parsed = parseGeoValues(value, `${label} 排除${field}`, field !== 'countries')
        if (parsed.length) excludedGeo[field] = parsed
      }
      if (adset.excluded_custom_locations_json.trim()) excludedGeo.custom_locations = parseGeoValues(adset.excluded_custom_locations_json, `${label} 排除自定义位置`, true)
    } catch (error: any) {
      ElMessage.warning(error?.message || `${label}地区 JSON 格式无效`)
      templateStep.value = 2
      return false
    }
    const geoFields = ['countries', 'regions', 'cities', 'zips', 'custom_locations']
    if (!geoFields.some(field => Array.isArray(geo[field]) && geo[field].length)) {
      ElMessage.warning(`${label}至少需要配置一个国家、地区、城市、邮编或自定义位置`)
      templateStep.value = 2
      return false
    }
    const countries = Array.isArray(geo.countries) ? geo.countries.map(value => String(value)) : []
    const excludedCountries = Array.isArray(excludedGeo.countries) ? excludedGeo.countries.map(value => String(value)) : []
    const countryOverlap = countries.map(value => value.toUpperCase()).filter(value => excludedCountries.map(item => item.toUpperCase()).includes(value))
    if (countryOverlap.length) {
      ElMessage.warning(`${label}包含和排除的国家/地区重复：${[...new Set(countryOverlap)].join(', ')}`)
      templateStep.value = 2
      return false
    }
    if (adset.age_min < 13 || adset.age_max > 65 || adset.age_min > adset.age_max) {
      ElMessage.warning(`${label}年龄范围必须在 13 至 65 岁之间，且最小年龄不能大于最大年龄`)
      templateStep.value = 2
      return false
    }
    if (!adset.genders.length) {
      ElMessage.warning(`${label}至少需要选择一个性别`)
      templateStep.value = 2
      return false
    }
    const included = splitTargetingValues(adset.custom_audiences)
    const excluded = splitTargetingValues(adset.excluded_custom_audiences)
    const audienceId = (value: string) => value.includes('::') ? value.slice(value.indexOf('::') + 2).trim() : value
    const invalidScoped = [...included, ...excluded].find(value => value.includes('::') && value.split('::').length !== 2)
    if (invalidScoped) {
      ElMessage.warning(`${label}的受众格式无效，请使用 account_id::audience_id`)
      templateStep.value = 2
      return false
    }
    const includedIds = new Set(included.map(audienceId))
    const audienceOverlap = excluded.map(audienceId).filter(value => includedIds.has(value))
    if (audienceOverlap.length) {
      ElMessage.warning(`${label}包含和排除的自定义受众重复：${[...new Set(audienceOverlap)].join(', ')}`)
      templateStep.value = 2
      return false
    }
    const invalidDevices = adset.device_platforms.filter(value => !['mobile', 'desktop'].includes(value))
    if (invalidDevices.length) {
      ElMessage.warning(`${label}的设备只能选择移动端或桌面端`)
      templateStep.value = 2
      return false
    }
  }
  return true
}

const submit = async () => {
  if (!form.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }
  if (form.objective === 'OUTCOME_SALES' && ['LINK_CLICKS', 'LANDING_PAGE_VIEWS'].includes(form.optimization_goal)) {
    ElMessage.warning('销售目标不能使用链接点击/落地页浏览，请改用流量目标或配置转化优化')
    templateStep.value = 1
    return
  }
  if (form.budget_type === 'LIFETIME' && !form.schedule_end) {
    ElMessage.warning('总预算模板必须设置结束时间')
    templateStep.value = 1
    return
  }
  if (!validateAdsetTargeting()) return
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
    if (creativeForm.creative_format === 'CAROUSEL' && asset.asset_type !== 'image') {
      ElMessage.warning(`轮播卡片 ${i + 1} 必须使用图片素材`)
      templateStep.value = 3
      return
    }
    const landingUrl = creative.landing_url || creativeForm.shared.landing_url
    if (asset.asset_type !== 'video' || landingUrl) {
      try {
        const url = new URL(landingUrl)
        if (!['http:', 'https:'].includes(url.protocol)) throw new Error('invalid')
      } catch {
        ElMessage.warning(`创意 ${i + 1} 的落地页必须是有效的 http/https URL`)
        templateStep.value = 3
        return
      }
    }
  }
  if (creativeForm.creative_format === 'CAROUSEL' && (creativeForm.creatives.length < 2 || creativeForm.creatives.length > 10)) {
    ElMessage.warning('轮播广告需要 2-10 张图片')
    templateStep.value = 3
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
  if (cfg?.creative_format === 'CAROUSEL') return Array.isArray(cfg.carousel_cards) ? cfg.carousel_cards.length : 0
  if (Array.isArray(cfg?.creatives)) return cfg.creatives.length
  return cfg && Object.keys(cfg).length ? 1 : 0
}

onMounted(() => {
  loadTemplates()
  loadTargetingResources()
})
</script>

<style scoped lang="scss">
.adset-editor { width: 100%; }
.adset-card { border: 1px solid #dcdfe6; border-radius: 6px; padding: 12px; margin-bottom: 10px; background: #fafcff; }
.adset-card :deep(.el-form-item) { margin-bottom: 10px; }
.adset-card :deep(.el-form-item__label) { width: 150px !important; white-space: nowrap; padding-right: 10px; }
.adset-card :deep(.el-form-item__content) { min-width: 0; }
.field-code { display: block; color: #909399; font-size: 11px; line-height: 1.3; margin-top: 4px; }
.adset-card .inline-fields { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 900px) {
  .adset-card .inline-fields { grid-template-columns: 1fr; gap: 0; }
  .adset-card :deep(.el-form-item__label) { width: 145px !important; }
}
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;

  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; max-width: 760px; }
}
.tip { color: #909399; font-size: 12px; margin-top: 4px; line-height: 1.5; }
.tracking-source-input { display: flex; gap: 8px; width: 100%; }
.tracking-source-input > .el-input { flex: 1; }
.page-select-row { display: flex; align-items: center; gap: 10px; width: 100%; }
.page-select { flex: 1; min-width: 0; }
.page-sync-tip { color: #8a98aa; }
@media (max-width: 680px) {
  .page-select-row { align-items: stretch; flex-direction: column; }
  .page-select-row .el-button { width: 100%; }
}
.inline-fields { display: flex; align-items: center; gap: 10px; }
.template-steps { margin-bottom: 20px; }
.creative-block { margin: 14px 0 20px; padding: 16px 18px 6px; border: 1px solid #ebeef5; border-radius: 8px; background: #fafcff; }
.creative-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; color: #243b53; }
.add-creative { margin-left: 120px; margin-bottom: 8px; }
.asset-option-meta { float: right; margin-left: 18px; color: #909399; }
.asset-selected { margin-top: 6px; color: #67c23a; font-size: 12px; }
</style>

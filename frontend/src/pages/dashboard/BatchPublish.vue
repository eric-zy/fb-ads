<template>
  <div class="batch-publish">
    <el-card shadow="never">
      <template #header>
        <div class="header-bar">
          <div>
            <h2 class="page-title">{{ t('pages.batch') }}</h2>
            <p class="page-desc">
              选择<b>投放模板或直接配置</b>与目标广告账户，系统按「配置 → 账户」生成部署任务：
              每个账户独立创建 Campaign / AdSet / Ad，全部进入队列异步执行，
              可实时查看进度、失败可单独重跑。
            </p>
          </div>
        </div>
      </template>

      <el-alert
        v-if="editSource"
        type="warning"
        :closable="false"
        show-icon
        title="编辑后重投"
        style="margin-bottom: 16px"
      >
        当前基于任务 {{ editSource.source_job_id }} 创建修订版，仅默认选择原任务失败账户；原任务不会被修改。
        <span v-if="editSource.errors.length">最近失败原因：{{ editSource.errors[0].message }}</span>
      </el-alert>

      <div v-if="editSource" class="revision-toolbar">
        <div>
          <el-tag size="small" type="info">修订草稿 v{{ revisionRecord?.version || (editSource.revision_no + 1) }}</el-tag>
          <el-tag v-if="revisionRecord" size="small" :type="revisionRecord.status === 'READY' ? 'success' : revisionRecord.status === 'SUBMITTED' ? 'warning' : 'info'" style="margin-left: 6px">
            {{ revisionRecord.status }}
          </el-tag>
          <span class="tip-inline">已记录 {{ revisionRecord?.diff?.length || 0 }} 项变更{{ revisionSaving ? '，保存中' : revisionDirty ? '，自动保存中' : '，已保存' }}</span>
        </div>
        <div>
          <el-button v-if="revisionRecord?.diff?.length" link type="primary" @click="revisionDiffVisible = true">查看变更</el-button>
          <el-button size="small" type="primary" plain :loading="revisionSaving" :disabled="!revisionDirty" @click="saveRevisionDraft()">保存草稿</el-button>
        </div>
      </div>

      <el-steps :active="activeStep" finish-status="success" simple class="publish-steps">
        <el-step title="选择投放方式" />
        <el-step title="广告系列与广告组" />
        <el-step title="广告账户与投放" />
        <el-step title="预览提交" />
      </el-steps>
      <el-form label-width="110px" :model="form" class="publish-form">
        <section v-if="activeStep === 0" class="step-panel">
          <h3>选择投放方式</h3>
          <p class="step-desc">可以复用已有模板，也可以直接填写一份投放配置；两种方式最终使用同一套发布链路。</p>
          <el-form-item label="投放方式" required class="field-medium">
            <el-select v-model="form.publish_mode" class="content-width-select" style="width:240px" title="请选择投放方式" placeholder="请选择投放方式">
              <el-option label="使用投放模板" value="TEMPLATE" />
              <el-option label="直接配置投放" value="DIRECT" />
            </el-select>
          </el-form-item>
          <template v-if="form.publish_mode === 'TEMPLATE'">
          <el-form-item label="投放模板" required class="field-wide">
          <el-select
            v-model="form.template_id"
            filterable
            placeholder="选择投放模板"
            :style="{ width: templateSelectWidth }"
            :title="selectedTemplateLabel"
            :loading="loadingTemplates"
          >
            <el-option
              v-for="t in templates"
              :key="t.id"
              :label="templateLabel(t)"
              :value="t.id"
            />
            <template #empty>
              <div class="template-empty">
                <span>暂无可用投放模板</span>
                <el-button link type="primary" @click="goCreateTemplate">去创建模板</el-button>
              </div>
            </template>
          </el-select>
          <div class="tip">一次配置模板，即可批量部署到任意数量账户。</div>
          </el-form-item>
          <el-alert v-if="selectedTemplate" type="info" :closable="false" show-icon title="模板内容">
            {{ selectedTemplate.name }} · {{ selectedTemplate.objective || '未设置目标' }} ·
            {{ creativeCount(selectedTemplate) }} 个广告创意
          </el-alert>
          <el-alert v-if="selectedTemplate && !templateReady" type="warning" :closable="false" show-icon>
            该模板尚未选择 Facebook Page，请先到「投放模板」编辑并选择已同步页面。
          </el-alert>
          <el-alert v-if="assetBindings.length" type="info" :closable="false" show-icon title="素材映射">
            素材会在各广告账户的 Celery 子任务中独立上传，不共用 image hash / video ID。
          </el-alert>
          <el-table v-if="assetBindings.length" :data="assetBindings" size="small" style="margin-top:12px">
            <el-table-column prop="asset_id" label="素材" show-overflow-tooltip />
            <el-table-column prop="ad_account_id" label="广告账户" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="110" />
          </el-table>
          </template>
          <template v-else>
            <el-form-item label="广告系列名称" required><el-input v-model="directForm.name" placeholder="例如 US 流量测试" /></el-form-item>
            <el-form-item label="推广目标" required><el-select v-model="directForm.objective" style="width:100%"><el-option label="流量 OUTCOME_TRAFFIC" value="OUTCOME_TRAFFIC" /><el-option label="销售 OUTCOME_SALES" value="OUTCOME_SALES" /><el-option label="互动 OUTCOME_ENGAGEMENT" value="OUTCOME_ENGAGEMENT" /><el-option label="潜在客户 OUTCOME_LEADS" value="OUTCOME_LEADS" /></el-select></el-form-item>
            <el-form-item label="Facebook Page" required>
              <el-select v-model="directForm.page_id" filterable style="width:100%" placeholder="选择已同步的 Facebook Page">
                <el-option v-for="page in metaPages" :key="page.page_id" :label="`${page.page_name || page.page_id} (${page.page_id})`" :value="page.page_id" />
              </el-select>
              <div v-if="!metaPages.length" class="page-sync-inline">
                <span>暂无已同步页面。</span>
                <el-button size="small" :loading="pagesSyncing" @click="syncMetaPages">同步 Facebook 页面</el-button>
              </div>
            </el-form-item>
            <el-form-item label="默认日预算" required><el-input-number v-model="directForm.daily_budget" :min="1" :step="1" /><span class="tip-inline">美元/天</span></el-form-item>
            <el-form-item label="成效目标"><el-select v-model="directForm.optimization_goal" style="width:100%"><el-option v-for="goal in optimizationGoalOptions(directForm.objective)" :key="goal.value" :label="`${goal.label} ${goal.value}`" :value="goal.value" /></el-select></el-form-item>
            <el-alert v-if="!directObjectiveValid" type="warning" :closable="false" show-icon title="当前推广目标与成效目标不兼容，请切换成 Meta 支持的组合" />
            <el-form-item label="计费事件"><el-select v-model="directForm.billing_event" style="width:100%"><el-option label="展示 IMPRESSIONS" value="IMPRESSIONS" /><el-option label="链接点击 LINK_CLICKS" value="LINK_CLICKS" /></el-select></el-form-item>
            <el-form-item label="出价策略"><el-select v-model="directForm.bid_strategy" style="width:100%"><el-option label="最低成本（无上限）" value="LOWEST_COST_WITHOUT_CAP" /><el-option label="最低成本 + 竞价上限" value="LOWEST_COST_WITH_BID_CAP" /><el-option label="成本上限" value="COST_CAP" /></el-select></el-form-item>
            <el-form-item v-if="directForm.bid_strategy !== 'LOWEST_COST_WITHOUT_CAP'" label="出价金额"><el-input-number v-model="directForm.bid_amount" :min="1" :step="1" /><span class="tip-inline">Meta 账户货币最小单位</span></el-form-item>
            <div v-for="(adset, index) in directForm.adsets" :key="adset.key" class="direct-adset">
              <div class="direct-adset-head"><b>广告组 {{ index + 1 }}</b><el-button v-if="directForm.adsets.length > 1" link type="danger" @click="removeDirectAdset(index)">删除</el-button></div>
              <el-form-item label="广告组名称" required><el-input v-model="adset.name" placeholder="例如 US 广告组" /></el-form-item>
              <el-form-item label="预算" required><el-input-number v-model="adset.budget" :min="1" :step="1" /><span class="tip-inline">美元/天</span></el-form-item>
              <el-form-item label="国家/地区" required><el-input v-model="adset.country" placeholder="例如 US；多个国家用逗号分隔" /></el-form-item>
              <el-form-item label="年龄范围"><el-input-number v-model="adset.age_min" :min="13" :max="65" /> <span>至</span> <el-input-number v-model="adset.age_max" :min="13" :max="65" /></el-form-item>
              <el-form-item label="性别"><el-checkbox-group v-model="adset.genders"><el-checkbox :label="1">男性</el-checkbox><el-checkbox :label="2">女性</el-checkbox></el-checkbox-group></el-form-item>
              <el-form-item label="兴趣"><el-input v-model="adset.interests" placeholder="多个兴趣用逗号分隔（可选）" /></el-form-item>
              <el-form-item label="语言"><MetaLanguageSelect v-model="adset.languages" /></el-form-item>
              <el-form-item label="版位"><el-select v-model="adset.publisher_platforms" multiple style="width:100%"><el-option label="Facebook" value="facebook" /><el-option label="Instagram" value="instagram" /><el-option label="Audience Network" value="audience_network" /><el-option label="Messenger" value="messenger" /></el-select></el-form-item>
              <el-form-item label="成效目标"><el-select v-model="adset.optimization_goal" style="width:100%"><el-option v-for="goal in optimizationGoalOptions(directForm.objective)" :key="goal.value" :label="`${goal.label} ${goal.value}`" :value="goal.value" /></el-select></el-form-item>
              <el-form-item label="计费事件"><el-select v-model="adset.billing_event" style="width:100%"><el-option label="展示 IMPRESSIONS" value="IMPRESSIONS" /><el-option label="链接点击 LINK_CLICKS" value="LINK_CLICKS" /></el-select></el-form-item>
              <el-form-item label="出价策略"><el-select v-model="adset.bid_strategy" style="width:100%"><el-option label="最低成本（无上限）" value="LOWEST_COST_WITHOUT_CAP" /><el-option label="最低成本 + 竞价上限" value="LOWEST_COST_WITH_BID_CAP" /><el-option label="成本上限" value="COST_CAP" /></el-select></el-form-item>
              <el-form-item v-if="adset.bid_strategy !== 'LOWEST_COST_WITHOUT_CAP'" label="出价金额"><el-input-number v-model="adset.bid_amount" :min="1" :step="1" /></el-form-item>
            </div>
            <el-button plain type="primary" @click="addDirectAdset">+ 添加广告组</el-button>
            <el-divider content-position="left">广告创意</el-divider>
            <el-form-item label="素材形式">
              <el-radio-group :model-value="creativeFormat" @change="handleCreativeFormatChange">
                <el-radio value="SINGLE_IMAGE_VIDEO">单图片或视频</el-radio>
                <el-radio value="CAROUSEL">轮播</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="拆分方式">
              <el-radio-group v-model="delivery.split_level">
                <el-radio value="AD">每个素材生成一个广告</el-radio>
                <el-radio value="ADSET" :disabled="creativeFormat === 'CAROUSEL'">按广告组拆分</el-radio>
                <el-radio value="CAMPAIGN" disabled>按广告系列拆分（后续开放）</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-alert type="info" :closable="false" show-icon :title="creativeFormat === 'CAROUSEL' ? '轮播广告' : '单图片或视频广告'">
              {{ creativeFormat === 'CAROUSEL' ? '2-10 张图片组成 1 个轮播广告；所有图片同步完成后才允许发布。' : delivery.split_level === 'AD' ? `每个广告使用一张图片或一个视频；可一次选择多份素材批量生成广告，共 ${directForm.creatives.length} 个。` : '按广告组拆分时一次选择一份素材；每份素材会单独生成一个广告组。' }}
            </el-alert>
            <el-form-item label="批量选素材">
              <el-select
                v-model="batchAssetSelection"
                :multiple="batchAssetMultiple"
                filterable
                :collapse-tags="batchAssetMultiple"
                :placeholder="batchAssetPlaceholder"
                style="width:100%"
              >
                <el-option v-for="asset in batchAssetOptions" :key="asset.id" :label="`${asset.name} · ${asset.asset_type} · ${asset.status}`" :value="asset.id" />
              </el-select>
              <el-button plain type="primary" style="margin-top:8px" :disabled="!batchAssetIds.length" @click="addBatchCreatives">{{ batchAssetActionLabel }}</el-button>
              <div class="tip">{{ creativeFormat === 'CAROUSEL' ? `已选择 ${directForm.creatives.filter(item => item.asset_id).length} 张图片，将生成 1 个轮播广告（2-10 张）` : `批量选择素材后，将按拆分方式生成 ${directForm.creatives.filter(item => item.asset_id).length} 个独立广告` }}</div>
            </el-form-item>
            <el-form-item label="文案模式">
              <el-radio-group v-model="creativeCopyMode">
                <el-radio value="SHARED">统一文案</el-radio>
                <el-radio value="INDIVIDUAL">每个素材独立文案</el-radio>
              </el-radio-group>
            </el-form-item>
            <div class="tip">公共配置会应用到全部素材；单个创意中的覆盖值为空时自动使用公共配置。</div>
            <el-form-item label="公共主文案"><el-input v-model="sharedCreative.primary_text" type="textarea" :rows="3" placeholder="可不填" /></el-form-item>
            <el-form-item label="默认落地页"><el-input v-model="sharedCreative.landing_url" placeholder="https://example.com/landing（图片广告最终必须有有效链接）" /></el-form-item>
            <el-form-item label="公共标题"><el-input v-model="sharedCreative.headline" /></el-form-item>
            <el-form-item label="公共描述"><el-input v-model="sharedCreative.description" /></el-form-item>
            <el-form-item label="公共行动号召"><el-select v-model="sharedCreative.cta" style="width:100%"><el-option v-for="cta in CTA_OPTIONS" :key="cta.value" :label="`${cta.label} ${cta.value}`" :value="cta.value" /></el-select></el-form-item>
            <div v-for="(creative, index) in directForm.creatives" :key="creative.key" class="direct-creative">
              <div class="direct-adset-head"><b>{{ creativeFormat === 'CAROUSEL' ? `轮播卡片 ${index + 1}` : `创意 ${index + 1}` }}</b><el-button v-if="directForm.creatives.length > 1" link type="danger" @click="removeDirectCreative(index)">删除</el-button></div>
              <el-form-item label="素材" required><el-select v-model="creative.asset_id" filterable style="width:100%" :placeholder="creativeFormat === 'CAROUSEL' ? '选择已同步图片' : '选择已上传素材'"><el-option v-for="asset in creativeAssetOptions" :key="asset.id" :label="`${asset.name} · ${asset.asset_type} · ${asset.status}`" :value="asset.id" /></el-select></el-form-item>
              <template v-if="creativeCopyMode === 'INDIVIDUAL'">
                <el-form-item label="主文案覆盖"><el-input v-model="creative.primary_text" type="textarea" :rows="3" placeholder="可留空，使用公共主文案" /></el-form-item>
                <el-form-item label="标题覆盖"><el-input v-model="creative.headline" placeholder="可留空，使用公共标题" /></el-form-item>
                <el-form-item label="描述覆盖"><el-input v-model="creative.description" placeholder="可留空，使用公共描述" /></el-form-item>
                <el-form-item label="行动号召覆盖"><el-select v-model="creative.cta" clearable style="width:100%"><el-option v-for="cta in CTA_OPTIONS" :key="cta.value" :label="`${cta.label} ${cta.value}`" :value="cta.value" /></el-select></el-form-item>
                <el-form-item label="落地页覆盖"><el-input v-model="creative.landing_url" placeholder="可留空，使用公共默认落地页" /></el-form-item>
              </template>
            </div>
            <el-button plain type="primary" @click="addDirectCreative">{{ creativeFormat === 'CAROUSEL' ? '+ 添加轮播卡片' : '+ 添加创意' }}</el-button>
            <div class="tip">素材必须先在素材库上传；提交后系统会按目标广告账户分别同步素材。</div>
            <el-checkbox v-model="form.save_as_template">保存为投放模板</el-checkbox>
            <el-form-item v-if="form.save_as_template" label="模板名称" required>
              <el-input v-model="form.template_name" placeholder="请输入模板名称" />
            </el-form-item>
          </template>
        </section>
        <section v-else-if="activeStep === 1" class="step-panel">
          <h3>广告系列与广告组</h3>
          <p class="step-desc">以下配置将为每个目标广告账户创建独立的 Campaign、AdSet 和 Ad。</p>
          <el-descriptions v-if="selectedTemplate" :column="2" border>
            <el-descriptions-item label="广告系列目标">{{ selectedTemplate.objective || '-' }}</el-descriptions-item>
            <el-descriptions-item label="购买类型">{{ selectedTemplate.buying_type || 'AUCTION' }}</el-descriptions-item>
            <el-descriptions-item label="成效目标">{{ optimizationGoalLabel(selectedTemplate.optimization_goal) }}</el-descriptions-item>
            <el-descriptions-item label="计费事件">{{ selectedTemplate.billing_event || '-' }}</el-descriptions-item>
            <el-descriptions-item label="默认预算">{{ templateBudget }}</el-descriptions-item>
            <el-descriptions-item label="广告创意">{{ creativeCount(selectedTemplate) }} 个</el-descriptions-item>
          </el-descriptions>
          <el-alert v-if="form.publish_mode === 'DIRECT'" type="info" :closable="false" show-icon title="直接配置">
            配置将在提交前转换为内部投放配置；素材仍会按广告账户分别同步。
          </el-alert>
          <el-alert v-if="form.publish_mode === 'TEMPLATE'" type="warning" :closable="false" show-icon title="模板配置">
            如需修改 Campaign / AdSet / Ad 配置，请先在投放模板中编辑。本次投放可覆盖预算和状态，不会修改模板原始内容。
          </el-alert>
          <el-alert v-if="form.sinan_promotion_id" type="success" :closable="false" show-icon title="已关联司南推广链">{{ form.sinan_promotion_id }}</el-alert>
        </section>
        <section v-else-if="activeStep === 2" class="step-panel">
          <h3>广告账户与本次投放参数</h3>
        <!-- 账户多选 -->
        <el-form-item label="广告账户" required>
          <el-select
            v-model="form.ad_account_ids"
            multiple
            filterable
            placeholder="选择目标账户"
            style="width: 100%"
            :loading="loadingAccounts"
          >
            <el-option
              v-for="a in accounts"
              :key="a.id"
              :label="`${a.account_name || a.account_id} (${a.account_id})`"
              :value="a.id"
            />
          </el-select>
        </el-form-item>

        <div v-if="trackingAssetRequired" class="tracking-asset-panel">
          <div class="tracking-asset-panel__title">转化资产</div>
          <div class="tracking-asset-panel__desc">
            {{ form.publish_mode === 'DIRECT' ? 'Pixel / 数据集会按已选广告账户自动筛选；多账户仅展示共同可用资产。' : '当前模板使用转化优化，请确认模板中已配置可用 Pixel / 数据集。' }}
          </div>
          <el-form-item v-if="form.publish_mode === 'DIRECT'" label="Pixel / 数据集" :required="trackingAssetRequired">
            <el-select
              v-model="directForm.dataset_id"
              filterable
              clearable
              style="width: 100%"
              placeholder="先选择广告账户，再选择共同可用的 Pixel / 数据集"
              :loading="trackingAssetsLoading"
              :disabled="!form.ad_account_ids.length"
            >
              <el-option
                v-for="asset in trackingAssets"
                :key="`${asset.asset_type}-${asset.id}`"
                :value="asset.id"
              >
                <div class="tracking-asset-option">
                  <div class="tracking-asset-option__name">
                    {{ asset.name }} · {{ asset.asset_type === 'PIXEL' ? 'Pixel' : 'Dataset' }} · {{ asset.id }}
                  </div>
                  <div class="tracking-asset-option__meta">
                    <el-tag size="small" :type="trackingAssetStatusType(asset)">{{ trackingAssetStatusLabel(asset) }}</el-tag>
                    <span>最近同步：{{ formatTrackingAssetTime(asset.last_synced_at) }}</span>
                  </div>
                </div>
              </el-option>
              <template #empty>
                <div class="tracking-asset-empty">暂无共同可用的 Pixel / 数据集，请检查授权范围或先同步广告账户。</div>
              </template>
            </el-select>
          </el-form-item>
            <el-form-item v-if="form.publish_mode === 'DIRECT'" label="转化事件" :required="trackingAssetRequired">
              <el-select v-model="directForm.conversion_event" filterable allow-create default-first-option style="width: 100%" placeholder="选择 Meta 转化事件">
                <el-option v-for="event in STANDARD_CONVERSION_EVENTS" :key="event.value" :label="`${event.label} ${event.value}`" :value="event.value" />
              </el-select>
              <div class="tip">支持标准事件或自定义事件；自定义事件需以字母开头，仅允许字母、数字和下划线。</div>
            </el-form-item>
          <div v-else class="tracking-asset-template-state">
            <el-tag v-if="selectedTemplateTrackingAssetId" type="success">已配置：{{ selectedTemplateTrackingAssetId }}</el-tag>
            <el-tag v-else type="warning">模板未配置 Pixel / 数据集，请先编辑模板</el-tag>
          </div>
          <el-alert
            v-if="!trackingConfigReady"
            type="warning"
            :closable="false"
            show-icon
            title="该优化目标需要事件源"
          >
            当前仅在发布预检阶段拦截；请选择 Pixel / 数据集并配置转化事件后再继续。
          </el-alert>
          <div v-if="trackingAssetsError" class="tracking-asset-error">{{ trackingAssetsError }}</div>
        </div>

        <el-form-item label="广告组来源" required>
          <el-radio-group v-model="adGroupMode">
            <el-radio value="NEW">新建广告组</el-radio>
            <el-radio value="EXISTING">同账户复用已同步广告组</el-radio>
            <el-radio value="COPY">跨账户复制广告组配置</el-radio>
          </el-radio-group>
          <div class="tip">同账户复用会沿用广告组及父广告系列；跨账户复制只复制定向、预算和出价，目标账户会新建投放对象。</div>
        </el-form-item>
        <el-alert v-if="adGroupMode !== 'NEW' && currentAdsetCount > 1" type="warning" :closable="false" show-icon>
          当前配置包含 {{ currentAdsetCount }} 个广告组；复用或复制模式每个账户只能选择一个已同步广告组，请调整为一个广告组后继续。
        </el-alert>
        <div v-if="adGroupMode !== 'NEW' && selectedAccountRows.length" class="existing-adgroup-list">
          <div v-for="account in selectedAccountRows" :key="account.id" class="existing-adgroup-row">
            <div class="account-label">{{ account.account_name || account.account_id }}</div>
            <el-select
              v-model="existingAdGroupSelections[account.id]"
              filterable
              remote
              clearable
              :remote-method="(query) => loadExistingAdGroups(account.id, query)"
              :loading="existingAdGroupLoading[account.id]"
              :placeholder="adGroupMode === 'COPY' ? '搜索源广告组 / 广告系列（可跨账户）' : '搜索已同步广告组 / 广告系列'"
              style="width: 440px"
              @focus="loadExistingAdGroups(account.id)"
              @clear="delete existingAdGroupSelections[account.id]"
            >
              <el-option
                v-for="group in (existingAdGroups[account.id] || [])"
                :key="group.id"
                :label="`${group.name} · ${group.campaign.name} · ${group.account_name || group.ad_account_id}`"
                :value="group.id"
              >
                <span>{{ group.name }} · {{ group.campaign.name }} · {{ group.account_name || group.ad_account_id }}</span>
                <small class="adgroup-option-meta">{{ group.ad_group_id }} · {{ group.status }}</small>
                <el-tag v-if="group.stale" size="small" type="warning">同步超过 24 小时</el-tag>
              </el-option>
            </el-select>
            <div v-if="selectedExistingAdGroup(account.id)" class="selected-adgroup-detail">
              Meta AdSet {{ selectedExistingAdGroup(account.id)?.ad_group_id }} · 父系列 {{ selectedExistingAdGroup(account.id)?.campaign.campaign_id }}
              <span v-if="selectedExistingAdGroup(account.id)?.stale" class="stale-adgroup-tip">
                源数据超过 24 小时未同步，请先同步 Meta
                <el-button
                  size="small"
                  type="warning"
                  :loading="existingAdGroupSyncing[account.id]"
                  @click="syncExistingAdGroup(account.id)"
                >
                  {{ existingAdGroupSyncing[account.id] ? '同步中' : '立即同步' }}
                </el-button>
              </span>
              <span v-if="existingAdGroupSyncState[account.id]" class="adgroup-sync-state">
                {{ adGroupSyncStateLabel(existingAdGroupSyncState[account.id]) }}
              </span>
              <span v-if="existingAdGroupSyncError[account.id]" class="adgroup-sync-error">
                {{ existingAdGroupSyncError[account.id] }}
              </span>
            </div>
          </div>
        </div>

        <el-form-item label="预算覆盖">
          <el-input-number v-model="form.budget_override" :min="0" :step="10" />
          <span class="tip-inline">为 0 或留空时沿用模板预算（美元/天）</span>
        </el-form-item>

        <el-form-item label="投放状态">
          <el-radio-group v-model="form.status">
            <el-radio value="PAUSED">暂停（推荐）</el-radio>
            <el-radio value="ACTIVE">立即启用</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon>
          账单状态仅作信息展示，不参与投放账户筛选；系统将校验账户状态、Meta 状态、授权凭据和 Facebook Page 权限，最终结果以 Meta 响应为准。
        </el-alert>
        <el-table v-if="selectedAccountRows.length" :data="selectedAccountRows" size="small" style="margin-bottom: 12px">
          <el-table-column prop="account_name" label="账户" show-overflow-tooltip />
          <el-table-column prop="account_id" label="Account ID" show-overflow-tooltip />
          <el-table-column label="账单状态（仅展示）" width="160">
            <template #default="{ row }">
              <el-tag :type="row.payment_status === 'AVAILABLE' ? 'success' : 'info'" size="small">
                {{ row.payment_status || 'UNKNOWN' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="payment_source" label="支付来源" width="140" />
        </el-table>

        <el-form-item v-if="selectedAccountRows.length" label="发布 BM">
          <div class="access-business-list">
            <div v-for="account in selectedAccountRows" :key="account.id" class="access-business-row">
              <span class="account-label">{{ account.account_name || account.account_id }}</span>
              <el-select v-model="accessBusinessIds[account.id]" filterable style="width: 260px" placeholder="选择访问 BM">
                <el-option
                  v-for="business in account.accessible_businesses || []"
                  :key="business.business_id"
                  :label="`${business.business_name || business.meta_business_id || business.business_id} · ${business.access_level}`"
                  :value="business.business_id"
                />
              </el-select>
            </div>
          </div>
          <span class="tip-inline">不选择时使用广告账户原始归属 BM；共享账户发布时请明确选择有权限的 BM。</span>
        </el-form-item>
        <el-alert v-if="!loadingAccounts && !accounts.length" type="warning" :closable="false" show-icon>
          当前没有可投放广告账户，请先完成 Meta OAuth 授权或恢复有效凭据。
        </el-alert>
        <el-alert type="info" :closable="false" show-icon title="地区与人群">
          当前版本沿用模板中的定向配置；地区、人群覆盖字段已预留，下一阶段接入 Meta 定向编辑器。
        </el-alert>
        </section>
        <section v-else class="step-panel">
          <h3>预览并提交</h3>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="投放方式">{{ form.publish_mode === 'DIRECT' ? '直接配置' : '使用模板' }}</el-descriptions-item>
            <el-descriptions-item label="投放模板">{{ selectedTemplate?.name || form.template_name || '直接配置' }}</el-descriptions-item>
            <el-descriptions-item label="目标账户">{{ form.ad_account_ids.length }} 个</el-descriptions-item>
            <el-descriptions-item label="部署结构">每个账户 1 个 Campaign → {{ form.publish_mode === 'DIRECT' ? previewAdsetCount : adsetCount(selectedTemplate) }} 个 AdSet → {{ form.publish_mode === 'DIRECT' ? previewAdCount : creativeCount(selectedTemplate) * adsetCount(selectedTemplate) }} 个 Ad</el-descriptions-item>
            <el-descriptions-item label="预算">{{ form.budget_override ? form.budget_override + ' 美元/天（本次覆盖）' : form.publish_mode === 'DIRECT' ? directForm.adsets.reduce((sum, item) => sum + Number(item.budget || 0), 0) + ' 美元/天' : templateBudget + '（沿用模板）' }}</el-descriptions-item>
            <el-descriptions-item v-if="form.publish_mode === 'TEMPLATE' && selectedTemplate?.budget_type === 'LIFETIME'" label="开始时间">{{ formatScheduleTime(templateSchedule.start_time) }}</el-descriptions-item>
            <el-descriptions-item v-if="form.publish_mode === 'TEMPLATE' && selectedTemplate?.budget_type === 'LIFETIME'" label="结束时间">{{ formatScheduleTime(templateSchedule.end_time) }}</el-descriptions-item>
            <el-descriptions-item label="初始状态">{{ form.status === 'ACTIVE' ? '立即启用' : '暂停' }}</el-descriptions-item>
            <el-descriptions-item label="广告组来源">{{ adGroupMode === 'EXISTING' ? `同账户复用（${form.ad_account_ids.length} 个账户分别选择）` : adGroupMode === 'COPY' ? `跨账户复制（${form.ad_account_ids.length} 个账户分别选择）` : '新建广告组' }}</el-descriptions-item>
          </el-descriptions>
          <el-table :data="selectedAccountRows" size="small" style="margin-top: 12px">
            <el-table-column prop="account_name" label="账户" show-overflow-tooltip />
            <el-table-column prop="account_id" label="Account ID" show-overflow-tooltip />
            <el-table-column prop="payment_status" label="账单状态（仅展示）" width="160" />
            <el-table-column prop="business.name" label="归属 BM" show-overflow-tooltip />
            <el-table-column v-if="preflightBlockedAccounts.length" label="预检结果" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="preflightReasonByAccount[row.id] || preflightReasonByAccount[row.account_id]" class="preflight-blocked">
                  {{ preflightReasonByAccount[row.id] || preflightReasonByAccount[row.account_id] }}
                </span>
                <span v-else class="preflight-ready">可投放</span>
              </template>
            </el-table-column>
          </el-table>
          <el-table v-if="form.publish_mode === 'DIRECT'" :data="directForm.adsets" size="small" style="margin-top: 12px" border>
            <el-table-column type="index" label="#" width="55" />
            <el-table-column prop="name" label="广告组" min-width="150" />
            <el-table-column prop="budget" label="预算（美元/天）" width="130" />
            <el-table-column prop="country" label="国家/地区" width="120" />
            <el-table-column label="年龄" width="100"><template #default="{ row }">{{ row.age_min }}-{{ row.age_max }}</template></el-table-column>
            <el-table-column label="性别" width="100"><template #default="{ row }">{{ row.genders?.length === 2 ? '男女' : row.genders?.includes(1) ? '男性' : row.genders?.includes(2) ? '女性' : '未设置' }}</template></el-table-column>
            <el-table-column prop="interests" label="兴趣" min-width="150" show-overflow-tooltip />
            <el-table-column label="版位" min-width="150"><template #default="{ row }">{{ row.publisher_platforms.join(', ') || '自动版位' }}</template></el-table-column>
          <el-table-column label="成效目标" width="150"><template #default="{ row }">{{ optimizationGoalLabel(row.optimization_goal) }}</template></el-table-column>
          </el-table>
          <el-alert v-if="form.publish_mode === 'DIRECT'" type="info" :closable="false" show-icon style="margin-top:12px">
            本次将生成 {{ previewAdsetCount }} 个 AdSet、{{ previewAdCount }} 个 Ad（按账户计算）。
          </el-alert>
          <el-alert type="warning" :closable="false" show-icon title="提交后将创建异步投放任务">
            系统会逐账户执行，失败账户不会影响已成功账户，可在任务中心重试失败项。
          </el-alert>
          <el-alert v-if="preflightResult" :type="preflightResult.passed ? 'success' : 'error'" :closable="false" show-icon style="margin-top:12px">
            <template #title>{{ preflightResult.passed ? `预检通过：${preflightResult.ready_account_ids.length} 个账户可投放` : '预检未通过，暂不能提交' }}</template>
            <div v-if="preflightResult.passed && preflightResult.expires_at" class="preflight-detail">本次预览仅对当前账户、素材和配置有效，提交前会再次校验；有效期至 {{ preflightResult.expires_at }}</div>
            <div v-for="item in preflightResult.errors" :key="`error-${item.code}`" class="preflight-error-item">
              <div>{{ item.message }}</div>
              <div v-if="preflightActionHint(item.code)" class="preflight-detail">处理建议：{{ preflightActionHint(item.code) }}</div>
              <div v-for="blocked in (item.items || [])" :key="`${item.code}-${blocked.account_id}-${blocked.asset_id || blocked.reason}`" class="preflight-detail">
                账户 {{ blocked.account_id }}：{{ blocked.reason }}{{ blocked.asset_id ? `（事件源 ${blocked.asset_id}）` : '' }}
              </div>
            </div>
            <div v-for="item in preflightResult.warnings" :key="`warning-${item.code}`" class="preflight-warning">
              <div>{{ item.message }}</div>
              <div v-if="preflightActionHint(item.code)" class="preflight-detail">处理建议：{{ preflightActionHint(item.code) }}</div>
              <div v-for="blocked in (item.items || [])" :key="`${item.code}-${blocked.account_id}-${blocked.reason}`" class="preflight-detail">
                账户 {{ blocked.account_id }}：{{ blocked.reason }}{{ blocked.asset_id ? `（事件源 ${blocked.asset_id}）` : '' }}
              </div>
            </div>
            <el-button v-if="missingAssetAccounts.length" type="primary" size="small" style="margin-top:8px" :loading="syncingAssets" @click="syncMissingAssets">
              立即同步缺失素材
            </el-button>
            <el-button v-if="trackingAssetIssues.length" type="warning" size="small" style="margin-top:8px" :loading="syncingTrackingAssets" @click="refreshTrackingAssetsAndPreflight">
              重新同步事件源并预检
            </el-button>
          </el-alert>
        </section>
        <div class="step-actions">
          <el-button v-if="activeStep > 0" @click="activeStep--">{{ t('pages.previous') }}</el-button>
          <el-button v-if="activeStep < 3" type="primary" :loading="preflighting" :disabled="!canNext" @click="nextStep">{{ t('pages.next') }}</el-button>
          <el-button v-else type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">{{ t('pages.submit') }}</el-button>
        </div>
      </el-form>

      <!-- 当前任务进度 -->
      <template v-if="currentJob">
        <el-divider>任务进度</el-divider>
        <p class="job-line">
          任务 <b>{{ currentJob.id }}</b> ·
          <el-tag size="small" type="info" style="margin-right:6px">{{ currentJob.params?.source === 'DIRECT' ? '直接配置' : '模板投放' }}</el-tag>
          <span v-if="currentJob.template_id" class="job-meta">模板 {{ currentJob.template_id }}</span>
          <el-tag :type="statusTagType(currentJob.status)" size="small">
            {{ currentJob.status }}
          </el-tag>
        </p>
        <el-progress :percentage="progressPercent" :status="progressStatus" />
        <p class="job-line">
          总计 <b>{{ currentJob.total_accounts }}</b> ·
          成功 <b style="color:#67c23a">{{ currentJob.success_count }}</b> ·
          失败 <b style="color:#f56c6c">{{ currentJob.failed_count }}</b>
        </p>

        <el-table :data="currentJob.items || []" size="small" max-height="300">
          <el-table-column prop="ad_account_id" label="账户" show-overflow-tooltip />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
            <el-tag :type="itemTagType(row.status)" size="small">{{ row.status }}</el-tag>
            <el-tag v-if="row.response_payload?.cleanup_failed" type="danger" size="small" style="margin-left:4px">待人工清理</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="meta_campaign_id" label="Meta Campaign" width="160" show-overflow-tooltip />
          <el-table-column prop="retry_count" label="重试" width="70" />
          <el-table-column label="错误" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.error_category" class="err-cat">[{{ row.error_category }}]</span>
              {{ row.error_message }}
            </template>
          </el-table-column>
          <el-table-column label="待清理 Meta 对象" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.response_payload?.cleanup_object_ids?.join(', ') || '-' }}
            </template>
          </el-table-column>
        </el-table>

        <div v-if="currentJob.failed_count > 0" style="margin-top: 12px">
          <el-button type="warning" size="small" @click="retryFailed">
            重跑失败账户（{{ currentJob.failed_count }}）
          </el-button>
          <span class="tip-inline">仅重跑失败项，不影响已成功的账户</span>
        </div>
      </template>

      <!-- 历史任务 -->
      <el-divider>历史任务</el-divider>
      <el-table :data="jobs" size="small" v-loading="loadingJobs">
        <el-table-column prop="id" label="Job ID" width="240" show-overflow-tooltip />
        <el-table-column prop="action_type" label="动作" width="120" />
        <el-table-column label="状态" width="150">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_accounts" label="总数" width="80" />
        <el-table-column prop="success_count" label="成功" width="80" />
        <el-table-column prop="failed_count" label="失败" width="80" />
        <el-table-column prop="created_at" label="创建时间" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewJob(row.id)">查看</el-button>
            <el-button
              link
              type="danger"
              :disabled="isFinalStatus(row.status)"
              @click="cancelJob(row.id)"
            >
              取消
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="revisionDiffVisible" title="修订变更" width="760px">
      <el-table :data="revisionRecord?.diff || []" size="small" border max-height="420">
        <el-table-column prop="path" label="配置项" width="220" show-overflow-tooltip />
        <el-table-column label="原值" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ formatRevisionValue(row.before) }}</template>
        </el-table-column>
        <el-table-column label="修改后" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ formatRevisionValue(row.after) }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi, type DeployableAccount } from '@/api/admin'
import { templatesApi, type CampaignTemplate } from '@/api/templates'
import { mediaApi, type MetaAssetBinding } from '@/api/media'
import { metaPagesApi, type MetaPage } from '@/api/metaPages'
import { metaTrackingAssetsApi, type MetaTrackingAsset } from '@/api/metaTrackingAssets'
import MetaLanguageSelect from '@/components/MetaLanguageSelect.vue'
import { campaignsApi, type SyncedAdGroup } from '@/api/campaigns'
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
import {
  jobsApi,
  isFinalStatus,
  type CampaignJob,
  type CampaignJobRevision,
  type JobEditSource,
} from '@/api/jobs'

const router = useRouter()
const route = useRoute()
const templates = ref<CampaignTemplate[]>([])
const accounts = ref<DeployableAccount[]>([])
const jobs = ref<CampaignJob[]>([])
const currentJob = ref<CampaignJob | null>(null)
const editSource = ref<JobEditSource | null>(null)
const editRevisionId = ref<string | null>(null)
const revisionRecord = ref<CampaignJobRevision | null>(null)
const revisionSaving = ref(false)
const revisionDirty = ref(false)
const revisionDiffVisible = ref(false)
let restoringRevision = false

const loadingTemplates = ref(false)
const loadingAccounts = ref(false)
const loadingJobs = ref(false)
const submitting = ref(false)
const syncingAssets = ref(false)
const syncingTrackingAssets = ref(false)
const preflighting = ref(false)
const preflightResult = ref<any>(null)
const rateLimitStatus = ref<{ count: number; limit: number; usage_ratio: number } | null>(null)
const assetBindings = ref<MetaAssetBinding[]>([])
const metaPages = ref<MetaPage[]>([])
const pagesSyncing = ref(false)
const trackingAssets = ref<MetaTrackingAsset[]>([])
const trackingAssetsLoading = ref(false)
const trackingAssetsError = ref('')
const mediaAssets = ref<any[]>([])
const activeStep = ref(0)
const adGroupMode = ref<'NEW' | 'EXISTING' | 'COPY'>('NEW')
const existingAdGroups = reactive<Record<string, SyncedAdGroup[]>>({})
const existingAdGroupLoading = reactive<Record<string, boolean>>({})
const existingAdGroupSelections = reactive<Record<string, string>>({})
const existingAdGroupSyncing = reactive<Record<string, boolean>>({})
const existingAdGroupSyncState = reactive<Record<string, string>>({})
const existingAdGroupSyncError = reactive<Record<string, string>>({})

let pollTimer: number | null = null
let assetPollTimer: number | null = null
let revisionSaveTimer: number | null = null
let revisionSavePromise: Promise<void> | null = null
let trackingAssetsRequest = 0

const form = reactive({
  publish_mode: 'TEMPLATE' as 'TEMPLATE' | 'DIRECT',
  template_id: '',
  template_name: '',
  save_as_template: false,
  ad_account_ids: [] as string[],
  budget_override: 0,
  status: 'PAUSED',
  sinan_promotion_id: String(route.query.sinan_promotion_id || ''),
})

const directForm = reactive({
  name: '直接投放测试', objective: 'OUTCOME_TRAFFIC', page_id: '', daily_budget: 10,
  optimization_goal: 'LANDING_PAGE_VIEWS', billing_event: 'IMPRESSIONS', bid_strategy: 'LOWEST_COST_WITHOUT_CAP', bid_amount: 1,
  dataset_id: '', conversion_event: 'PURCHASE',
  creative_format: 'SINGLE_IMAGE_VIDEO' as 'SINGLE_IMAGE_VIDEO' | 'CAROUSEL',
  adsets: [{ key: `${Date.now()}-1`, name: 'US 广告组', budget: 10, country: 'US', age_min: 18, age_max: 65, genders: [1, 2] as number[], interests: '', languages: [] as string[], publisher_platforms: ['facebook'] as string[], optimization_goal: 'LANDING_PAGE_VIEWS', billing_event: 'IMPRESSIONS', bid_strategy: 'LOWEST_COST_WITHOUT_CAP', bid_amount: 1 }],
  creatives: [{ key: `${Date.now()}-creative-1`, asset_id: '', primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', landing_url: '' }],
})
const batchAssetIds = ref<string[]>([])
const creativeCopyMode = ref<'SHARED' | 'INDIVIDUAL'>('SHARED')
const creativeFormat = ref<'SINGLE_IMAGE_VIDEO' | 'CAROUSEL'>('SINGLE_IMAGE_VIDEO')
const delivery = reactive({ split_level: 'AD' as 'AD' | 'ADSET' | 'CAMPAIGN', combination_mode: 'ACCOUNT_X_ADSET_X_CREATIVE' })
const readyImageAssets = computed(() => mediaAssets.value.filter(asset =>
  String(asset.asset_type || '').toLowerCase() === 'image' && String(asset.status || '').toUpperCase() === 'READY',
))
const creativeAssetOptions = computed(() => creativeFormat.value === 'CAROUSEL' ? readyImageAssets.value : mediaAssets.value)
const batchAssetOptions = creativeAssetOptions
// 按广告拆分时，单图/视频允许一次选择多份素材批量生成广告；
// 按广告组拆分时，一次只选择一份素材，避免选择器和拆分语义不一致。
// 轮播本身必须由多张图片组成，并且后端只支持按 AD 拆分。
const batchAssetMultiple = computed(() => creativeFormat.value === 'CAROUSEL' || delivery.split_level === 'AD')
const batchAssetSelection = computed<string | string[]>({
  get: () => batchAssetMultiple.value ? batchAssetIds.value : (batchAssetIds.value[0] || ''),
  set: value => {
    const ids = Array.isArray(value) ? value : (value ? [value] : [])
    batchAssetIds.value = batchAssetMultiple.value ? ids : ids.slice(0, 1)
  },
})
const batchAssetPlaceholder = computed(() => batchAssetMultiple.value ? '选择多份素材后批量加入' : '选择一份素材后加入')
const batchAssetActionLabel = computed(() => creativeFormat.value === 'CAROUSEL'
  ? '加入轮播卡片'
  : delivery.split_level === 'AD' ? '加入独立广告' : '加入广告组拆分')
const previewAdsetCount = computed(() => delivery.split_level === 'ADSET' && creativeFormat.value !== 'CAROUSEL'
  ? directForm.adsets.length * directForm.creatives.length
  : directForm.adsets.length)
const previewAdCount = computed(() => directForm.adsets.length * (creativeFormat.value === 'CAROUSEL' ? 1 : directForm.creatives.length))
const directObjectiveValid = computed(() => isOptimizationGoalAllowed(directForm.objective, directForm.optimization_goal)
  && directForm.adsets.every(item => isOptimizationGoalAllowed(directForm.objective, item.optimization_goal)))
const sharedCreative = reactive({ primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', landing_url: '' })

const addDirectAdset = () => {
  directForm.adsets.push({ key: `${Date.now()}-${directForm.adsets.length + 1}`, name: `广告组 ${directForm.adsets.length + 1}`, budget: directForm.daily_budget, country: 'US', age_min: 18, age_max: 65, genders: [1, 2], interests: '', languages: [], publisher_platforms: ['facebook'], optimization_goal: directForm.optimization_goal, billing_event: directForm.billing_event, bid_strategy: directForm.bid_strategy, bid_amount: 1 })
}
const removeDirectAdset = (index: number) => { if (directForm.adsets.length > 1) directForm.adsets.splice(index, 1) }
const addDirectCreative = () => directForm.creatives.push({ key: `${Date.now()}-${directForm.creatives.length + 1}`, asset_id: '', primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', landing_url: '' })
const removeDirectCreative = (index: number) => { if (directForm.creatives.length > 1) directForm.creatives.splice(index, 1) }
const resetCreativeItems = () => {
  directForm.creatives.splice(0, directForm.creatives.length, {
    key: `${Date.now()}-creative-1`, asset_id: '', primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', landing_url: '',
  })
  batchAssetIds.value = []
}
const handleCreativeFormatChange = async (value: 'SINGLE_IMAGE_VIDEO' | 'CAROUSEL') => {
  if (value === creativeFormat.value) return
  const hasSelectedAssets = directForm.creatives.some(item => !!item.asset_id) || batchAssetIds.value.length > 0
  if (hasSelectedAssets) {
    try {
      await ElMessageBox.confirm(
        value === 'CAROUSEL'
          ? '切换为轮播后，当前独立广告素材会清空，请重新选择 2-10 张图片。'
          : '切换为单图片/视频后，当前轮播卡片会清空，并按独立广告重新选择素材。',
        '确认切换素材形式',
        { type: 'warning', confirmButtonText: '确认切换', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    resetCreativeItems()
  }
  creativeFormat.value = value
  if (value === 'CAROUSEL') delivery.split_level = 'AD'
}
const addBatchCreatives = () => {
  const existing = new Set(directForm.creatives.map(item => item.asset_id).filter(Boolean))
  const allowed = new Set(batchAssetOptions.value.map(asset => String(asset.id)))
  const selected = batchAssetIds.value.filter(id => allowed.has(String(id)))
  const added = selected.filter(id => !existing.has(id))
  if (!added.length) { ElMessage.warning('所选素材已存在于创意列表中'); return }
  const capacity = creativeFormat.value === 'CAROUSEL' ? 10 - directForm.creatives.filter(item => item.asset_id).length : added.length
  if (capacity <= 0) { ElMessage.warning('轮播最多支持 10 张图片卡片'); batchAssetIds.value = []; return }
  const accepted = added.slice(0, capacity)
  const blank = directForm.creatives.length === 1 && !directForm.creatives[0].asset_id
  if (blank) directForm.creatives.splice(0, 1)
  for (const asset_id of accepted) directForm.creatives.push({ key: `${Date.now()}-${directForm.creatives.length + 1}-${asset_id}`, asset_id, primary_text: '', headline: '', description: '', cta: 'LEARN_MORE', landing_url: '' })
  batchAssetIds.value = []
  if (accepted.length < added.length) ElMessage.warning('轮播最多支持 10 张图片，超出素材未加入')
  else ElMessage.success(creativeFormat.value === 'CAROUSEL' ? `已加入 ${accepted.length} 张轮播卡片` : `已加入 ${accepted.length} 个素材创意`)
}

const buildDirectTargeting = (adset: typeof directForm.adsets[number]) => {
  const targeting: Record<string, any> = {
    geo_locations: { countries: adset.country.split(',').map(v => v.trim()).filter(Boolean) },
    age_min: adset.age_min,
    age_max: adset.age_max,
    genders: [...adset.genders],
  }
  const interests = adset.interests.split(',').map(v => v.trim()).filter(Boolean)
  if (interests.length) targeting.flexible_spec = [{ interests: interests.map(name => ({ name })) }]
  if (adset.languages.length) targeting.languages = [...adset.languages]
  return targeting
}

const selectedTemplate = computed(() => templates.value.find(t => t.id === form.template_id) || null)
const templateLabel = (item: CampaignTemplate) => `${item.name}（${item.objective || '-'} · $${item.daily_budget ?? '-'}/天）`
const selectedTemplateLabel = computed(() => selectedTemplate.value ? templateLabel(selectedTemplate.value) : '选择投放模板')
const templateSelectWidth = computed(() => {
  const longest = templates.value.reduce((max, item) => Math.max(max, templateLabel(item).length), 8)
  return `${Math.min(640, Math.max(180, Math.ceil(longest * 14 * 1.05)))}px`
})
const directConfig = computed<Record<string, any> | null>(() => {
  if (form.publish_mode !== 'DIRECT') return null
  const creatives = directForm.creatives.map(({ key, ...creative }) => {
    const asset = mediaAssets.value.find(item => item.id === creative.asset_id)
    // 保留单个创意覆盖值；公共配置只作为空值回退。
    const merged = { ...sharedCreative, ...creative }
    for (const field of ['primary_text', 'headline', 'description', 'cta', 'landing_url']) {
      if (creative[field] === '' || creative[field] == null) merged[field] = sharedCreative[field]
    }
    // 后端不能仅凭 Meta 素材 ID 判断视频/图片；必须把素材类型随协议传递。
    if (asset?.asset_type) merged.asset_type = asset.asset_type
    return merged
  })
  return {
    name: directForm.name, objective: directForm.objective, page_id: directForm.page_id, daily_budget: directForm.daily_budget,
    creative_format: creativeFormat.value,
    delivery: { ...delivery },
    ...(creativeFormat.value === 'CAROUSEL' ? { carousel_cards: creatives } : {}),
    ...(creativeFormat.value !== 'CAROUSEL' ? { creatives } : {}),
    optimization_goal: directForm.optimization_goal, billing_event: directForm.billing_event, bid_strategy: directForm.bid_strategy,
    // 事件源仅在当前广告组实际使用转化优化时进入请求；切换到互动、展示
    // 或站内线索目标后保留界面草稿，但不把无关 Pixel/Dataset 发送给 Meta。
    ...(directNeedsTrackingAsset.value && directForm.dataset_id ? { dataset_id: directForm.dataset_id } : {}),
    ...(directNeedsTrackingAsset.value && directForm.conversion_event ? { conversion_event: directForm.conversion_event } : {}),
    adsets: directForm.adsets.map(adset => ({ name: adset.name, budget: adset.budget,
      targeting: buildDirectTargeting(adset),
      placement: { publisher_platforms: adset.publisher_platforms }, optimization_goal: adset.optimization_goal,
      billing_event: adset.billing_event, bid_strategy: adset.bid_strategy,
      bid_amount: adset.bid_strategy === 'LOWEST_COST_WITHOUT_CAP' ? undefined : adset.bid_amount,
      ...(creativeFormat.value !== 'CAROUSEL' ? { creatives } : {}) })),
  }
})

const applyEditInlineConfig = (config: Record<string, any>) => {
  directForm.name = config.name || directForm.name
  directForm.objective = config.objective || directForm.objective
  directForm.page_id = config.page_id || directForm.page_id
  directForm.daily_budget = Number(config.daily_budget || directForm.daily_budget)
  directForm.optimization_goal = config.optimization_goal || directForm.optimization_goal
  directForm.dataset_id = config.dataset_id
    || config.pixel_id
    || config.promoted_object?.dataset_id
    || config.promoted_object?.pixel_id
    || ''
  directForm.conversion_event = config.conversion_event
    || config.promoted_object?.conversion_event
    || config.promoted_object?.custom_event_type
    || directForm.conversion_event
  directForm.billing_event = config.billing_event || directForm.billing_event
  directForm.bid_strategy = config.bid_strategy || directForm.bid_strategy
  creativeFormat.value = config.creative_format === 'CAROUSEL' ? 'CAROUSEL' : 'SINGLE_IMAGE_VIDEO'
  if (config.delivery) Object.assign(delivery, config.delivery)
  const sourceCreatives = creativeFormat.value === 'CAROUSEL' ? (config.carousel_cards || []) : (config.creatives || [])
  const firstCreative = sourceCreatives[0] || {}
  for (const key of ['primary_text', 'headline', 'description', 'cta', 'landing_url']) {
    if (firstCreative[key] != null) (sharedCreative as any)[key] = firstCreative[key]
  }
  const adsets = Array.isArray(config.adsets) && config.adsets.length ? config.adsets : []
  directForm.adsets.splice(0, directForm.adsets.length, ...adsets.map((item: any, index: number) => {
    const targeting = item.targeting || {}
    const countries = targeting.geo_locations?.countries || []
    return {
      key: `edit-adset-${Date.now()}-${index}`,
      name: item.name || `广告组 ${index + 1}`,
      budget: Number(item.budget || directForm.daily_budget),
      country: Array.isArray(countries) ? countries.join(',') : String(countries || 'US'),
      age_min: Number(targeting.age_min || 18),
      age_max: Number(targeting.age_max || 65),
      genders: Array.isArray(targeting.genders) ? [...targeting.genders] : [1, 2],
      interests: (targeting.flexible_spec?.[0]?.interests || []).map((v: any) => v.name || '').filter(Boolean).join(','),
      languages: Array.isArray(targeting.languages) ? [...targeting.languages] : [],
      publisher_platforms: item.placement?.publisher_platforms || ['facebook'],
      optimization_goal: item.optimization_goal || directForm.optimization_goal,
      billing_event: item.billing_event || directForm.billing_event,
      bid_strategy: item.bid_strategy || directForm.bid_strategy,
      bid_amount: Number(item.bid_amount || 1),
    }
  }))
  if (!directForm.adsets.length) addDirectAdset()
  const creatives = Array.isArray(sourceCreatives) ? sourceCreatives : []
  directForm.creatives.splice(0, directForm.creatives.length, ...creatives.map((item: any, index: number) => ({
    key: `edit-creative-${Date.now()}-${index}`,
    asset_id: item.asset_id || '',
    primary_text: item.primary_text || '',
    headline: item.headline || '',
    description: item.description || '',
    cta: item.cta || 'LEARN_MORE',
    landing_url: item.landing_url || '',
  })))
  if (!directForm.creatives.length) addDirectCreative()
}
const revisionSnapshot = computed<Record<string, any>>(() => ({
  template_id: form.publish_mode === 'TEMPLATE' ? form.template_id || null : null,
  source: form.publish_mode,
  inline_config: form.publish_mode === 'DIRECT' ? directConfig.value : null,
  ad_account_ids: [...form.ad_account_ids],
  budget_override: form.budget_override || null,
  status: form.status,
  sinan_promotion_id: form.sinan_promotion_id || null,
  access_business_ids: { ...accessBusinessIds },
  ad_group_mode: adGroupMode.value,
  ad_group_selections: adGroupSelectionsPayload.value,
}))

const formatRevisionValue = (value: any) => {
  if (value === undefined || value === null || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const applyRevisionSnapshot = async (revision: CampaignJobRevision) => {
  const current = revision.snapshot?.current
  if (!current || typeof current !== 'object') return
  const source = String(current.source || '').toUpperCase()
  form.publish_mode = source === 'DIRECT' ? 'DIRECT' : 'TEMPLATE'
  await nextTick()
  if (source === 'DIRECT' && current.inline_config) {
    applyEditInlineConfig(current.inline_config)
  } else if (current.template_id) {
    form.template_id = current.template_id
  }
  if (Array.isArray(current.ad_account_ids)) form.ad_account_ids = [...current.ad_account_ids]
  form.budget_override = Number(current.budget_override || 0)
  form.status = current.status || 'PAUSED'
  form.sinan_promotion_id = current.sinan_promotion_id || ''
  adGroupMode.value = (current.ad_group_mode || 'NEW') as 'NEW' | 'EXISTING' | 'COPY'
  Object.keys(accessBusinessIds).forEach(id => delete accessBusinessIds[id])
  Object.assign(accessBusinessIds, current.access_business_ids || {})
  Object.keys(existingAdGroupSelections).forEach(id => delete existingAdGroupSelections[id])
  for (const [accountId, selection] of Object.entries(current.ad_group_selections || {})) {
    if ((selection as any)?.ad_group_id) existingAdGroupSelections[accountId] = (selection as any).ad_group_id
  }
}

const saveRevisionDraft = async (silent = false) => {
  if (!editRevisionId.value) return
  if (revisionSavePromise) return revisionSavePromise
  const task = (async () => {
    const snapshot = revisionSnapshot.value
    const snapshotKey = JSON.stringify(snapshot)
    revisionSaving.value = true
    try {
      const { data } = await jobsApi.updateRevision(editRevisionId.value!, {
        snapshot,
        account_ids: [...form.ad_account_ids],
      })
      revisionRecord.value = data
      if (JSON.stringify(revisionSnapshot.value) === snapshotKey) revisionDirty.value = false
      if (!silent) ElMessage.success('修订草稿已保存')
    } finally {
      revisionSaving.value = false
    }
  })()
  revisionSavePromise = task
  try {
    await task
  } finally {
    if (revisionSavePromise === task) revisionSavePromise = null
  }
}

const scheduleRevisionAutosave = () => {
  if (revisionSaveTimer !== null) window.clearTimeout(revisionSaveTimer)
  if (!editRevisionId.value || restoringRevision) return
  revisionSaveTimer = window.setTimeout(() => {
    revisionSaveTimer = null
    saveRevisionDraft(true).catch(() => undefined)
  }, 800)
}

const flushRevisionDraft = async () => {
  if (revisionSaveTimer !== null) {
    window.clearTimeout(revisionSaveTimer)
    revisionSaveTimer = null
  }
  if (editRevisionId.value && revisionDirty.value) await saveRevisionDraft(true)
}

const templateReady = computed(() => form.publish_mode === 'DIRECT'
  ? !!directConfig.value?.page_id
  : !!selectedTemplate.value?.creative_config_json?.page_id)
const canSubmit = computed(() => (form.publish_mode === 'DIRECT' ? !!directConfig.value : !!form.template_id) && templateReady.value && form.ad_account_ids.length > 0 && !!preflightResult.value?.passed && !!preflightResult.value?.preview_id && !!preflightResult.value?.snapshot_hash)
const templateBudget = computed(() => {
  if (!selectedTemplate.value) return '-'
  if (selectedTemplate.value.budget_type === 'LIFETIME') return '$' + (selectedTemplate.value.lifetime_budget ?? '-') + ' 总预算'
  return '$' + (selectedTemplate.value.daily_budget ?? '-') + ' / 天'
})
const templateSchedule = computed<Record<string, string>>(() => selectedTemplate.value?.creative_config_json?.schedule || {})
const formatScheduleTime = (value?: string | null) => value
  ? new Date(value).toLocaleString('zh-CN', { hour12: false })
  : '未设置'
const accessBusinessIds = reactive<Record<string, string>>({})
const selectedAccountRows = computed(() => accounts.value.filter(account => form.ad_account_ids.includes(account.id)))
const selectedTemplateTrackingConfig = computed(() => selectedTemplate.value?.creative_config_json || {})
const selectedTemplateTrackingAssetId = computed(() => selectedTemplateTrackingConfig.value.dataset_id
  || selectedTemplateTrackingConfig.value.pixel_id
  || selectedTemplateTrackingConfig.value.promoted_object?.dataset_id
  || selectedTemplateTrackingConfig.value.promoted_object?.pixel_id
  || '')
const templateOptimizationGoal = computed(() => selectedTemplate.value?.optimization_goal
  || selectedTemplateTrackingConfig.value.optimization_goal
  || selectedTemplateTrackingConfig.value.adsets?.[0]?.optimization_goal
  || '')
const templateNeedsTrackingAsset = computed(() => isConversionOptimizationGoal(templateOptimizationGoal.value)
  || (selectedTemplateTrackingConfig.value.adsets || []).some((item: any) => isConversionOptimizationGoal(item?.optimization_goal)))
const directNeedsTrackingAsset = computed(() => isConversionOptimizationGoal(directForm.optimization_goal)
  || directForm.adsets.some(item => isConversionOptimizationGoal(item.optimization_goal)))
const trackingAssetRequired = computed(() => form.publish_mode === 'DIRECT' ? directNeedsTrackingAsset.value : templateNeedsTrackingAsset.value)
const trackingConfigReady = computed(() => !trackingAssetRequired.value
  || (form.publish_mode === 'DIRECT'
    ? !!directForm.dataset_id && !!directForm.conversion_event
    : !!selectedTemplateTrackingAssetId.value))
const formatTrackingAssetTime = (value?: string | null) => value
  ? new Date(value).toLocaleString('zh-CN', { hour12: false })
  : '未同步'
const trackingAssetStatusLabel = (asset: MetaTrackingAsset) => asset.last_sync_error
  ? '同步异常'
  : asset.status === 'ACTIVE' && asset.usable !== false ? '可用' : '不可用'
const trackingAssetStatusType = (asset: MetaTrackingAsset) => asset.last_sync_error
  ? 'danger' : asset.status === 'ACTIVE' && asset.usable !== false ? 'success' : 'warning'
const creativeCount = (template: CampaignTemplate | null) => {
  if (template?.creative_config_json?.creative_format === 'CAROUSEL') return 1
  const creatives = template?.creative_config_json?.creatives
  return Array.isArray(creatives) && creatives.length ? creatives.length : template?.creative_config_json ? 1 : 0
}
const adsetCount = (template: CampaignTemplate | null) => {
  const adsets = template?.creative_config_json?.adsets
  return Array.isArray(adsets) && adsets.length ? adsets.length : 1
}
const currentAdsetCount = computed(() => form.publish_mode === 'DIRECT' ? directForm.adsets.length : adsetCount(selectedTemplate.value))
const selectedExistingAdGroup = (accountId: string) =>
  (existingAdGroups[accountId] || []).find(group => group.id === existingAdGroupSelections[accountId])
const adGroupSyncStateLabel = (state?: string) => ({
  PENDING: '同步任务排队中',
  STARTED: '同步任务执行中',
  RETRY: '同步任务重试中',
  SUCCESS: '同步任务完成',
  PARTIAL_SUCCESS: '同步完成，但有部分对象异常',
  STALE: '同步完成，但广告组信息仍未刷新',
  FAILURE: '同步任务失败',
  REVOKED: '同步任务已取消',
}[state || ''] || state || '')
const adGroupSelectionsPayload = computed(() => {
  if (adGroupMode.value === 'NEW') return {}
  return Object.fromEntries(
    form.ad_account_ids
      .filter(id => existingAdGroupSelections[id])
      .map(id => {
        const selected = selectedExistingAdGroup(id)
        return [id, {
          mode: adGroupMode.value,
          ad_group_id: existingAdGroupSelections[id],
          ad_group_external_id: selected?.ad_group_id,
        }]
      }),
  )
})
const existingAdGroupsReady = computed(() => adGroupMode.value === 'NEW'
  || (currentAdsetCount.value === 1 && form.ad_account_ids.every(id => {
    const selected = selectedExistingAdGroup(id)
    return !!selected && !selected.stale && !existingAdGroupSyncing[id]
  })))
const directCreativesReady = computed(() => {
  const creatives = (creativeFormat.value === 'CAROUSEL' ? directConfig.value?.carousel_cards : directConfig.value?.creatives) as any[] | undefined
  const countReady = creativeFormat.value === 'CAROUSEL' ? !!creatives && creatives.length >= 2 && creatives.length <= 10 : !!creatives?.length
  const typeReady = creativeFormat.value !== 'CAROUSEL' || creatives?.every(item => mediaAssets.value.find(asset => asset.id === item.asset_id)?.asset_type === 'image')
  return countReady && !!typeReady && !!creatives?.length && creatives.every(item => !!item.asset_id && (
    (mediaAssets.value.find(asset => asset.id === item.asset_id)?.asset_type === 'video' && !item.landing_url) || /^https?:\/\//.test(item.landing_url)
  ))
})
const canNext = computed(() => {
  if (activeStep.value === 0) return form.publish_mode === 'DIRECT'
    ? directObjectiveValid.value && !!directConfig.value?.page_id && !!directConfig.value?.name && (!form.save_as_template || !!form.template_name.trim()) && directForm.adsets.length > 0 && directForm.adsets.every(item => !!item.name && !!item.country && Number(item.budget) > 0 && item.age_min <= item.age_max) && directCreativesReady.value
    : !!form.template_id && templateReady.value
  if (activeStep.value === 2) return form.ad_account_ids.length > 0 && existingAdGroupsReady.value
  return true
})
const goCreateTemplate = () => router.push('/dashboard/templates')

const nextStep = async () => {
  if (activeStep.value === 2) {
    await runPreflight()
    if (!preflightResult.value?.passed) return
  }
  activeStep.value++
}

const progressPercent = computed(() => {
  if (!currentJob.value || !currentJob.value.total_accounts) return 0
  const done = currentJob.value.success_count + currentJob.value.failed_count
  return Math.round((done / currentJob.value.total_accounts) * 100)
})

const progressStatus = computed(() => {
  if (!currentJob.value) return undefined
  if (currentJob.value.status === 'SUCCESS') return 'success'
  if (currentJob.value.status === 'FAILED' || currentJob.value.status === 'CANCELLED') {
    return 'exception'
  }
  return undefined
})

const statusTagType = (status: string) =>
  ({
    PENDING: 'info',
    VALIDATING: 'info',
    QUEUED: 'info',
    RUNNING: 'primary',
    SUCCESS: 'success',
    PARTIAL_SUCCESS: 'warning',
    FAILED: 'danger',
    CANCELLED: 'info',
  }[status] || 'info')

const itemTagType = (status: string) =>
  ({ SUCCESS: 'success', FAILED: 'danger', RUNNING: 'primary', PENDING: 'info' }[status] || 'info')

// ---------------- 数据加载 ----------------
const loadTemplates = async () => {
  loadingTemplates.value = true
  try {
    const { data } = await templatesApi.list('ACTIVE')
    templates.value = data
  } finally {
    loadingTemplates.value = false
  }
}

const loadAccounts = async () => {
  loadingAccounts.value = true
  try {
    const { data } = await accountApi.availableForDeployment({ allow_paused_debug: true })
    // 接口返回 { total, accounts }，不能把整个响应对象当成账户数组。
    accounts.value = data.accounts || []
  } finally {
    loadingAccounts.value = false
  }
}

const loadJobs = async () => {
  loadingJobs.value = true
  try {
    const { data } = await jobsApi.list({ limit: 50 })
    jobs.value = data
  } finally {
    loadingJobs.value = false
  }
}

// ---------------- 任务提交与轮询 ----------------
const stopPolling = () => {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

const loadRateLimitStatus = async () => {
  const first = selectedAccountRows.value[0]
  if (!first) { rateLimitStatus.value = null; return }
  try {
    const { data } = await accountApi.rateLimitStatus(first.id)
    rateLimitStatus.value = data.rate_limits?.hour || null
  } catch { rateLimitStatus.value = null }
}

const syncAccessBusinessDefaults = () => {
  for (const account of selectedAccountRows.value) {
    if (accessBusinessIds[account.id]) continue
    const owner = account.accessible_businesses?.find(item => item.business_id === account.business?.id)
    const first = owner || account.accessible_businesses?.find(item => item.status === 'ACTIVE')
    if (first) accessBusinessIds[account.id] = first.business_id
  }
  for (const id of Object.keys(accessBusinessIds)) {
    if (!form.ad_account_ids.includes(id)) delete accessBusinessIds[id]
  }
}

const loadEditSource = async (jobId: string, revisionId?: string) => {
  try {
    const { data } = await jobsApi.getEditSource(jobId)
    const { data: revision } = revisionId
      ? await jobsApi.getRevision(revisionId)
      : await jobsApi.createRevision(jobId, { account_ids: data.ad_account_ids })
    if (revision.base_job_id !== jobId) throw new Error('修订草稿与来源任务不一致')
    restoringRevision = true
    editSource.value = data
    editRevisionId.value = revision.id
    revisionRecord.value = revision
    form.ad_account_ids = data.ad_account_ids || []
    form.status = data.status || 'PAUSED'
    form.budget_override = Number(data.budget_override || 0)
    form.sinan_promotion_id = data.sinan_promotion_id || ''
    adGroupMode.value = (data.ad_group_mode || 'NEW') as 'NEW' | 'EXISTING' | 'COPY'
    Object.assign(accessBusinessIds, data.access_business_ids || {})
    if (data.source === 'DIRECT' && data.inline_config) {
      form.publish_mode = 'DIRECT'
      applyEditInlineConfig(data.inline_config)
    } else {
      form.publish_mode = 'TEMPLATE'
      await nextTick()
      form.template_id = data.template_id || ''
    }
    await applyRevisionSnapshot(revision)
    await nextTick()
    revisionDirty.value = false
    restoringRevision = false
    ElMessage.info(`已加载任务失败配置，修复后将生成新的修订任务（来源 ${jobId}）`)
  } catch {
    restoringRevision = false
    ElMessage.error('无法加载原任务配置，请从任务详情重新进入编辑')
  }
}

const loadExistingAdGroups = async (accountId: string, keyword = '') => {
  existingAdGroupLoading[accountId] = true
  try {
    const { data } = await campaignsApi.searchAdGroups({ account_id: adGroupMode.value === 'EXISTING' ? accountId : undefined, q: keyword || undefined, limit: 50 })
    const selected = selectedExistingAdGroup(accountId)
    const rows = Array.isArray(data) ? data : []
    existingAdGroups[accountId] = selected && !rows.some(item => item.id === selected.id) ? [selected, ...rows] : rows
  } catch {
    existingAdGroups[accountId] = []
  } finally {
    existingAdGroupLoading[accountId] = false
  }
}

const syncExistingAdGroup = async (targetAccountId: string) => {
  const selected = selectedExistingAdGroup(targetAccountId)
  if (!selected || existingAdGroupSyncing[targetAccountId]) return
  existingAdGroupSyncing[targetAccountId] = true
  existingAdGroupSyncState[targetAccountId] = 'PENDING'
  delete existingAdGroupSyncError[targetAccountId]
  try {
    const { data } = await campaignsApi.syncAdGroup(selected.id)
    ElMessage.success('已提交广告组同步，完成后将自动刷新配置')
    for (let attempt = 0; attempt < 45; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 2000))
      const { data: task } = await campaignsApi.taskStatus(data.task_id)
      existingAdGroupSyncState[targetAccountId] = task.state
      if (task.state === 'FAILURE' || task.state === 'REVOKED') {
        existingAdGroupSyncError[targetAccountId] = task.error || '同步任务失败，请重试'
        return
      }
      const taskStatus = String(task.result?.status || '').toLowerCase()
      if (taskStatus === 'failed') {
        existingAdGroupSyncState[targetAccountId] = 'FAILURE'
        existingAdGroupSyncError[targetAccountId] = task.result?.error || task.error || '同步任务失败，请重试'
        return
      }
      // 新的定向同步任务必须回传本次刷新的 canonical AdGroup。
      // 如果没有该字段，通常是 Celery Worker 尚未加载新任务代码，
      // 不能把旧的全量同步结果误认为已刷新当前选中广告组。
      if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(task.state)
        && taskStatus !== 'failed'
        && String(task.result?.ad_group_id || '') !== String(selected.id)) {
        existingAdGroupSyncState[targetAccountId] = 'FAILURE'
        existingAdGroupSyncError[targetAccountId] = '同步任务已完成，但 Worker 未返回当前广告组刷新结果，请重启 Celery Worker 后重试'
        return
      }
      await loadExistingAdGroups(targetAccountId)
      const refreshed = selectedExistingAdGroup(targetAccountId)
      if (refreshed && !refreshed.stale) {
        if (task.result?.status === 'partial_success') {
          existingAdGroupSyncState[targetAccountId] = 'PARTIAL_SUCCESS'
          existingAdGroupSyncError[targetAccountId] = `已刷新，但有 ${task.result.error_count || 0} 项同步异常，可到任务中心查看详情`
        } else {
          existingAdGroupSyncState[targetAccountId] = 'SUCCESS'
        }
        ElMessage.success('广告组配置已刷新，可以继续预检')
        return
      }
      if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(task.state)) break
    }
    existingAdGroupSyncState[targetAccountId] = 'STALE'
    existingAdGroupSyncError[targetAccountId] = '同步任务已结束，但广告组信息仍未刷新，请重试或检查任务中心'
  } catch {
    existingAdGroupSyncState[targetAccountId] = 'FAILURE'
    existingAdGroupSyncError[targetAccountId] = '无法读取同步任务状态，请检查网络或任务中心'
    ElMessage.error('广告组同步失败，请检查同步权限或任务中心')
  } finally {
    existingAdGroupSyncing[targetAccountId] = false
  }
}

const loadMetaPages = async () => {
  try {
    const { data } = await metaPagesApi.list('ACTIVE')
    metaPages.value = data || []
  } catch {
    metaPages.value = []
  }
}

const syncMetaPages = async () => {
  pagesSyncing.value = true
  try {
    const { data } = await metaPagesApi.syncAll()
    await loadMetaPages()
    const conflictCount = Number(data?.conflict_count || 0)
    if (data?.status === 'FAILED') ElMessage.error('Facebook 页面同步失败')
    else if (conflictCount) ElMessage.warning(`${conflictCount} 个 Facebook 页面已绑定其他授权，请使用对应 Connector 凭据单独同步`)
    else if (data?.status === 'PARTIAL_SUCCESS') ElMessage.warning('部分 Facebook 页面同步失败，请检查授权状态')
    else if (!metaPages.value.length) ElMessage.warning('当前授权未返回可用的 Facebook 页面')
    else ElMessage.success(`已同步 ${metaPages.value.length} 个 Facebook 页面`)
  } catch {
    ElMessage.error('Facebook 页面同步失败，请检查 Meta 授权状态')
  } finally {
    pagesSyncing.value = false
  }
}

const loadTrackingAssets = async (accountIds = form.ad_account_ids) => {
  const requestNo = ++trackingAssetsRequest
  if (form.publish_mode !== 'DIRECT' || !directNeedsTrackingAsset.value || !accountIds.length) {
    trackingAssets.value = []
    trackingAssetsError.value = ''
    return
  }
  trackingAssetsLoading.value = true
  trackingAssetsError.value = ''
  try {
    const { data } = await metaTrackingAssetsApi.list([...accountIds])
    // 后端已按账户返回关联范围；这里再做一次前端保护，避免旧响应覆盖新账户选择。
    if (requestNo !== trackingAssetsRequest) return
    trackingAssets.value = (data.items || []).filter(item => accountIds.every(id => item.account_ids.includes(id)))
    const selectedAssetStillAvailable = trackingAssets.value.some(item => item.id === directForm.dataset_id)
    if (!selectedAssetStillAvailable) directForm.dataset_id = ''
    // 只有一个共同可用事件源时自动选中，减少投放人员重复操作；
    // 存在多个资产时保留空值，让用户明确选择，避免误用 Pixel。
    if (!directForm.dataset_id && trackingAssets.value.length === 1) {
      directForm.dataset_id = trackingAssets.value[0].id
    }
  } catch (error: any) {
    if (requestNo !== trackingAssetsRequest) return
    trackingAssets.value = []
    trackingAssetsError.value = error?.response?.data?.detail || 'Pixel / 数据集读取失败，请检查 Meta 授权状态'
  } finally {
    if (requestNo === trackingAssetsRequest) trackingAssetsLoading.value = false
  }
}

const loadDirectResources = async () => {
  await Promise.all([
    loadMetaPages(),
    mediaApi.list()
      .then(({ data }) => { mediaAssets.value = (data || []).filter((item: any) => ['READY', 'PENDING', 'PROCESSING'].includes(item.status)) })
      .catch(() => { mediaAssets.value = [] }),
  ])
}

const pollAssetBindings = (assetIds: string[]): Promise<void> => {
  if (assetPollTimer !== null) window.clearInterval(assetPollTimer)
  let rounds = 0
  return new Promise(resolve => {
    assetPollTimer = window.setInterval(async () => {
      rounds += 1
      try {
        const results = await Promise.all(assetIds.map(id => mediaApi.bindings(String(id))))
        assetBindings.value = results.flatMap(result => result.data)
        const pending = assetBindings.value.some(row => ['PENDING', 'UPLOADING', 'PROCESSING'].includes(row.status))
        if (!pending || rounds >= 30) {
          window.clearInterval(assetPollTimer as number)
          assetPollTimer = null
          resolve()
        }
      } catch {
        if (rounds >= 30) {
          window.clearInterval(assetPollTimer as number)
          assetPollTimer = null
          resolve()
        }
      }
    }, 2000)
  })
}

const startPolling = (jobId: string) => {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      const { data } = await jobsApi.get(jobId)
      currentJob.value = data
      if (isFinalStatus(data.status)) {
        stopPolling()
        await loadJobs()
      }
    } catch (e) {
      stopPolling()
    }
  }, 2000)
}

const submit = async () => {
  if (!canSubmit.value) {
    ElMessage.warning(!templateReady.value ? '模板尚未选择有效 Facebook 页面' : '请选择至少一个可投放广告账户')
    return
  }
  // 二次确认前不准备素材、不创建 Job；用户取消时不会产生任何外部副作用。
  try {
    await ElMessageBox.confirm(
      `即将为 ${form.ad_account_ids.length} 个账户创建 ${form.status === 'PAUSED' ? '暂停（调试）' : '立即启用'}广告对象。${form.status === 'PAUSED' ? '暂停状态不会开始投放，但仍可能受 Meta 账户资格限制。' : '立即启用可能产生实际广告费用。'}确认继续吗？`,
      '确认提交广告发布',
      {
        type: form.status === 'ACTIVE' ? 'warning' : 'info',
        confirmButtonText: '确认提交',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  // 预览页停留期间账户状态可能已变化，提交前重新执行只读预检。
  await runPreflight()
  if (!preflightResult.value?.passed) {
    ElMessage.error('提交前预检未通过，请处理阻断项')
    return
  }

  submitting.value = true
  try {
    syncAccessBusinessDefaults()
    // 素材是按广告账户生成 Meta 映射的；绑定占位和上传由后端投放任务
    // 幂等处理。不要在提交 Job 前调用 /prepare：素材仍在 OSS 处理时，
    // 该接口会返回 409，导致真正的 campaign-create 请求永远不会发出。
    // 后端 create_campaign_for_account 会负责创建绑定、派发上传并等待素材就绪。
    const selectedConfig = selectedTemplate.value?.creative_config_json
    const creatives = selectedConfig?.creative_format === 'CAROUSEL'
      ? selectedConfig?.carousel_cards
      : selectedConfig?.creatives || (creativeFormat.value === 'CAROUSEL' ? directConfig.value?.carousel_cards : directConfig.value?.creatives)
    const assetIds = Array.isArray(creatives)
      ? [...new Set(creatives.map((item: any) => item?.asset_id).filter(Boolean))]
      : []
    const { data } = await jobsApi.createCampaign({
      template_id: form.template_id || undefined,
      inline_config: form.publish_mode === 'DIRECT' ? directConfig.value || undefined : undefined,
      source: form.publish_mode,
      save_as_template: form.save_as_template,
      template_name: form.template_name || undefined,
      ad_account_ids: form.ad_account_ids,
      budget_override: form.budget_override || undefined,
      status: form.status,
      sinan_promotion_id: form.sinan_promotion_id || undefined,
      access_business_ids: Object.keys(accessBusinessIds).length ? { ...accessBusinessIds } : undefined,
      ad_group_mode: adGroupMode.value,
      ad_group_selections: adGroupSelectionsPayload.value,
      preview_id: preflightResult.value.preview_id,
      snapshot_hash: preflightResult.value.snapshot_hash,
      idempotency_key: editSource.value
        ? `edit:${editSource.value.source_job_id}:${preflightResult.value.preview_id}`
        : `publish:${preflightResult.value.preview_id}`,
      source_job_id: editSource.value?.source_job_id,
      revision_id: editRevisionId.value || undefined,
    })
    if (data.rejected_accounts?.length) {
      ElMessage.warning(`有 ${data.rejected_accounts.length} 个账号未进入任务，请检查账号状态`)
    }
    ElMessage.success(`任务已提交：${data.job_id}（${data.source === 'DIRECT' ? '直接配置' : '模板'}，共 ${data.total_accounts} 个账户）`)
    const { data: job } = await jobsApi.get(data.job_id)
    currentJob.value = job
    if (assetIds.length) pollAssetBindings(assetIds.map(String))
    startPolling(data.job_id)
    await loadJobs()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  } finally {
    submitting.value = false
  }
}

const runPreflight = async () => {
  if (form.publish_mode === 'TEMPLATE' && !form.template_id || form.publish_mode === 'DIRECT' && !directConfig.value || !form.ad_account_ids.length) return
  preflighting.value = true
  try {
    await flushRevisionDraft()
    if (form.publish_mode === 'DIRECT' && form.save_as_template && !form.template_id && directConfig.value) {
      const firstAdset = directConfig.value.adsets?.[0] || {}
      const { data: saved } = await templatesApi.create({
        name: form.template_name || directConfig.value.name,
        objective: directConfig.value.objective,
        daily_budget: directConfig.value.daily_budget,
        bid_strategy: firstAdset.bid_strategy,
        optimization_goal: firstAdset.optimization_goal,
        billing_event: firstAdset.billing_event,
        targeting_json: firstAdset.targeting,
        placement_json: firstAdset.placement,
        creative_config_json: {
          ...directConfig.value,
          page_id: directConfig.value.page_id,
          adsets: directConfig.value.adsets,
        },
      })
      form.template_id = saved.id
      ElMessage.success(`已保存投放模板：${saved.name}`)
    }
    syncAccessBusinessDefaults()
    const { data } = await jobsApi.preflightCampaign({ template_id: form.template_id || undefined, inline_config: form.publish_mode === 'DIRECT' ? directConfig.value || undefined : undefined, template_name: form.template_name || undefined, save_as_template: form.save_as_template, source: form.publish_mode, ad_account_ids: form.ad_account_ids, budget_override: form.budget_override || undefined, status: form.status, sinan_promotion_id: form.sinan_promotion_id || undefined, access_business_ids: Object.keys(accessBusinessIds).length ? { ...accessBusinessIds } : undefined, ad_group_mode: adGroupMode.value, ad_group_selections: adGroupSelectionsPayload.value, source_job_id: editSource.value?.source_job_id, revision_id: editRevisionId.value || undefined })
    if (data.template_id && form.publish_mode === 'DIRECT') form.template_id = data.template_id
    preflightResult.value = data
    if (editRevisionId.value && data.passed) {
      const { data: revision } = await jobsApi.getRevision(editRevisionId.value)
      revisionRecord.value = revision
      revisionDirty.value = false
    }
    if (!data.passed) ElMessage.error('预检未通过，请处理阻断项')
  } finally { preflighting.value = false }
}

// 账户选择变化后刷新限流水位；这是参考水位，不替代 Meta app-level 限流返回。
watch(form, loadRateLimitStatus, { deep: true })
watch(() => form.publish_mode, mode => {
  form.template_id = ''
  preflightResult.value = null
  if (mode === 'TEMPLATE') form.save_as_template = false
})
watch(adGroupMode, () => {
  preflightResult.value = null
  if (adGroupMode.value !== 'NEW') {
    for (const id of form.ad_account_ids) loadExistingAdGroups(id)
  }
})
watch(() => form.ad_account_ids.slice(), ids => {
  for (const id of Object.keys(existingAdGroupSelections)) {
    if (!ids.includes(id)) delete existingAdGroupSelections[id]
  }
  for (const id of ids) {
    if (adGroupMode.value !== 'NEW' && !existingAdGroups[id]) loadExistingAdGroups(id)
  }
  loadTrackingAssets(ids)
  preflightResult.value = null
})
watch(() => directForm.optimization_goal, () => loadTrackingAssets())
watch(() => directForm.objective, objective => {
  if (!isOptimizationGoalAllowed(objective, directForm.optimization_goal)) directForm.optimization_goal = defaultOptimizationGoal(objective)
  directForm.adsets.forEach(item => {
    if (!isOptimizationGoalAllowed(objective, item.optimization_goal)) item.optimization_goal = defaultOptimizationGoal(objective)
  })
})
watch(directNeedsTrackingAsset, (required) => {
  if (required) loadTrackingAssets()
})
watch(() => form.save_as_template, enabled => {
  if (!enabled) form.template_name = ''
})
watch([creativeFormat, () => delivery.split_level], () => {
  // 轮播只能按 AD 生成；切换到 ADSET 时立即纠正，而不是等到预检才报错。
  if (creativeFormat.value === 'CAROUSEL' && delivery.split_level !== 'AD') delivery.split_level = 'AD'
  // 从多选切换到单选时保留第一份素材，避免隐藏的多余选择继续被批量加入。
  if (!batchAssetMultiple.value && batchAssetIds.value.length > 1) batchAssetIds.value = batchAssetIds.value.slice(0, 1)
})
watch([form, directForm, sharedCreative, delivery, accessBusinessIds, existingAdGroupSelections, adGroupMode, creativeFormat], () => {
  if (editRevisionId.value && !restoringRevision) {
    revisionDirty.value = true
    scheduleRevisionAutosave()
  }
}, { deep: true })

const missingAssetAccounts = computed(() => [...(preflightResult.value?.warnings || []), ...(preflightResult.value?.errors || [])].filter((item: any) => ['ASSET_SYNC_PENDING', 'ASSET_SYNC_FAILED', 'ACCOUNTS_REJECTED'].includes(item.code) && item.items?.some((row: any) => row.reason === '素材尚未同步完成' || row.reason === '素材将于投放前自动同步' || String(row.reason || '').startsWith('素材同步失败'))))
const trackingAssetIssues = computed(() => [...(preflightResult.value?.warnings || []), ...(preflightResult.value?.errors || [])].filter((item: any) => ['TRACKING_ASSET_UNAVAILABLE', 'TRACKING_ASSET_STALE'].includes(item.code)))
const preflightActionHint = (code: string) => ({
  TRACKING_ASSET_REQUIRED: '选择 Pixel / 数据集并填写转化事件，或切换为不需要事件源的优化目标。',
  TRACKING_EVENT_INVALID: '检查事件名称格式：以字母开头，仅允许字母、数字和下划线。',
  TRACKING_ASSET_UNAVAILABLE: '重新同步事件源，或缩小目标账户范围后重新选择共同可用资产。',
  TRACKING_ASSET_STALE: '点击“重新同步事件源并预检”，确认最新资产状态。',
  ASSET_SYNC_FAILED: '点击“立即同步缺失素材”重置失败绑定并重新上传；完成后重新预检。',
  OBJECTIVE_OPTIMIZATION_INCOMPATIBLE: '调整推广目标或优化目标，使两者处于允许的组合。',
  SCHEDULE_END_REQUIRED: '返回模板编辑，补充总预算投放的结束时间。',
  SCHEDULE_TIME_INVALID: '返回模板编辑，重新选择合法的开始/结束时间。',
  SCHEDULE_RANGE_INVALID: '返回模板编辑，确保结束时间晚于开始时间。',
  BID_CONSTRAINT_INVALID: '返回模板编辑，填写大于 0 的 roas_average_floor。',
}[code] || '')
const preflightBlockedAccounts = computed(() => [...(preflightResult.value?.warnings || []), ...(preflightResult.value?.errors || [])]
  .flatMap((item: any) => item.items || []))
const preflightReasonByAccount = computed<Record<string, string>>(() => {
  const reasons: Record<string, string> = {}
  for (const item of preflightBlockedAccounts.value) {
    const reason = `${item.reason || '预检未通过'}${item.asset_id ? `（事件源 ${item.asset_id}）` : ''}`
    reasons[item.account_id] = reasons[item.account_id] ? `${reasons[item.account_id]}；${reason}` : reason
  }
  return reasons
})

const syncMissingAssets = async () => {
  const rows = missingAssetAccounts.value.flatMap((warning: any) => warning.items || []).filter((row: any) => row.reason === '素材尚未同步完成' || row.reason === '素材将于投放前自动同步' || String(row.reason || '').startsWith('素材同步失败'))
  const assetIds = [...new Set(rows.flatMap((row: any) => row.asset_ids || []))]
  const accountIds = [...new Set(rows.map((row: any) => row.account_id))]
  if (!assetIds.length || !accountIds.length) return
  syncingAssets.value = true
  try {
    await Promise.all(assetIds.map(assetId => mediaApi.prepare(String(assetId), accountIds)))
    ElMessage.success('已提交缺失素材同步任务，正在等待素材同步完成')
    await pollAssetBindings(assetIds)
    await runPreflight()
  } finally {
    syncingAssets.value = false
  }
}

const refreshTrackingAssetsAndPreflight = async () => {
  if (!form.ad_account_ids.length) return
  syncingTrackingAssets.value = true
  try {
    // 直接投放由 loadTrackingAssets 同步并更新下拉选项；模板投放也要
    // 触发一次账户级同步，确保预检读取到最新资产状态。
    if (form.publish_mode === 'DIRECT') await loadTrackingAssets(form.ad_account_ids)
    else await metaTrackingAssetsApi.list([...form.ad_account_ids])
    await runPreflight()
    ElMessage.success('事件源已刷新，并已重新执行预检')
  } finally {
    syncingTrackingAssets.value = false
  }
}

const viewJob = async (id: string) => {
  const { data } = await jobsApi.get(id)
  currentJob.value = data
  if (!isFinalStatus(data.status)) startPolling(id)
}

const retryFailed = async () => {
  if (!currentJob.value) return
  try {
    await jobsApi.retry(currentJob.value.id)
    ElMessage.success('已重新分派失败账户')
    startPolling(currentJob.value.id)
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const cancelJob = async (id: string) => {
  try {
    await jobsApi.cancel(id)
    ElMessage.success('任务已取消')
    await loadJobs()
    if (currentJob.value?.id === id) {
      const { data } = await jobsApi.get(id)
      currentJob.value = data
    }
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

onMounted(() => {
  loadTemplates()
  loadAccounts()
  loadDirectResources()
  loadJobs()
  const presetAccounts = String(route.query.account_ids || '').split(',').filter(Boolean)
  if (presetAccounts.length) form.ad_account_ids = presetAccounts
  const sourceJobId = String(route.query.source_job_id || '')
  const revisionId = String(route.query.revision_id || '')
  if (sourceJobId) loadEditSource(sourceJobId, revisionId || undefined)
})

onUnmounted(() => {
  if (assetPollTimer !== null) window.clearInterval(assetPollTimer)
  if (revisionSaveTimer !== null) window.clearTimeout(revisionSaveTimer)
})

onUnmounted(stopPolling)
</script>

<style scoped lang="scss">
.preflight-error-item { color: #f56c6c; margin-top: 4px; }
.preflight-warning { color: #e6a23c; margin-top: 4px; }
.preflight-detail { color: #606266; font-size: 12px; margin: 3px 0 0 16px; }
.preflight-blocked { color: #f56c6c; }
.preflight-ready { color: #67c23a; }
.header-bar {
  .page-title { margin: 0; font-size: 18px; }
  .page-desc { margin: 4px 0 0; font-size: 13px; color: #909399; line-height: 1.6; }
}
.tip { color: #909399; font-size: 12px; margin-top: 4px; }
.tip-inline { color: #909399; font-size: 12px; margin-left: 10px; }
.revision-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -4px 0 16px; padding: 10px 12px; border: 1px solid #d9ecff; border-radius: 6px; background: #f4f9ff; }
.page-sync-inline { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 4px; color: #909399; font-size: 12px; line-height: 1.5; }
.tracking-asset-panel { margin: 12px 0 18px; padding: 14px 16px 4px; border: 1px solid #d9ecff; border-radius: 8px; background: linear-gradient(180deg, #f7fbff 0%, #fff 100%); }
.tracking-asset-panel__title { color: #1f2d3d; font-weight: 600; font-size: 14px; }
.tracking-asset-panel__desc { margin: 4px 0 12px; color: #909399; font-size: 12px; line-height: 1.5; }
.tracking-asset-empty { padding: 8px 12px; color: #909399; font-size: 12px; line-height: 1.5; }
.tracking-asset-option { padding: 2px 0; line-height: 1.4; }
.tracking-asset-option__name { color: #303133; font-size: 13px; }
.tracking-asset-option__meta { display: flex; align-items: center; gap: 8px; margin-top: 3px; color: #909399; font-size: 11px; }
.tracking-asset-template-state { margin: 0 0 12px 110px; }
.tracking-asset-error { margin: -4px 0 12px 110px; color: #f56c6c; font-size: 12px; }
.publish-steps { margin: 6px 0 28px; }
.publish-form { max-width: 920px; }
.publish-mode { margin-bottom: 18px; }
.publish-form :deep(.el-form-item.field-medium .el-form-item__content) { max-width: 360px; }
.publish-form :deep(.el-form-item.field-wide .el-form-item__content) { max-width: 640px; }
.publish-form :deep(.el-form-item.field-medium .el-select) { width: 240px !important; }
.content-width-select :deep(.el-select__selected-item),
.content-width-select :deep(.el-input__inner) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.direct-adset { padding: 14px 16px 4px; margin: 12px 0; border: 1px solid #dcdfe6; border-radius: 8px; background: #fafcff; }
.direct-creative { padding: 14px 16px 4px; margin: 12px 0; border: 1px solid #e4e7ed; border-radius: 8px; background: #fff; }
.job-meta { color: #909399; font-size: 12px; margin-right: 6px; }
.direct-adset-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; color: #243b53; }
.existing-adgroup-list { margin: 10px 0 18px 110px; max-width: 760px; padding: 12px 14px; border: 1px solid #dcdfe6; border-radius: 8px; background: #fafcff; }
.existing-adgroup-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin: 8px 0; }
.existing-adgroup-row .account-label { width: 150px; color: #303133; }
.adgroup-option-meta { margin-left: 8px; color: #909399; }
.selected-adgroup-detail { margin-left: 160px; color: #67c23a; font-size: 12px; }
.stale-adgroup-tip { margin-left: 8px; color: #e6a23c; }
.adgroup-sync-state { margin-left: 8px; color: #409eff; }
.adgroup-sync-error { display: block; margin: 4px 0 0 160px; color: #f56c6c; }
.step-panel { min-height: 180px; padding: 8px 4px; }
.step-panel > .el-form-item { max-width: 760px; }
.step-panel > .el-alert { max-width: 760px; }
.step-panel > .el-descriptions { max-width: 760px; }
.step-panel h3 { margin: 0 0 8px; color: #1f2d3d; }
.step-desc { margin: 0 0 24px; color: #909399; font-size: 13px; }
.step-panel .el-alert { margin-top: 22px; }
.step-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; padding-top: 18px; border-top: 1px solid #ebeef5; }
.template-empty { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; color: #909399; }
.job-line { margin: 8px 0; }
.err-cat { color: #e6a23c; margin-right: 4px; }
</style>

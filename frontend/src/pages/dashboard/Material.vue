<template>
  <div class="material">
    <el-card shadow="never" class="library-shell">
      <template #header>
        <div class="header-bar">
          <div class="title-block">
            <div class="eyebrow">CONTENT LIBRARY</div>
            <h2 class="page-title">素材库</h2>
            <p class="page-desc">统一管理图片与视频素材，发布广告时可直接复用。</p>
          </div>
          <div class="header-actions">
            <el-select v-model="uploadAccountId" class="upload-account" placeholder="上传后同步账户（可选）" filterable clearable>
              <el-option v-for="account in accounts" :key="account.id" :label="`${account.account_name || account.account_id} (${account.account_id})`" :value="account.id" />
            </el-select>
            <el-upload
              :auto-upload="false"
              :show-file-list="false"
              :on-change="onSelect"
              :disabled="uploading"
              accept="image/*,video/*"
            >
              <el-button type="primary" :icon="UploadFilled" :loading="uploading">
                {{ retryAssetId ? '选择文件重试' : '上传素材' }}
              </el-button>
            </el-upload>
            <input
              ref="retryFileInput"
              class="retry-file-input"
              type="file"
              accept="image/*,video/*"
              @change="onRetryFileSelected"
            />
            <input ref="versionFileInput" class="retry-file-input" type="file" accept="image/*,video/*" @change="onVersionFileSelected" />
            <el-button @click="createGroupVisible = true">新建分组</el-button>
            <el-button :disabled="!groups.length" @click="openMembers">成员管理</el-button>
          </div>
        </div>
        <div class="shared-hint">
          <span class="hint-dot" />
          租户内共享素材，上传人仅用于记录；相同文件会自动去重。
        </div>
        <div v-if="uploading" class="upload-progress-panel">
          <div class="upload-progress-head">
            <span>{{ uploadStage }}</span>
            <span>{{ uploadProgress }}%</span>
          </div>
          <el-progress :percentage="uploadProgress" :stroke-width="8" :show-text="false" />
          <small>大视频会先校验文件指纹，再通过 OSS 分片上传；页面可安全等待或刷新后继续。</small>
        </div>
      </template>

      <div class="workspace-tabs">
        <button :class="{ active: workspaceMode === 'mine' }" @click="workspaceMode = 'mine'">我的素材</button>
        <button :class="{ active: workspaceMode === 'team' }" @click="workspaceMode = 'team'">团队素材</button>
        <button :class="{ active: workspaceMode === 'testing' }" @click="workspaceMode = 'testing'">正在测试</button>
        <button :class="{ active: workspaceMode === 'archive' }" @click="workspaceMode = 'archive'">已归档</button>
      </div>
      <div class="workspace-context">
        <div>
          <span class="context-label">当前项目工作区</span>
          <el-select v-model="filterGroup" clearable filterable placeholder="全部团队素材" class="workspace-select" @change="load">
            <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id">
              <span>{{ group.name }}</span><el-tag size="small" effect="plain" class="visibility-tag">{{ group.visibility === 'PRIVATE' ? '私有' : '团队共享' }}</el-tag>
            </el-option>
          </el-select>
        </div>
        <span class="context-help">工作区成员决定谁可以查看和编辑素材</span>
        <el-button size="small" plain :disabled="!groups.length" @click="openMembers">管理成员与授权</el-button>
      </div>

      <div class="filters">
        <div class="filter-title">素材筛选</div>
        <el-input v-model="searchKeyword" clearable class="filter-search" placeholder="搜索素材名 / 上传人 / 标签" />
        <el-select v-model="filterStatus" placeholder="投放状态" clearable class="filter-status" @change="load">
          <el-option label="全部状态" value="" />
          <el-option label="可投放" value="ready" />
          <el-option label="处理中" value="processing" />
          <el-option label="正在投放" value="delivering" />
          <el-option label="未使用" value="unused" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-select v-model="filterType" placeholder="类型" clearable class="filter-type" @change="load">
          <el-option label="全部" value="" />
          <el-option label="图片" value="image" />
          <el-option label="视频" value="video" />
        </el-select>
        <el-select v-model="filterAccount" placeholder="归属账户筛选（可选）" clearable filterable class="filter-account" @change="load">
            <el-option v-for="account in accounts" :key="account.id" :label="`${account.account_name || account.account_id} (${account.account_id})`" :value="account.id" />
        </el-select>
        <el-select v-model="filterTag" placeholder="素材标签" clearable filterable class="filter-tag" @change="load">
          <el-option v-for="tag in tags" :key="tag.id" :label="tag.name" :value="tag.id" />
        </el-select>
        <el-button class="new-tag" @click="createTagVisible = true">新建标签</el-button>
        <el-radio-group v-model="viewMode" size="small" class="view-switch">
          <el-radio-button value="card">卡片</el-radio-button>
          <el-radio-button value="list">列表</el-radio-button>
        </el-radio-group>
        <el-date-picker
          class="overview-picker"
          v-model="overviewRange"
          type="daterange"
          single-panel
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="统计开始"
          end-placeholder="统计结束"
          popper-class="date-range-popper"
          placement="bottom-start"
          :clearable="true"
          @change="loadOverview"
        />
      </div>

      <div v-if="overview" class="overview-section">
        <div class="overview-grid">
          <div class="overview-item"><span>可见素材</span><strong>{{ overview.asset_count }}</strong><small>就绪 {{ overview.ready_asset_count }}</small></div>
          <div class="overview-item highlight"><span>库存使用率</span><strong>{{ overview.inventory_usage_rate }}<em>%</em></strong><small>已使用 {{ overview.used_asset_count }} / 未使用 {{ overview.unused_asset_count }}</small></div>
          <div class="overview-item"><span>账户覆盖率</span><strong>{{ overview.account_coverage_rate }}<em>%</em></strong><small>已覆盖 {{ overview.bound_account_count }} / {{ overview.available_account_count }} 个账户</small></div>
          <div class="overview-item"><span>账户绑定</span><strong>{{ overview.ready_binding_count }}<em>/{{ overview.binding_count }}</em></strong><small>已就绪 / 总数</small></div>
          <div class="overview-item"><span>使用次数</span><strong>{{ overview.usage_count }}</strong><small>成功 {{ overview.successful_usage_count }}</small></div>
          <div class="overview-item success"><span>投放成功率</span><strong>{{ overview.success_rate }}<em>%</em></strong><small>失败 {{ overview.failed_usage_count }}</small></div>
        </div>
        <div v-if="overview.funnel.length" class="overview-funnel">
          <div class="funnel-title">素材使用漏斗 <span>统计区间内按素材去重，成功记录不代表平台转化效果</span></div>
          <div class="funnel-list">
            <div v-for="step in overview.funnel" :key="step.key" class="funnel-step">
              <div class="funnel-label"><span>{{ step.label }}</span><b>{{ step.count }}</b></div>
              <el-progress :percentage="Math.min(step.rate, 100)" :show-text="false" :stroke-width="7" />
              <small>{{ step.rate }}%</small>
            </div>
          </div>
        </div>
        <div v-if="overview.top_assets.length" class="overview-top" title="按使用次数排序">
          <span class="top-label">使用次数排行</span>
          <el-table :data="overview.top_assets.slice(0, 5)" size="small" class="top-assets-table">
            <el-table-column type="index" width="48" />
            <el-table-column prop="name" label="素材" min-width="220" show-overflow-tooltip />
            <el-table-column prop="usage_count" label="使用次数" width="100" />
            <el-table-column prop="successful_usage_count" label="成功次数" width="100" />
            <el-table-column label="成功率" width="100"><template #default="{ row }">{{ row.usage_count ? Math.round(row.successful_usage_count * 100 / row.usage_count) : 0 }}%</template></el-table-column>
          </el-table>
        </div>
        <div v-if="performanceOverview?.has_data" class="overview-performance">
          <div class="performance-title">平台效果排行 <span>按展示量排序 · {{ performanceOverview.latest_synced_at ? `最近同步 ${formatUploadedAt(performanceOverview.latest_synced_at)}` : '同步时间未知' }}</span></div>
          <el-table :data="performanceOverview.items.slice(0, 10)" size="small">
            <el-table-column type="index" width="48" />
            <el-table-column prop="name" label="素材" min-width="200" show-overflow-tooltip />
            <el-table-column prop="currency" label="币种" width="70" />
            <el-table-column label="消耗" width="105"><template #default="{ row }">{{ formatMajorMoney(row.spend, row.currency) }}</template></el-table-column>
            <el-table-column prop="impressions" label="展示" width="90" />
            <el-table-column prop="clicks" label="点击" width="80" />
            <el-table-column label="CTR" width="75"><template #default="{ row }">{{ formatPercent(row.ctr) }}</template></el-table-column>
            <el-table-column label="CPA" width="90"><template #default="{ row }">{{ formatMajorMoney(row.cpa, row.currency) }}</template></el-table-column>
            <el-table-column label="ROAS" width="75"><template #default="{ row }">{{ formatRatio(row.roas) }}</template></el-table-column>
          </el-table>
        </div>
        <div v-else-if="performanceOverviewError" class="platform-empty platform-error">
          平台 Insights 加载失败，请稍后重试。
          <el-button link type="primary" size="small" @click="loadOverview">重试</el-button>
        </div>
        <div v-else-if="performanceOverview" class="platform-empty">暂无平台 Insights：素材尚未建立广告映射，或所选区间内尚未完成数据同步。</div>
      </div>

      <div v-if="selectedIds.length" class="bulk-bar">
        <span>已选择 {{ selectedIds.length }} 个素材</span>
        <el-select v-model="moveTargetGroup" placeholder="移动到分组" clearable style="width: 180px">
          <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
        </el-select>
        <el-button type="primary" size="small" @click="moveSelected">移动</el-button>
        <el-button size="small" :loading="bulkSyncing" @click="syncSelected">同步账户</el-button>
        <el-select v-model="batchTagId" placeholder="覆盖标签" clearable style="width: 160px">
          <el-option v-for="tag in tags" :key="tag.id" :label="tag.name" :value="tag.id" />
        </el-select>
        <el-button size="small" :disabled="!batchTagId" @click="applyBatchTag">覆盖标签</el-button>
        <el-button size="small" @click="selectedIds = []">取消选择</el-button>
      </div>
      <div v-loading="loading" v-if="viewMode === 'card'" class="grid">
        <el-empty v-if="!filteredList.length" description="暂无符合条件的素材" />
        <div v-for="item in filteredList" :key="item.id" class="card">
          <el-checkbox v-if="item.can_edit" v-model="selectedIds" :label="item.id" class="asset-check"><span /></el-checkbox>
          <div class="thumb" @click="openPreview(item)">
            <img v-if="item.asset_type === 'image' && previewUrls[item.id]?.url" :src="previewUrls[item.id].url" alt="" />
            <img v-else-if="item.asset_type === 'image' && item.url" :src="item.url" alt="" />
            <img v-else-if="item.asset_type === 'video' && previewUrls[item.id]?.url" :src="previewUrls[item.id].url" alt="视频封面" />
            <video v-else-if="item.asset_type === 'video' && item.url" :src="item.url" muted :poster="item.url" />
            <el-icon v-else class="thumb-icon"><Picture /></el-icon>
            <div class="thumb-overlay">
              <span>{{ item.asset_type === 'image' ? '图片' : '视频' }}</span>
              <span class="preview-action">点击预览</span>
            </div>
          </div>
          <div class="info">
            <div class="name-row"><div class="name" :title="item.name">{{ item.name }}</div><el-tag size="small" effect="plain">V{{ item.version_number || 1 }}</el-tag><span class="ready-dot" :class="{ failed: !isAssetReady(item) }" /></div>
            <div class="uploader" :title="item.uploader_email || undefined">
              负责人：{{ item.uploader_name || '系统' }} · {{ formatUploadedAt(item.uploaded_at || item.created_at) }}
            </div>
            <div class="asset-stats clickable" @click.stop="openStats(item)">
              <span>绑定 <b>{{ item.ready_binding_count || 0 }}/{{ item.binding_count || 0 }}</b></span>
              <span>投放 <b>{{ item.successful_publish_count || 0 }}/{{ item.publish_count || 0 }}</b></span>
            </div>
            <div class="meta">
              <el-tag size="small" :type="item.asset_type === 'image' ? 'success' : 'warning'">
                {{ item.asset_type === 'image' ? '图片' : '视频' }}
              </el-tag>
              <span class="size">{{ formatSize(item.size) }}</span>
              <span v-if="item.width && item.height" class="size">{{ item.width }}×{{ item.height }}</span>
              <span v-if="item.duration" class="size">{{ formatDuration(item.duration) }}</span>
            </div>
            <div v-if="item.tag_ids?.length" class="tags">
              <el-tag v-for="tagId in item.tag_ids" :key="tagId" size="small" effect="plain">{{ tagName(tagId) }}</el-tag>
            </div>
            <div v-if="placementAdvice(item)" class="placement-tip">{{ placementAdvice(item) }}</div>
            <div class="status">
              <el-tag v-if="item.processing_status === 'READY' || (!item.processing_status && ['ready', 'READY'].includes(item.status))" size="small" type="success">素材就绪</el-tag>
              <el-tag v-else-if="['uploading', 'UPLOADING', 'PENDING', 'PROCESSING'].includes(item.status) || ['PENDING', 'PROCESSING'].includes(item.processing_status || '')" size="small" type="info">处理中</el-tag>
              <el-tooltip v-else-if="item.status === 'FAILED' || item.status === 'failed'" :content="item.error || '点击查看失败原因'" placement="top">
                <el-tag size="small" type="danger" class="clickable" @click="openFailure(item)">失败</el-tag>
              </el-tooltip>
              <el-tag v-else size="small" type="danger">失败</el-tag>
              <span v-if="item.fb_hash || item.fb_video_id" class="fb-ok">✓ 已同步 Meta</span>
            </div>
          </div>
          <div class="actions">
            <el-popconfirm v-if="item.can_edit" title="确定删除该素材？" @confirm="remove(item)">
              <template #reference>
                <el-button link type="danger" size="small">删除</el-button>
              </template>
            </el-popconfirm>
            <el-button link type="primary" size="small" :disabled="!isAssetReady(item)" @click="openBindings(item)">查看映射</el-button>
            <el-button link type="success" size="small" :disabled="!isAssetReady(item)" @click="syncAllAccounts(item)">同步账户</el-button>
            <el-button v-if="item.can_edit" link size="small" @click="refreshMetadata(item)">刷新</el-button>
            <el-button v-if="item.can_edit && isAssetReady(item)" link type="primary" size="small" @click="beginNewVersion(item)">新版本</el-button>
            <el-button
              v-if="item.can_edit && ['FAILED', 'PENDING', 'UPLOADING'].includes(String(item.status || '').toUpperCase())"
              link
              type="warning"
              size="small"
              @click="beginRetryUpload(item)"
            >
              {{ String(item.status || '').toUpperCase() === 'FAILED' ? '重新上传' : '继续上传' }}
            </el-button>
          </div>
        </div>
      </div>
      <el-table v-else v-loading="loading" :data="filteredList" class="asset-table" row-key="id" @row-click="openStats" @selection-change="onTableSelectionChange">
        <el-table-column type="selection" width="48" />
        <el-table-column label="素材" min-width="280">
          <template #default="{ row }"><div class="table-asset"><img v-if="row.asset_type === 'image' && (previewUrls[row.id]?.url || row.url)" :src="previewUrls[row.id]?.url || row.url || ''" /><div><b>{{ row.name }} <el-tag size="small" effect="plain">V{{ row.version_number || 1 }}</el-tag></b><small>{{ row.asset_type === 'image' ? '图片' : '视频' }} · {{ formatSize(row.size) }}</small></div></div></template>
        </el-table-column>
        <el-table-column label="负责人" width="140"><template #default="{ row }">{{ row.uploader_name || '系统' }}</template></el-table-column>
        <el-table-column label="使用关系" width="180"><template #default="{ row }"><span>账户 {{ row.ready_binding_count || 0 }}/{{ row.binding_count || 0 }}</span><br /><span>投放 {{ row.successful_publish_count || 0 }}/{{ row.publish_count || 0 }}</span></template></el-table-column>
        <el-table-column label="状态" width="120"><template #default="{ row }"><el-tag size="small" :type="statusTagType(row)">{{ statusLabel(row) }}</el-tag></template></el-table-column>
        <el-table-column label="最近使用" width="170"><template #default="{ row }">{{ formatUploadedAt(row.last_used_at) }}</template></el-table-column>
        <el-table-column label="操作" width="110" fixed="right"><template #default="{ row }"><el-button link type="primary" @click.stop="openStats(row)">使用详情</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="createGroupVisible" title="新建素材分组" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称"><el-input v-model="newGroupName" maxlength="128" /></el-form-item>
        <el-form-item label="可见性"><el-radio-group v-model="newGroupVisibility"><el-radio value="PRIVATE">私有</el-radio><el-radio value="TENANT">租户共享</el-radio></el-radio-group></el-form-item>
      </el-form>
      <template #footer><el-button @click="createGroupVisible = false">取消</el-button><el-button type="primary" @click="createGroup">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="createTagVisible" title="新建素材标签" width="420px">
      <el-input v-model="newTagName" maxlength="64" placeholder="例如：US、UGC、V2" />
      <template #footer><el-button @click="createTagVisible = false">取消</el-button><el-button type="primary" @click="createTag">创建</el-button></template>
    </el-dialog>
    <el-dialog v-model="membersVisible" title="分组成员管理" width="620px">
      <el-select v-model="memberGroupId" placeholder="选择分组" style="width:100%;margin-bottom:12px" @change="loadMembers">
        <el-option v-for="group in groups" :key="group.id" :label="group.name" :value="group.id" />
      </el-select>
      <div class="member-add">
        <el-input v-model="memberUserId" placeholder="输入用户 ID" />
        <el-checkbox v-model="memberCanEdit">允许编辑</el-checkbox>
        <el-button type="primary" @click="addMember">添加</el-button>
      </div>
      <el-table :data="members" size="small" v-loading="membersLoading">
        <el-table-column prop="user_id" label="用户 ID" />
        <el-table-column label="权限"><template #default="{ row }">{{ row.can_edit ? '可编辑' : '只读' }}</template></el-table-column>
        <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="danger" @click="removeMember(row.user_id)">移除</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
    <el-dialog v-model="bindingVisible" title="账号素材映射" width="720px" @closed="stopBindingPolling">
      <el-table :data="bindings" v-loading="bindingLoading" size="small">
        <el-table-column prop="account_name" label="账号" min-width="180" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="connector_task_id" label="外部任务" min-width="180" show-overflow-tooltip />
        <el-table-column prop="meta_asset_id" label="Meta 素材 ID" min-width="180" show-overflow-tooltip />
        <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.status === 'FAILED'" link type="primary" @click="retryBinding(row)">重试</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
    <el-dialog v-model="statsVisible" :title="`${statsAsset?.name || '素材'} · 使用统计`" width="760px">
      <div class="stats-toolbar">
        <span>统计区间</span>
        <el-date-picker
          v-model="statsRange"
          type="daterange"
          single-panel
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          popper-class="date-range-popper"
          placement="bottom-start"
          :clearable="true"
          @change="reloadStats"
        />
      </div>
      <el-skeleton v-if="statsLoading" :rows="4" animated />
      <template v-else-if="usageStats">
        <el-descriptions :column="4" border size="small">
          <el-descriptions-item label="使用次数">{{ usageStats.usage_count }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ usageStats.successful_usage_count }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ usageStats.failed_usage_count }}</el-descriptions-item>
          <el-descriptions-item label="最近使用">{{ formatUploadedAt(usageStats.last_used_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="stats-section-title">平台效果 <span class="stats-section-note">真实广告级 Insights，金额按币种分组</span></div>
        <el-alert
          v-if="performanceStatsError"
          type="error"
          :closable="false"
          show-icon
          title="平台 Insights 加载失败"
          description="请稍后重试，当前显示的本地使用统计不受影响。"
        />
        <el-alert
          v-else-if="!performanceStats?.has_data"
          type="info"
          :closable="false"
          show-icon
          title="暂无平台 Insights"
          description="当前素材尚未建立广告级数据映射，或所选区间内尚未完成平台数据同步。"
        />
        <template v-else>
          <div class="platform-data-note">{{ performanceStats?.data_scope_note }}<span v-if="performanceStats?.latest_synced_at"> · 最近同步 {{ formatUploadedAt(performanceStats.latest_synced_at) }}</span></div>
          <el-table :data="performanceStats?.items || []" size="small">
            <el-table-column prop="currency" label="币种" width="75" />
            <el-table-column label="消耗" width="105"><template #default="{ row }">{{ formatMajorMoney(row.spend, row.currency) }}</template></el-table-column>
            <el-table-column prop="impressions" label="展示" width="85" />
            <el-table-column prop="clicks" label="点击" width="75" />
            <el-table-column label="CTR" width="75"><template #default="{ row }">{{ formatPercent(row.ctr) }}</template></el-table-column>
            <el-table-column label="转化" width="75"><template #default="{ row }">{{ row.conversions }}</template></el-table-column>
            <el-table-column label="CPA" width="90"><template #default="{ row }">{{ formatMajorMoney(row.cpa, row.currency) }}</template></el-table-column>
            <el-table-column label="ROAS" width="75"><template #default="{ row }">{{ formatRatio(row.roas) }}</template></el-table-column>
            <el-table-column prop="latest_date" label="数据日期" min-width="110" />
          </el-table>
          <div v-if="performanceStats?.series.length" class="stats-section-title">平台每日趋势</div>
          <el-table v-if="performanceStats?.series.length" :data="performanceStats.series" size="small" max-height="260">
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column prop="currency" label="币种" width="70" />
            <el-table-column label="消耗" width="105"><template #default="{ row }">{{ formatMajorMoney(row.spend, row.currency) }}</template></el-table-column>
            <el-table-column prop="impressions" label="展示" width="85" />
            <el-table-column prop="clicks" label="点击" width="75" />
            <el-table-column label="CTR" width="75"><template #default="{ row }">{{ formatPercent(row.ctr) }}</template></el-table-column>
            <el-table-column label="转化" width="75"><template #default="{ row }">{{ row.conversions }}</template></el-table-column>
            <el-table-column label="CPA" width="90"><template #default="{ row }">{{ formatMajorMoney(row.cpa, row.currency) }}</template></el-table-column>
            <el-table-column label="ROAS" width="75"><template #default="{ row }">{{ formatRatio(row.roas) }}</template></el-table-column>
          </el-table>
        </template>
        <el-table :data="usageStats.by_account" size="small" style="margin-top:16px">
          <el-table-column prop="account_name" label="广告账户" min-width="180" />
          <el-table-column prop="usage_count" label="使用次数" width="100" />
          <el-table-column prop="successful_usage_count" label="成功" width="80" />
          <el-table-column prop="failed_usage_count" label="失败" width="80" />
          <el-table-column label="最近使用" min-width="170"><template #default="{ row }">{{ formatUploadedAt(row.last_used_at) }}</template></el-table-column>
        </el-table>
        <el-empty v-if="!usageStats.by_account.length" description="暂无投放使用记录" />
        <div class="stats-section-title">每日趋势</div>
        <el-table :data="usageStats.daily" size="small" max-height="240">
          <el-table-column prop="date" label="日期" width="140" />
          <el-table-column prop="usage_count" label="使用次数" width="110" />
          <el-table-column prop="successful_usage_count" label="成功" width="90" />
          <el-table-column prop="failed_usage_count" label="失败" width="90" />
        </el-table>
        <el-empty v-if="!usageStats.daily.length" description="所选区间暂无每日使用记录" />
        <div v-if="versions.length" class="stats-section-title">版本历史</div>
        <el-table v-if="versions.length" :data="versions" size="small">
          <el-table-column label="版本" width="100"><template #default="{ row }"><el-tag size="small" :type="row.is_current ? 'success' : 'info'">V{{ row.version_number || 1 }}</el-tag></template></el-table-column>
          <el-table-column prop="name" label="文件" min-width="220" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="上传时间" width="170"><template #default="{ row }">{{ formatUploadedAt(row.created_at) }}</template></el-table-column>
          <el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="!row.is_current && row.can_edit" link type="primary" @click="setCurrentVersion(row)">设为当前</el-button><span v-else-if="row.is_current" class="current-version">当前版本</span></template></el-table-column>
        </el-table>
      </template>
    </el-dialog>
    <el-dialog v-model="failureVisible" title="素材上传失败原因" width="620px">
      <el-descriptions v-if="failureAsset" :column="1" border size="small">
        <el-descriptions-item label="素材">{{ failureAsset.name }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ failureAsset.status }}</el-descriptions-item>
        <el-descriptions-item label="重试次数">{{ failureAsset.retry_count ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="错误信息">
          <pre class="error-detail">{{ failureAsset.error || '未记录具体错误，请查看 Worker 日志' }}</pre>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
    <el-dialog v-model="previewVisible" :title="previewAsset?.name || '素材预览'" width="760px" destroy-on-close>
      <img v-if="previewAsset?.asset_type === 'image' && previewOriginalUrl" :src="previewOriginalUrl" class="preview-media" alt="" />
      <video v-else-if="previewAsset?.asset_type === 'video' && previewOriginalUrl" :src="previewOriginalUrl" class="preview-media" controls autoplay />
      <el-empty v-else description="素材预览暂不可用" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { UploadFilled, Picture } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { mediaApi, type MediaItem, type MediaOverviewStats, type MediaUsageStats, type MediaPerformanceStats, type CreativeAssetGroup, type CreativeAssetTag, type MediaStatusFilter } from '@/api/media'
import { accountApi, type AdAccountItem } from '@/api/admin'

const list = ref<MediaItem[]>([])
const loading = ref(false)
const filterType = ref('')
const filterAccount = ref('')
const uploadAccountId = ref('')
const filterGroup = ref('')
const filterTag = ref('')
const filterStatus = ref<MediaStatusFilter | ''>('')
const searchKeyword = ref('')
const viewMode = ref<'card' | 'list'>('card')
const workspaceMode = ref<'mine' | 'team' | 'testing' | 'archive'>('team')
const savedFilterKey = 'fb-ads-material-view'
const restoreSavedView = () => {
  try {
    const saved = JSON.parse(localStorage.getItem(savedFilterKey) || '{}')
    if (['mine', 'team', 'testing', 'archive'].includes(saved.workspaceMode)) workspaceMode.value = saved.workspaceMode
    if (['card', 'list'].includes(saved.viewMode)) viewMode.value = saved.viewMode
    if (typeof saved.searchKeyword === 'string') searchKeyword.value = saved.searchKeyword
    if (typeof saved.filterType === 'string') filterType.value = saved.filterType
    if (typeof saved.filterAccount === 'string') filterAccount.value = saved.filterAccount
    if (typeof saved.filterGroup === 'string') filterGroup.value = saved.filterGroup
    if (typeof saved.filterStatus === 'string') filterStatus.value = saved.filterStatus
    if (typeof saved.filterTag === 'string') filterTag.value = saved.filterTag
  } catch { /* 忽略损坏的本地视图配置 */ }
}
watch([workspaceMode, viewMode, searchKeyword, filterType, filterAccount, filterGroup, filterStatus, filterTag], () => {
  localStorage.setItem(savedFilterKey, JSON.stringify({
    workspaceMode: workspaceMode.value, viewMode: viewMode.value, searchKeyword: searchKeyword.value,
    filterType: filterType.value, filterAccount: filterAccount.value, filterGroup: filterGroup.value,
    filterStatus: filterStatus.value, filterTag: filterTag.value,
  }))
})
const toDateInput = (value: Date) => {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const recentDateRange = (days = 30): [string, string] => {
  const end = new Date()
  const start = new Date(end)
  start.setDate(end.getDate() - days + 1)
  return [toDateInput(start), toDateInput(end)]
}
const overviewRange = ref<[string, string] | null>(recentDateRange())
const overview = ref<MediaOverviewStats | null>(null)
const performanceOverview = ref<MediaPerformanceStats | null>(null)
const performanceOverviewError = ref(false)
const groups = ref<CreativeAssetGroup[]>([])
const tags = ref<CreativeAssetTag[]>([])
const selectedIds = ref<string[]>([])
const moveTargetGroup = ref('')
const batchTagId = ref('')
const bulkSyncing = ref(false)
const createGroupVisible = ref(false)
const createTagVisible = ref(false)
const newTagName = ref('')
const membersVisible = ref(false)
const memberGroupId = ref('')
const memberUserId = ref('')
const memberCanEdit = ref(false)
const members = ref<any[]>([])
const membersLoading = ref(false)
const newGroupName = ref('')
const newGroupVisibility = ref('PRIVATE')
const accounts = ref<AdAccountItem[]>([])
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadStage = ref('准备上传')
const retryAssetId = ref('')
const retryFileInput = ref<HTMLInputElement | null>(null)
const versionFileInput = ref<HTMLInputElement | null>(null)
const bindingVisible = ref(false)
const bindingLoading = ref(false)
const bindings = ref<any[]>([])
const bindingAssetId = ref('')
const statsVisible = ref(false)
const statsLoading = ref(false)
const statsAsset = ref<MediaItem | null>(null)
const usageStats = ref<MediaUsageStats | null>(null)
const performanceStats = ref<MediaPerformanceStats | null>(null)
const performanceStatsError = ref(false)
const versions = ref<MediaItem[]>([])
const statsRange = ref<[string, string] | null>(recentDateRange())
const failureVisible = ref(false)
const failureAsset = ref<MediaItem | null>(null)
const previewUrls = reactive<Record<string, { url: string; expiresAt: number }>>({})
const previewVisible = ref(false)
const previewAsset = ref<MediaItem | null>(null)
const previewOriginalUrl = ref('')
let bindingTimer: number | null = null
let assetPollingTimer: number | null = null

const filteredList = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return list.value.filter((item) => {
    const text = [item.name, item.original_name, item.uploader_name, ...(item.tag_ids || []).map(tagName)].filter(Boolean).join(' ').toLowerCase()
    if (keyword && !text.includes(keyword)) return false
    const publishCount = item.publish_count || 0
    if (filterStatus.value === 'unused' && (item.usage_count || publishCount) > 0) return false
    if (filterStatus.value === 'delivering' && publishCount === 0) return false
    if (filterStatus.value === 'processing' && !isAssetProcessing(item)) return false
    if (filterStatus.value === 'failed' && !['FAILED', 'failed'].includes(item.status)) return false
    if (filterStatus.value === 'ready' && !isAssetReady(item)) return false
    if (workspaceMode.value === 'testing' && publishCount === 0) return false
    if (workspaceMode.value === 'mine' && !item.is_owner) return false
    if (workspaceMode.value === 'archive' && item.status !== 'ARCHIVED') return false
    return true
  })
})

const statusLabel = (item: MediaItem) => {
  if (item.status === 'ARCHIVED') return '已归档'
  if (isAssetProcessing(item)) return '处理中'
  if (['FAILED', 'failed'].includes(item.status)) return '失败'
  if ((item.publish_count || 0) > 0) return '正在投放'
  return isAssetReady(item) ? '可投放' : '待处理'
}
const statusTagType = (item: MediaItem) => {
  const label = statusLabel(item)
  return label === '正在投放' || label === '可投放' ? 'success' : label === '失败' ? 'danger' : label === '处理中' ? 'info' : 'warning'
}
const onTableSelectionChange = (rows: MediaItem[]) => {
  selectedIds.value = rows.filter(item => item.can_edit).map(item => item.id)
}

const isAssetReady = (item: MediaItem) => item.processing_status === 'READY' || (!item.processing_status && item.status === 'READY')
const isAssetProcessing = (item: MediaItem) =>
  ['UPLOADING', 'PENDING', 'PROCESSING'].includes(String(item.status || '').toUpperCase())
  || ['PENDING', 'PROCESSING'].includes(String(item.processing_status || '').toUpperCase())

const stopAssetPolling = () => {
  if (assetPollingTimer !== null) {
    window.clearInterval(assetPollingTimer)
    assetPollingTimer = null
  }
}

const syncAssetPolling = () => {
  if (list.value.some(isAssetProcessing)) {
    if (assetPollingTimer === null) {
      assetPollingTimer = window.setInterval(() => {
        if (!loading.value) void load()
      }, 5000)
    }
  } else {
    stopAssetPolling()
  }
}

const loadOverview = async () => {
  performanceOverviewError.value = false
  try {
    const [start_date, end_date] = overviewRange.value || []
    const params = {
      start_date,
      end_date,
      asset_type: filterType.value || undefined,
      account_id: filterAccount.value || undefined,
      group_id: filterGroup.value || undefined,
      tag_id: filterTag.value || undefined,
      workspace_mode: workspaceMode.value,
      status_filter: filterStatus.value || undefined,
      include_archived: workspaceMode.value === 'archive' || undefined,
    }
    const [overviewResponse, performanceResponse] = await Promise.all([
      mediaApi.statsOverview(params),
      mediaApi.performance({
        start_date,
        end_date,
        asset_type: filterType.value || undefined,
        account_id: filterAccount.value || undefined,
        group_id: filterGroup.value || undefined,
        tag_id: filterTag.value || undefined,
        workspace_mode: workspaceMode.value,
        status_filter: filterStatus.value || undefined,
        include_archived: workspaceMode.value === 'archive' || undefined,
      }).catch(() => null),
    ])
    overview.value = overviewResponse.data
    performanceOverview.value = performanceResponse?.data || null
    performanceOverviewError.value = !performanceResponse
  } catch {
    overview.value = null
    performanceOverview.value = null
    performanceOverviewError.value = true
  }
}

const load = async () => {
  loading.value = true
  try {
    const { data } = await mediaApi.list({
      asset_type: filterType.value || undefined,
      account_id: filterAccount.value || undefined,
      group_id: filterGroup.value || undefined,
      tag_id: filterTag.value || undefined,
      workspace_mode: workspaceMode.value,
      status_filter: filterStatus.value || undefined,
      include_archived: workspaceMode.value === 'archive' || undefined,
    })
    list.value = data
    await loadOverview()
    await Promise.all(data.map(async (item) => {
      if (item.url || !isAssetReady(item)) return
      const cached = previewUrls[item.id]
      if (cached && cached.expiresAt > Date.now() + 5000) return
      try {
        const { data: signed } = await mediaApi.getDownloadUrl(item.id, item.asset_type === 'video' ? 'cover' : 'thumbnail')
        previewUrls[item.id] = {
          url: signed.url,
          expiresAt: Date.now() + Math.max(signed.expires_in - 30, 30) * 1000,
        }
      } catch {
        delete previewUrls[item.id]
        /* 预览失败不影响列表 */
      }
    }))
    syncAssetPolling()
  } finally {
    loading.value = false
  }
}

watch(workspaceMode, (next, previous) => {
  if (next !== previous) void load()
})

// Element Plus 的 change 回调第二个参数是当前文件列表，不能当成 asset_id 传给后端。
// 重传场景走独立的原生 file input，由 uploadFile 显式传入原素材 ID。
const uploadFile = async (file: any, assetId = '', versionOfAssetId = '') => {
  const raw: File = file.raw
  if (!raw) return
  const validation = await validateMediaFile(raw)
  if (validation) {
    ElMessage.warning(validation)
    return
  }
  if (uploading.value) return
  uploading.value = true
  uploadProgress.value = 0
  uploadStage.value = '计算文件指纹'
  try {
    const res = await mediaApi.upload(raw, {
      account_id: uploadAccountId.value || undefined,
      group_id: filterGroup.value || undefined,
      asset_id: assetId || undefined,
      version_of_asset_id: versionOfAssetId || undefined,
    }, (event) => {
      uploadStage.value = '上传 OSS'
      if (event.total) uploadProgress.value = Math.min(99, 20 + Math.round((event.loaded / event.total) * 80))
    }, (loaded, total) => {
      uploadStage.value = '计算文件指纹'
      uploadProgress.value = total ? Math.min(20, Math.round((loaded / total) * 20)) : 0
    })
    uploadProgress.value = 100
    uploadStage.value = res.data.status === 'PROCESSING' || res.data.processing_status === 'PROCESSING'
      ? '生成封面并处理素材'
      : '上传完成'
    ElMessage.success(
      res.duplicate
        ? (uploadAccountId.value ? '文件已存在，已关联当前广告账户：' : '文件已存在，已复用共享素材：') + res.data.name
        : (uploadAccountId.value ? '已上传并提交账户同步：' : '已上传到共享素材库：') + res.data.name,
    )
    await load()
    if (res.data.status === 'PROCESSING' || res.data.processing_status === 'PROCESSING') {
      await waitForAsset(res.data.id)
      await load()
    }
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.message || '素材上传失败'
    ElMessage.error(String(detail))
  } finally {
    uploading.value = false
    if (assetId) retryAssetId.value = ''
  }
}

const versionAssetId = ref('')
const beginNewVersion = (item: MediaItem) => {
  versionAssetId.value = item.id
  ElMessage.info(`请选择 ${item.name} 的新版本文件`)
  versionFileInput.value?.click()
}
const onVersionFileSelected = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const raw = input.files?.[0]
  const assetId = versionAssetId.value
  input.value = ''
  versionAssetId.value = ''
  if (!raw || !assetId) return
  await uploadFile({ raw }, '', assetId)
}

const onSelect = async (file: any) => uploadFile(file)

const beginRetryUpload = (item: MediaItem) => {
  retryAssetId.value = item.id
  ElMessage.info('请选择与原素材相同的文件，系统会复用原素材记录并重新上传')
  retryFileInput.value?.click()
}

const onRetryFileSelected = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const raw = input.files?.[0]
  const assetId = retryAssetId.value
  input.value = ''
  if (!raw || !assetId) return
  await uploadFile({ raw }, assetId)
}

const openPreview = async (item: MediaItem) => {
  previewAsset.value = item
  previewOriginalUrl.value = ''
  previewVisible.value = true
  try {
    if (item.url) previewOriginalUrl.value = item.url
    else if (isAssetReady(item)) {
      const { data } = await mediaApi.getDownloadUrl(item.id, 'original')
      previewOriginalUrl.value = data.url
    }
  } catch { /* 全局请求层已静默，弹窗保留空状态 */ }
}

const waitForAsset = async (assetId: string) => {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 2000))
    const { data } = await mediaApi.get(assetId)
    if (isAssetReady(data) || data.status === 'FAILED' || data.processing_status === 'FAILED') return data
  }
  return null
}

const validateMediaFile = (file: File): Promise<string | null> => new Promise(resolve => {
  const isImage = file.type.startsWith('image/')
  const isVideo = file.type.startsWith('video/')
  if (!isImage && !isVideo) return resolve('仅支持图片或视频文件')
  const maxBytes = isImage ? 30 * 1024 * 1024 : 1024 * 1024 * 1024
  if (file.size > maxBytes) return resolve(`文件不能超过 ${isImage ? '30MB' : '1GB'}`)

  if (isImage) {
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(image.src)
      if (image.width < 600 || image.height < 600) resolve('图片尺寸不能小于 600 × 600')
      else if (image.width / image.height < 0.5 || image.width / image.height > 2.2) resolve('图片比例不适合常用 Meta 广告版位')
      else resolve(null)
    }
    image.onerror = () => resolve('图片文件无法解析')
    image.src = URL.createObjectURL(file)
    return
  }

  const video = document.createElement('video')
  video.preload = 'metadata'
  video.onloadedmetadata = () => {
    URL.revokeObjectURL(video.src)
    if (!video.videoWidth || !video.videoHeight) resolve('视频尺寸无法识别')
    else if (video.duration > 241) resolve('视频时长不能超过 241 秒')
    else if (video.videoWidth < 600 || video.videoHeight < 600) resolve('视频尺寸不能小于 600 × 600')
    else resolve(null)
  }
  video.onerror = () => resolve('视频文件无法解析')
  video.src = URL.createObjectURL(file)
})

const createGroup = async () => {
  if (!newGroupName.value.trim()) { ElMessage.warning('请输入分组名称'); return }
  try {
    const { data } = await mediaApi.groups.create({ name: newGroupName.value.trim(), visibility: newGroupVisibility.value })
    groups.value.unshift(data)
    filterGroup.value = data.id
    newGroupName.value = ''
    createGroupVisible.value = false
    ElMessage.success('分组已创建')
  } catch { /* 全局拦截器提示错误 */ }
}

const tagName = (id: string) => tags.value.find(tag => tag.id === id)?.name || id
const placementAdvice = (item: MediaItem) => {
  if (!item.width || !item.height) return ''
  const ratio = item.width / item.height
  if (ratio >= 0.9 && ratio <= 1.1) return '建议：Feed / 方图版位'
  if (ratio >= 0.52 && ratio <= 0.58) return '建议：Stories / Reels / 9:16'
  if (ratio >= 1.7 && ratio <= 2.0) return '建议：Feed 横版版位'
  return '建议：发布前确认版位裁剪'
}
const createTag = async () => {
  if (!newTagName.value.trim()) { ElMessage.warning('请输入标签名称'); return }
  try {
    const { data } = await mediaApi.tags.create({ name: newTagName.value.trim() })
    tags.value.push(data)
    newTagName.value = ''
    createTagVisible.value = false
    ElMessage.success('标签已创建')
  } catch { /* 全局拦截器提示错误 */ }
}

const openMembers = () => {
  memberGroupId.value = filterGroup.value || groups.value[0]?.id || ''
  membersVisible.value = true
  loadMembers()
}
const loadMembers = async () => {
  if (!memberGroupId.value) return
  membersLoading.value = true
  try { members.value = (await mediaApi.groups.members(memberGroupId.value)).data || [] } finally { membersLoading.value = false }
}
const addMember = async () => {
  if (!memberGroupId.value || !memberUserId.value.trim()) { ElMessage.warning('请选择分组并输入用户 ID'); return }
  try {
    await mediaApi.groups.upsertMember(memberGroupId.value, memberUserId.value.trim(), memberCanEdit.value)
    memberUserId.value = ''
    await loadMembers()
    ElMessage.success('成员已更新')
  } catch { /* 全局拦截器提示错误 */ }
}
const removeMember = async (userId: string) => {
  try { await mediaApi.groups.removeMember(memberGroupId.value, userId); await loadMembers(); ElMessage.success('成员已移除') } catch { /* 全局拦截器提示错误 */ }
}

const moveSelected = async () => {
  if (!moveTargetGroup.value) { ElMessage.warning('请选择目标分组'); return }
  try {
    await mediaApi.groups.moveAssets(selectedIds.value, moveTargetGroup.value)
    ElMessage.success('素材已移动')
    selectedIds.value = []
    moveTargetGroup.value = ''
    await load()
  } catch { /* 全局拦截器提示错误 */ }
}

const applyBatchTag = async () => {
  if (!batchTagId.value || !selectedIds.value.length) return
  try {
    await mediaApi.tags.setBatch(selectedIds.value, [batchTagId.value])
    const tagId = batchTagId.value
    list.value.forEach((item) => {
      if (selectedIds.value.includes(item.id)) item.tag_ids = [tagId]
    })
    selectedIds.value = []
    batchTagId.value = ''
    ElMessage.success('已为选中素材设置标签')
  } catch { /* 全局拦截器提示错误 */ }
}

const syncSelected = async () => {
  if (!selectedIds.value.length) return
  if (!accounts.value.length) { ElMessage.warning('暂无可用广告账户'); return }
  const readyIds = new Set(list.value.filter(item => selectedIds.value.includes(item.id) && isAssetReady(item)).map(item => item.id))
  if (!readyIds.size) { ElMessage.warning('选中的素材均未就绪，无法同步'); return }
  bulkSyncing.value = true
  try {
    await Promise.all(Array.from(readyIds).map(id => mediaApi.syncToAccounts(id, accounts.value.map(account => account.id))))
    ElMessage.success(`已提交 ${readyIds.size} 个素材的账户同步任务`)
    await load()
  } catch { /* 全局拦截器提示错误 */ }
  finally { bulkSyncing.value = false }
}

const syncAllAccounts = async (item: MediaItem) => {
  if (!accounts.value.length) { ElMessage.warning('暂无可用广告账户'); return }
  try {
    await mediaApi.syncToAccounts(item.id, accounts.value.map(account => account.id))
    ElMessage.success('已提交全部可见广告账户同步任务')
    await openBindings(item)
  } catch (e: any) {
    ElMessage.error(String(e?.response?.data?.detail || e?.message || '同步账户失败'))
  }
}

const refreshMetadata = async (item: MediaItem) => {
  try {
    const { data } = await mediaApi.refreshMetadata(item.id)
    if ('asset' in data) Object.assign(item, data.asset)
    if ('status' in data && data.status === 'PROCESSING') {
      ElMessage.success('已提交素材信息刷新任务')
      await waitForAsset(item.id)
      await load()
    } else {
      Object.assign(item, data)
      ElMessage.success('素材信息已刷新')
    }
  } catch { /* 全局拦截器提示错误 */ }
}

const remove = async (item: MediaItem) => {
  try {
    const { data } = await mediaApi.remove(item.id)
    ElMessage.success(data?.status === 'DELETING' ? '已提交删除任务' : '已删除')
    await load()
  } catch (e: any) {
    // 错误已由 utils/request.ts 全局拦截器弹框提示
  }
}

const refreshBindings = async () => { if (!bindingAssetId.value) return; const { data } = await mediaApi.bindings(bindingAssetId.value); bindings.value = data }
const reloadStats = async () => {
  if (!statsAsset.value) return
  statsLoading.value = true
  performanceStatsError.value = false
  try {
    const [start_date, end_date] = statsRange.value || []
    const params = { start_date, end_date }
    const [usageResponse] = await Promise.all([
      mediaApi.stats(statsAsset.value.id, params),
      mediaApi.performance({
        asset_id: statsAsset.value.id,
        start_date,
        end_date,
        include_archived: statsAsset.value.status === 'ARCHIVED' || undefined,
      }).then(({ data }) => {
        performanceStats.value = data
      }).catch(() => {
        performanceStats.value = null
        performanceStatsError.value = true
      }),
    ])
    usageStats.value = usageResponse.data
  } catch {
    ElMessage.error('素材统计加载失败')
  } finally {
    statsLoading.value = false
  }
}
const openStats = async (item: MediaItem) => {
  statsAsset.value = item
  statsRange.value = recentDateRange()
  usageStats.value = null
  performanceStats.value = null
  performanceStatsError.value = false
  versions.value = []
  statsVisible.value = true
  await Promise.all([reloadStats(), mediaApi.versions(item.id).then(({ data }) => { versions.value = data }).catch(() => { versions.value = [] })])
}
const setCurrentVersion = async (version: MediaItem) => {
  if (!statsAsset.value) return
  try {
    await mediaApi.setCurrentVersion(statsAsset.value.id, version.id)
    versions.value = versions.value.map(item => ({ ...item, is_current: item.id === version.id }))
    await load()
    ElMessage.success(`已将 V${version.version_number || 1} 设为当前版本`)
  } catch { /* 全局拦截器提示错误 */ }
}
const openBindings = async (item: MediaItem) => {
  bindingAssetId.value = item.id
  bindings.value = []
  bindingVisible.value = true
  bindingLoading.value = true
  try {
    await refreshBindings()
    if (bindingTimer !== null) window.clearInterval(bindingTimer)
    bindingTimer = window.setInterval(refreshBindings, 2000)
  } catch (e: any) {
    ElMessage.error(String(e?.response?.data?.detail || e?.message || '读取素材映射失败'))
  } finally { bindingLoading.value = false }
}
const retryBinding = async (row: any) => {
  try { await mediaApi.retryBinding(bindingAssetId.value, row.id); row.status = 'PENDING'; row.error_message = null; ElMessage.success('已提交素材重试任务') }
  catch (e: any) { ElMessage.error(String(e?.response?.data?.detail || e?.message || '提交重试失败')) }
}
const stopBindingPolling = () => { if (bindingTimer !== null) { window.clearInterval(bindingTimer); bindingTimer = null } }
const openFailure = (item: MediaItem) => { failureAsset.value = item; failureVisible.value = true }
onBeforeUnmount(() => {
  stopBindingPolling()
  stopAssetPolling()
})

const formatSize = (n?: number | null) => {
  if (!n) return '-'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}
const formatDuration = (seconds?: number | null) => {
  if (!seconds) return ''
  const total = Math.round(seconds)
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}
const formatUploadedAt = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}
const formatPercent = (value?: number | null) => value == null ? '—' : `${Number(value).toFixed(2)}%`
const formatRatio = (value?: number | null) => value == null ? '—' : Number(value).toFixed(2)
const formatMajorMoney = (value?: number | null, currency?: string | null) => {
  if (value == null) return '—'
  const noDecimal = ['JPY', 'KRW', 'VND'].includes(String(currency || '').toUpperCase())
  return `${currency || ''} ${Number(value).toFixed(noDecimal ? 0 : 2)}`.trim()
}

onMounted(async () => {
  restoreSavedView()
  try {
    const { data } = await accountApi.list({ page: 1, page_size: 100 })
    accounts.value = data || []
  } catch (e: any) {
    accounts.value = []
    ElMessage.error(String(e?.response?.data?.detail || e?.message || '广告账户加载失败，请先检查账户授权'))
  }
  try {
    const { data } = await mediaApi.groups.list()
    groups.value = data || []
  } catch {
    groups.value = []
  }
  try {
    const { data } = await mediaApi.tags.list()
    tags.value = data || []
  } catch {
    tags.value = []
  }
  await load()
})
</script>

<style scoped lang="scss">
.material { color: #1f2937; }
.retry-file-input { display: none; }
.library-shell { border: 0; border-radius: 16px; background: #fff; box-shadow: 0 8px 28px rgba(15, 35, 70, .06); }
.library-shell :deep(.el-card__header) { padding: 24px 28px 18px; border-bottom: 1px solid #edf1f7; }
.library-shell :deep(.el-card__body) { padding: 20px 28px 28px; }
.header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 24px;
  .title-block { min-width: 240px; }
  .eyebrow { color: #8a9ab0; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
  .page-title { margin: 5px 0 3px; color: #172b4d; font-size: 24px; line-height: 1.25; }
  .page-desc { margin: 0; color: #8492a6; font-size: 13px; }
  .header-actions { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; }
  .upload-account { width: 230px; }
}
.shared-hint { display: flex; align-items: center; gap: 7px; margin-top: 16px; color: #718096; font-size: 12px; }
.hint-dot { width: 7px; height: 7px; border-radius: 50%; background: #35b779; box-shadow: 0 0 0 4px #e8f7ef; }
.workspace-tabs { display: flex; gap: 4px; margin: 18px 0 12px; border-bottom: 1px solid #edf1f7; }
.workspace-tabs button { padding: 9px 16px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: #718096; cursor: pointer; font-size: 13px; }
.workspace-tabs button:hover, .workspace-tabs button.active { border-bottom-color: #409eff; color: #2f75c5; font-weight: 600; }
.workspace-context { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; padding: 12px 14px; border: 1px solid #e4ecf7; border-radius: 10px; background: #f8fbff; }
.context-label { margin-right: 8px; color: #52657f; font-size: 12px; }
.workspace-select { width: 245px; }
.visibility-tag { margin-left: 10px; }
.context-help { flex: 1; color: #8796a9; font-size: 12px; }
.upload-progress-panel { margin-top: 14px; padding: 12px 14px; border: 1px solid #dbeafe; border-radius: 10px; background: #f6faff; }
.upload-progress-head { display: flex; justify-content: space-between; margin-bottom: 7px; color: #486581; font-size: 12px; font-weight: 600; }
.upload-progress-panel small { display: block; margin-top: 7px; color: #8a9aad; font-size: 11px; }
.filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 14px 16px;
  margin-bottom: 18px;
  border: 1px solid #edf1f7;
  border-radius: 12px;
  background: #f8fafc;
  .filter-title { margin-right: 2px; color: #506176; font-size: 13px; font-weight: 600; }
  .filter-search { width: 235px; }
  .filter-status { width: 125px; }
  .filter-type { width: 110px; }
  .filter-account { width: 245px; }
  .filter-group { width: 170px; }
  .filter-tag { width: 150px; }
  .overview-picker { width: 250px; margin-left: auto; }
  .view-switch { margin-left: auto; }
}
.overview-section { margin-bottom: 20px; }
.overview-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.overview-item {
  padding: 16px 18px;
  border: 1px solid #edf1f7;
  border-radius: 12px;
  background: linear-gradient(135deg, #fff, #f8fbff);
  span, small { display: block; color: #8a98aa; font-size: 12px; }
  strong { display: block; margin: 8px 0 4px; color: #172b4d; font-size: 26px; line-height: 1; }
  em { color: #9aa8b9; font-size: 14px; font-style: normal; font-weight: 500; }
  &.highlight strong { color: #3678d4; }
  &.success strong { color: #16a36a; }
}
.overview-funnel { margin-top: 12px; padding: 14px 16px; border: 1px solid #edf1f7; border-radius: 12px; background: #fff; }
.funnel-title { color: #344b6a; font-size: 13px; font-weight: 600; }
.funnel-title span { margin-left: 8px; color: #97a4b5; font-size: 11px; font-weight: 400; }
.funnel-list { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; margin-top: 14px; }
.funnel-step { position: relative; min-width: 0; }
.funnel-label { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 7px; color: #718198; font-size: 12px; }
.funnel-label b { color: #29486e; font-size: 13px; }
.funnel-step small { display: block; margin-top: 5px; color: #91a0b3; font-size: 11px; text-align: right; }
.overview-top { overflow: hidden; margin-top: 12px; padding: 10px 14px; border-radius: 9px; background: #f5f8fc; color: #65758b; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.top-label { margin-right: 8px; color: #344b6a; font-weight: 600; }
.overview-performance { margin-top: 12px; padding: 12px 14px; border: 1px solid #e6eef9; border-radius: 10px; background: #fbfdff; }
.performance-title { margin-bottom: 8px; color: #344b6a; font-size: 13px; font-weight: 600; }
.performance-title span { margin-left: 8px; color: #97a4b5; font-size: 11px; font-weight: 400; }
.platform-empty { margin-top: 12px; padding: 13px 16px; border-radius: 9px; background: #f7f9fc; color: #8a98aa; font-size: 12px; }
.bulk-bar { display:flex; align-items:center; gap:10px; margin-bottom:12px; padding: 10px 14px; border: 1px solid #dbeafe; border-radius: 10px; background: #f5f9ff; color:#506176; font-size:13px; }
.asset-table { margin-top: 4px; }
.table-asset { display: flex; align-items: center; gap: 10px; min-width: 0; }
.table-asset img { width: 54px; height: 42px; border-radius: 6px; object-fit: cover; background: #eef3f9; }
.table-asset b, .table-asset small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.table-asset b { color: #203552; font-size: 13px; }
.table-asset small { margin-top: 4px; color: #94a1b2; font-size: 11px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 18px;
  align-items: stretch;
}
.card {
  position: relative;
  min-width: 0;
  border: 1px solid #e8edf4;
  border-radius: 14px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #fff;
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
  &:hover { border-color: #c8d9f5; box-shadow: 0 10px 24px rgba(31, 76, 135, .1); transform: translateY(-2px); }
  .thumb {
    position: relative;
    height: 180px;
    background: linear-gradient(135deg, #eef3f9, #dfe7f1);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    img, video { width: 100%; height: 100%; object-fit: cover; }
    .thumb-icon { font-size: 42px; color: #a9b7c8; }
    .thumb-overlay { position: absolute; right: 10px; bottom: 10px; left: 10px; display: flex; align-items: center; justify-content: space-between; color: #fff; font-size: 11px; opacity: 0; transition: opacity .2s ease; }
    &:hover .thumb-overlay { opacity: 1; }
    .thumb-overlay > span:first-child { padding: 3px 7px; border-radius: 5px; background: rgba(18, 38, 68, .72); }
    .preview-action { padding: 3px 7px; border-radius: 5px; background: rgba(18, 38, 68, .62); }
  }
  .asset-check { position:absolute; left:10px; top:10px; z-index:2; background:rgba(255,255,255,.92); padding:3px 5px; border-radius:6px; }
  .info { padding: 14px 15px 12px; flex: 1; }
  .name-row { display: flex; align-items: center; gap: 8px; }
  .ready-dot { flex: 0 0 auto; width: 7px; height: 7px; border-radius: 50%; background: #35b779; box-shadow: 0 0 0 3px #e8f7ef; }
  .ready-dot.failed { background: #e6a23c; box-shadow: 0 0 0 3px #fff4df; }
  .name { color: #203552; font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .uploader { margin-top: 6px; overflow: hidden; color: #94a1b2; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
  .asset-stats { display: flex; gap: 14px; margin-top: 10px; color: #75849a; font-size: 11px; }
  .asset-stats b { color: #3e5777; font-weight: 600; }
  .meta { margin-top: 10px; display: flex; align-items: center; gap: 8px; }
  .tags { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 4px; }
  .placement-tip { margin-top: 8px; color: #8292a6; font-size: 11px; line-height: 1.4; }
  .size { font-size: 11px; color: #93a0b1; }
  .status { margin-top: 10px; display: flex; align-items: center; gap: 8px; }
  .fb-ok { font-size: 11px; color: #2daa70; }
  .actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 2px; min-height: 42px; padding: 5px 10px; border-top: 1px solid #f0f3f7; background: #fbfcfe; }
}
.stats-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; color: #606266; font-size: 13px; }
.stats-section-title { margin: 18px 0 8px; color: #303133; font-size: 14px; font-weight: 600; }
.stats-section-note { margin-left: 7px; color: #97a4b5; font-size: 11px; font-weight: 400; }
.platform-data-note { margin-bottom: 8px; color: #8292a6; font-size: 11px; line-height: 1.5; }
.member-add { display:flex; align-items:center; gap:12px; margin-bottom:12px; }
.clickable { cursor: pointer; }
.error-detail { white-space: pre-wrap; word-break: break-word; margin: 0; font-family: inherit; color: #f56c6c; }
.preview-media { display: block; max-width: 100%; max-height: 68vh; margin: 0 auto; object-fit: contain; border-radius: 8px; }
@media (max-width: 1100px) {
  .header-bar { align-items: flex-start; flex-direction: column; }
  .header-actions { justify-content: flex-start; }
  .filters .overview-picker { margin-left: 0; }
  .overview-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .funnel-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 680px) {
  .library-shell :deep(.el-card__header), .library-shell :deep(.el-card__body) { padding-right: 16px; padding-left: 16px; }
  .header-actions, .header-actions .el-select, .header-actions .el-upload, .header-actions .el-button { width: 100%; }
  .header-actions .el-upload .el-button { width: 100%; }
  .filters > * { width: 100% !important; margin-left: 0 !important; }
  .overview-grid { grid-template-columns: 1fr 1fr; }
  .funnel-title span { display: block; margin: 5px 0 0; line-height: 1.4; }
  .funnel-list { grid-template-columns: 1fr; gap: 10px; }
  .grid { grid-template-columns: 1fr; }
}
</style>

# Connector 投放创建协议设计

## 1. 目标

国内 SaaS 只负责校验业务参数、创建本地 Job 和保存映射；海外 Connector 负责读取 FB 凭证并调用 Meta Graph API。一次请求描述一个广告账户下的完整投放树：

```text
Campaign
└── AdSet[]
    └── Creative[]
        └── Ad[]
```

接口采用异步模式，国内请求不等待 Meta 创建完成。

## 2. 创建接口

`POST /internal/meta/campaigns/deploy`

请求必须携带国内生成的 `task_id`、海外 `credential_id`、Meta 广告账户 ID 和 `idempotency_key`。请求签名覆盖完整 JSON body；Bearer Token 用于服务间认证。

### 请求示例

```json
{
  "task_id": "saas-job-item-001",
  "credential_id": "remote-credential-001",
  "account_id": "act_123456789",
  "idempotency_key": "deploy:template-001:account-001:v1",
  "campaign": {
    "name": "春季推广",
    "objective": "OUTCOME_TRAFFIC",
    "status": "PAUSED",
    "special_ad_categories": [],
    "is_adset_budget_sharing_enabled": false
  },
  "adsets": [
    {
      "client_key": "adset-1",
      "name": "美国受众",
      "status": "PAUSED",
      "daily_budget": 10000,
      "billing_event": "IMPRESSIONS",
      "optimization_goal": "LINK_CLICKS",
      "targeting": {"geo_locations": {"countries": ["US"]}},
      "creatives": [
        {
          "client_key": "creative-1",
          "name": "主图创意",
          "page_id": "123456789",
          "object_story_spec": {"page_id": "123456789", "link_data": {"message": "文案", "link": "https://example.com"}},
          "ads": [
            {"client_key": "ad-1", "name": "主图广告", "status": "PAUSED"}
          ]
        }
      ]
    }
  ]
}
```

`object_story_spec`、`asset_feed_spec`、`promoted_object`、轮播卡片等 Meta 参数原样放在对应节点，不由 Connector 猜测或补全业务含义。素材字段必须引用已存在的 Meta 资源 ID；素材上传另行处理。

## 3. 账户级 Custom Audience 元数据同步

国内管理员配置“法律/运营强制排除受众”前，先通过 Connector 同步指定广告账户可访问的受众元数据：

`POST /internal/meta/audiences/list`

```json
{
  "credential_id": "remote-credential-001",
  "account_id": "act_123456789"
}
```

响应仅包含 `id`、`name`、`subtype`、`delivery_status`、`sharing_status`、`time_updated` 等元数据；Connector 不读取、不缓存、不返回受众成员数据。国内服务按广告账户缓存这些资产，管理员只能从已同步且属于当前账户的 ID 中选择强制排除项。投放时强制排除项由国内服务合并进每个广告组的 `targeting.excluded_custom_audiences`，广告组模板不能覆盖或移除该策略。

强制排除策略由国内服务保存为账户级版本化策略。发布预检时生成不可变快照，并随部署请求传递：

```json
{
  "policy_snapshot": {
    "policy_version": 12,
    "hash": "sha256:...",
    "fail_closed": true,
    "required_excluded_audience_ids": ["238..."],
    "captured_at": "2026-09-22T10:00:00Z"
  }
}
```

Connector 只使用其中的受众 ID 合并最终 AdSet targeting，并原样回传应用结果；策略原因、备注和审批信息仅留在国内服务。相同任务重试必须使用相同快照；策略变更只影响新的发布任务。受众同步完整成功后未返回的资产标记为 `MISSING`，包含强制策略的账户在预检阶段 fail-closed。

## 4. 返回值

首次请求返回 `202 Accepted`：

```json
{
  "status": "QUEUED",
  "connector_task_id": "remote-task-001",
  "task_id": "saas-job-item-001",
  "idempotency_key": "deploy:template-001:account-001:v1"
}
```

重复使用同一幂等键必须返回原任务，不得再次创建 Meta 对象。

## 5. 状态查询

`GET /internal/meta/campaigns/deploy/{connector_task_id}`

状态统一为：

```text
QUEUED → RUNNING → CAMPAIGN_CREATED → ADSETS_CREATED
       → CREATIVES_CREATED → ADS_CREATED → SUCCEEDED
```

失败状态：`FAILED`。返回结构：

```json
{
  "status": "SUCCEEDED",
  "step": "ADS_CREATED",
  "connector_task_id": "remote-task-001",
  "objects": {
    "campaign_id": "cmp_1",
    "adsets": [{"client_key": "adset-1", "id": "set_1"}],
    "creatives": [{"client_key": "creative-1", "id": "creative_1"}],
    "ads": [{"client_key": "ad-1", "id": "ad_1"}]
  },
  "error": null
}
```

失败时返回 `failed_step`、`error_code`、`retryable` 和脱敏后的 `error_message`，不得返回 Access Token 或请求签名。

## 6. 回调接口

海外任务状态通过 HMAC 回调国内，终态回调后国内会立即触发统一收敛；国内原有状态轮询保留为降级兜底：

- `POST {SAAS_CALLBACK_BASE_URL}/api/v1/internal/fb-connector/delivery-status`
- `POST {SAAS_CALLBACK_BASE_URL}/api/v1/internal/fb-connector/media-status`

回调携带 `X-Request-Id`、`X-Timestamp`、`X-Signature`、`X-Idempotency-Key`。签名覆盖 HTTP 方法、路径、时间戳、原始 body 摘要和幂等键。国内按 Connector task ID 更新对应投放子项或账户级素材绑定；未知任务返回 200 并记录告警，避免历史任务清理后触发无限重试。回调事件先写入 Connector 的 `connector_callback_events` outbox，失败按指数退避重试；回调失败不影响海外 Meta 执行，轮询和 Beat 恢复任务负责兜底。

## 7. 国内映射

Connector 返回的 Meta ID 映射到本地：

| Connector 对象 | 国内对象 |
|---|---|
| `campaign_id` | `CampaignInstance.meta_campaign_id` |
| `adsets[].id` | `AdSetInstance.meta_adset_id` |
| `creatives[].id` | `CreativeAsset` / 创意映射 |
| `ads[].id` | `AdInstance.meta_ad_id` |

本地保存 `connector_credential_id`，不得把海外 Token 写入国内 `Credential` 表。

## 8. 失败与补偿

- 参数校验、权限不足、Meta 对象不存在：`retryable=false`，任务终止。
- 网络超时、Meta 429、5xx：`retryable=true`，按步骤重试。
- 已创建对象再次重试：使用 `client_key` 和幂等键查询/复用，禁止重复创建。
- 后续节点失败：保留已创建对象 ID，状态为 `FAILED`，由补偿任务按策略清理或人工处理。
- 国内回调失败不影响海外任务最终状态，Connector 通过 outbox 和 Beat 按指数退避重试回调。

## 9. Builder 改造约束

后续 `CampaignDeploymentBuilder` 只负责生成协议 payload 和解析结果，不直接调用 Meta API。新增 Connector Builder 适配层，direct 模式继续使用现有四个 Builder。两种模式最终都必须产出相同的本地实例映射。

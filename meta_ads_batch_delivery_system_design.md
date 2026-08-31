# Meta Ads 批量投流系统技术设计方案

> 版本：V1.0\
> 日期：2026-08-29\
> 技术方向：Python + FastAPI + PostgreSQL + Redis + Celery + Meta
> Marketing API + `facebook-business-sdk`

------------------------------------------------------------------------

## 1. 项目概述

本系统面向多 Business Manager（BM）和多广告账户的 Meta Ads
批量投放场景。

基本业务结构：

``` text
N 个 BM 主账号
    │
    ├── 广告账户 01
    ├── 广告账户 02
    ├── 广告账户 03
    └── ...
```

系统的核心目标不是简单地批量调用 Meta API，而是建立：

-   账号统一管理
-   投放模板化
-   批量创建 Campaign / Ad Set / Ad
-   批量启停
-   批量调整预算
-   异步任务队列
-   限流与重试
-   投放状态同步
-   数据报表
-   后续自动化投放策略

最终形成：

``` text
投放模板
    ↓
选择 BM / 广告账户
    ↓
生成批量投放任务
    ↓
任务队列
    ↓
Meta API Worker
    ↓
Campaign / AdSet / Ad
    ↓
数据同步
    ↓
报表 / 策略引擎
```

------------------------------------------------------------------------

# 2. 产品目标

## 2.1 核心目标

用户尽可能少设置参数，即可将一个投放方案批量部署到多个广告账户。

例如用户只需要配置：

``` json
{
  "name": "产品A-US-Sales",
  "objective": "OUTCOME_SALES",
  "daily_budget": 100,
  "countries": ["US"],
  "page_id": "xxx",
  "pixel_id": "xxx",
  "creative_ids": [
    "creative_01",
    "creative_02"
  ]
}
```

系统自动完成：

``` text
Campaign
    │
    ├── AdSet 01
    │      ├── Ad 01
    │      └── Ad 02
    │
    └── AdSet 02
           ├── Ad 03
           └── Ad 04
```

然后部署到：

``` text
BM-A
 ├── Account 001
 ├── Account 002
 ├── Account 003
 └── Account 004

BM-B
 ├── Account 005
 └── Account 006
```

------------------------------------------------------------------------

# 3. 核心设计思想

## 3.1 不以"BM × 广告账户"作为核心抽象

系统最重要的业务抽象应该是：

> 一个 Campaign Template 如何被部署到多个 Ad Account。

模型：

``` text
                    Campaign Template
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          Account A    Account B    Account C
              │            │            │
              ▼            ▼            ▼
          Campaign      Campaign      Campaign
              │            │            │
            AdSet         AdSet         AdSet
              │            │            │
             Ads          Ads           Ads
```

这样无论规模是：

``` text
2 个 BM
20 个广告账户
```

还是：

``` text
100 个 BM
5000 个广告账户
```

核心业务模型都不需要改变。

------------------------------------------------------------------------

# 4. 总体系统架构

``` text
                         ┌─────────────────────┐
                         │     管理后台 Web     │
                         │                     │
                         │  BM/广告账户管理      │
                         │  投放模板             │
                         │  批量投放             │
                         │  Job Center          │
                         │  数据报表             │
                         └──────────┬──────────┘
                                    │
                              REST / API
                                    │
                         ┌──────────▼──────────┐
                         │       FastAPI        │
                         │     API Gateway      │
                         └──────────┬──────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
   │ PostgreSQL   │         │    Redis     │         │ Meta Service │
   │              │         │              │         │              │
   │ 业务数据      │         │ Queue/Cache  │         │ Business SDK │
   └──────────────┘         └──────┬───────┘         └──────┬───────┘
                                    │                         │
                                    ▼                         ▼
                              ┌───────────┐              Meta API
                              │  Celery   │
                              │  Workers  │
                              └─────┬─────┘
                                    │
                           ┌────────┼────────┐
                           ▼        ▼        ▼
                        Worker    Worker    Worker
```

------------------------------------------------------------------------

# 5. 推荐技术栈

  层级             技术
  ---------------- -----------------------------
  后端 API         Python + FastAPI
  ORM              SQLAlchemy
  数据库           PostgreSQL
  Schema           Pydantic
  队列             Celery
  Cache / Broker   Redis
  Meta SDK         `facebook-business-sdk`
  定时任务         Celery Beat
  前端             Next.js / React
  日志             Python logging / structlog
  容器             Docker
  部署             Docker Compose / Kubernetes
  监控             Prometheus + Grafana，可选
  错误追踪         Sentry，可选

------------------------------------------------------------------------

# 6. 核心业务模块

系统建议拆成以下模块：

``` text
1. Organization
2. BM Management
3. Ad Account Management
4. Credential Management
5. Campaign Template
6. Creative Management
7. Campaign Builder
8. Batch Job
9. Meta API Service
10. Rate Limiter
11. Sync Service
12. Insights
13. Rule Engine
14. Audit Log
```

------------------------------------------------------------------------

# 7. BM 主账号管理

## 7.1 bm_accounts

建议数据库表：

``` sql
CREATE TABLE bm_accounts (
    id BIGSERIAL PRIMARY KEY,
    business_id VARCHAR(64) NOT NULL UNIQUE,
    business_name VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

核心字段：

  字段              说明
  ----------------- ---------------------------
  `id`              系统内部 ID
  `business_id`     Meta Business ID
  `business_name`   BM 名称
  `status`          ACTIVE / DISABLED / ERROR
  `created_at`      创建时间
  `updated_at`      更新时间

------------------------------------------------------------------------

# 8. 广告账户管理

## 8.1 ad_accounts

``` sql
CREATE TABLE ad_accounts (
    id BIGSERIAL PRIMARY KEY,
    bm_id BIGINT NOT NULL REFERENCES bm_accounts(id),
    ad_account_id VARCHAR(64) NOT NULL UNIQUE,
    account_name VARCHAR(255),
    currency VARCHAR(16),
    timezone VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    spend_cap NUMERIC(18, 2),
    balance NUMERIC(18, 2),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

关系：

``` text
BM A
 ├── act_111
 ├── act_112
 ├── act_113
 └── act_114

BM B
 ├── act_211
 ├── act_212
 └── act_213
```

------------------------------------------------------------------------

# 9. Token / Credential 管理

不要把 Access Token 直接存放在广告账户表中。

推荐：

``` text
Credential
    │
    └── BM
          ├── Ad Account
          ├── Ad Account
          └── Ad Account
```

## 9.1 credentials

``` sql
CREATE TABLE credentials (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT REFERENCES bm_accounts(id),
    access_token_encrypted TEXT NOT NULL,
    token_type VARCHAR(32),
    expires_at TIMESTAMP,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

要求：

-   Access Token 加密存储
-   不在前端暴露 Token
-   不将 Token 写入 Git
-   不将 Token 写入普通日志
-   支持 Token 过期检测
-   支持权限异常标记
-   支持 Token 更换

推荐使用：

``` text
环境变量
Secret Manager
KMS
Vault
```

生产环境不要硬编码：

``` python
ACCESS_TOKEN = "xxxx"
```

------------------------------------------------------------------------

# 10. Campaign Template

Campaign Template 是整个系统最核心的业务对象。

用户配置一次：

``` text
US Sales V1
```

系统即可批量部署到多个广告账户。

## 10.1 campaign_templates

``` sql
CREATE TABLE campaign_templates (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,

    objective VARCHAR(64),
    buying_type VARCHAR(64),
    special_ad_categories JSONB,

    budget_type VARCHAR(32),
    daily_budget NUMERIC(18, 2),
    lifetime_budget NUMERIC(18, 2),

    bid_strategy VARCHAR(64),
    optimization_goal VARCHAR(64),
    billing_event VARCHAR(64),

    targeting_json JSONB,
    placement_json JSONB,
    creative_config_json JSONB,

    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',

    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

建议将 Meta 经常变化的参数放到 JSONB：

``` text
targeting_json
placement_json
creative_config_json
```

优点：

-   Meta API 参数变化时更容易兼容
-   不需要频繁修改数据库结构
-   可以保存完整模板
-   支持不同类型 Campaign

------------------------------------------------------------------------

# 11. Creative 管理

可以建立统一的素材模型：

``` sql
CREATE TABLE creatives (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255),
    creative_type VARCHAR(32),
    image_url TEXT,
    video_url TEXT,
    thumbnail_url TEXT,
    primary_text TEXT,
    headline TEXT,
    description TEXT,
    call_to_action VARCHAR(64),
    landing_url TEXT,
    status VARCHAR(32) DEFAULT 'ACTIVE',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

如果未来素材需要跨账户复制，需要保存：

``` text
系统 Creative
        │
        ├── Account A → Meta Creative ID
        ├── Account B → Meta Creative ID
        └── Account C → Meta Creative ID
```

------------------------------------------------------------------------

# 12. Campaign 实例映射

Template 和 Meta Campaign 之间必须建立映射。

例如：

``` text
Template Campaign
        │
        ├── Account A → Campaign 111
        ├── Account B → Campaign 222
        └── Account C → Campaign 333
```

## 12.1 campaign_instances

``` sql
CREATE TABLE campaign_instances (
    id BIGSERIAL PRIMARY KEY,
    template_id BIGINT NOT NULL REFERENCES campaign_templates(id),
    ad_account_id BIGINT NOT NULL REFERENCES ad_accounts(id),

    meta_campaign_id VARCHAR(128),
    name VARCHAR(255),

    status VARCHAR(32),
    meta_status VARCHAR(32),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(template_id, ad_account_id)
);
```

------------------------------------------------------------------------

# 13. AdSet 实例

``` sql
CREATE TABLE adset_instances (
    id BIGSERIAL PRIMARY KEY,

    campaign_instance_id BIGINT NOT NULL
        REFERENCES campaign_instances(id),

    meta_adset_id VARCHAR(128),

    name VARCHAR(255),
    status VARCHAR(32),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

------------------------------------------------------------------------

# 14. Ad 实例

``` sql
CREATE TABLE ad_instances (
    id BIGSERIAL PRIMARY KEY,

    adset_instance_id BIGINT NOT NULL
        REFERENCES adset_instances(id),

    creative_id BIGINT REFERENCES creatives(id),

    meta_ad_id VARCHAR(128),

    name VARCHAR(255),
    status VARCHAR(32),

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

------------------------------------------------------------------------

# 15. 批量投放流程

用户操作：

``` text
选择模板
    ↓
选择 BM
    ↓
选择广告账户
    ↓
选择素材
    ↓
设置预算
    ↓
预览
    ↓
提交批量投放
```

例如：

``` text
模板：
US Sales V1

BM-A
 ☑ Account 001
 ☑ Account 002
 ☑ Account 003

BM-B
 ☑ Account 005
 ☑ Account 006

预算：
$100 / day
```

点击：

``` text
批量创建
```

系统创建：

``` text
5 个广告账户
×
1 Campaign
×
2 AdSet
×
3 Ads

= 30 Ads
```

------------------------------------------------------------------------

# 16. 不建议直接循环调用 API

不推荐：

``` python
for account in accounts:
    create_campaign(account)
    create_adset(account)
    create_ad(account)
```

原因：

-   API 限流
-   网络超时
-   Token 失效
-   单个账户失败
-   部分成功
-   重复创建
-   无法恢复任务

正确设计：

``` text
Batch Campaign Job
        │
        ├── Account 001
        ├── Account 002
        ├── Account 003
        └── Account N
              │
              ▼
            Queue
              │
       ┌──────┼──────┐
       ▼      ▼      ▼
    Worker  Worker  Worker
```

------------------------------------------------------------------------

# 17. Job Center

## 17.1 campaign_jobs

``` sql
CREATE TABLE campaign_jobs (
    id BIGSERIAL PRIMARY KEY,

    template_id BIGINT NOT NULL
        REFERENCES campaign_templates(id),

    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',

    total_accounts INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,

    created_by BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
```

## 17.2 campaign_job_items

``` sql
CREATE TABLE campaign_job_items (
    id BIGSERIAL PRIMARY KEY,

    job_id BIGINT NOT NULL
        REFERENCES campaign_jobs(id),

    ad_account_id BIGINT NOT NULL
        REFERENCES ad_accounts(id),

    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',

    campaign_id VARCHAR(128),
    adset_ids JSONB,
    ad_ids JSONB,

    request_payload JSONB,
    response_payload JSONB,

    error_code VARCHAR(128),
    error_message TEXT,

    retry_count INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

------------------------------------------------------------------------

# 18. Job 状态机

推荐：

``` text
PENDING
   │
   ▼
VALIDATING
   │
   ▼
QUEUED
   │
   ▼
RUNNING
   │
   ├──────────────┐
   ▼              ▼
SUCCESS       PARTIAL_SUCCESS
                  │
                  ▼
                FAILED
                  │
                  ▼
                RETRY
```

完整状态：

``` text
PENDING
VALIDATING
QUEUED
RUNNING
PARTIAL_SUCCESS
SUCCESS
FAILED
CANCELLED
```

------------------------------------------------------------------------

# 19. Meta API Service

不要让业务代码直接调用 `facebook_business`。

应该增加封装层：

``` text
Application
      │
      ▼
MetaAdsService
      │
      ▼
facebook_business
      │
      ▼
Meta Marketing API
```

推荐接口：

``` python
class MetaAdsService:

    def create_campaign(self, account_id, params):
        ...

    def create_adset(self, account_id, campaign_id, params):
        ...

    def create_creative(self, account_id, params):
        ...

    def create_ad(self, account_id, adset_id, params):
        ...

    def update_budget(self, adset_id, budget):
        ...

    def pause_campaign(self, campaign_id):
        ...

    def enable_campaign(self, campaign_id):
        ...

    def get_insights(self, account_id, params):
        ...
```

------------------------------------------------------------------------

# 20. Meta SDK 初始化

使用官方 Python Business SDK：

``` python
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount

FacebookAdsApi.init(
    app_id,
    app_secret,
    access_token
)

account = AdAccount("act_<ACCOUNT_ID>")

campaigns = account.get_campaigns()
```

建议进一步封装：

``` python
class MetaClient:

    def __init__(
        self,
        app_id,
        app_secret,
        access_token
    ):
        self.api = FacebookAdsApi.init(
            app_id=app_id,
            app_secret=app_secret,
            access_token=access_token
        )

    def account(self, account_id):
        return AdAccount(
            f"act_{account_id}"
        )
```

调用：

``` python
client = MetaClient(
    app_id,
    app_secret,
    token
)

account = client.account("123456")
```

------------------------------------------------------------------------

# 21. Campaign Builder

建议将 Campaign / AdSet / Creative / Ad 创建逻辑拆开。

``` text
CampaignBuilder
      │
      ├── CampaignBuilder
      ├── AdSetBuilder
      ├── CreativeBuilder
      └── AdBuilder
```

例如：

``` python
campaign = CampaignBuilder(
    account=account,
    template=template
).build()

adsets = AdSetBuilder(
    campaign=campaign,
    template=template
).build()

ads = AdBuilder(
    adsets=adsets,
    creatives=creatives
).build()
```

------------------------------------------------------------------------

# 22. 批量预算修改

例如：

``` text
Template: US-SALES-V1

Account 01
Campaign 111
Budget 100

Account 02
Campaign 222
Budget 100

Account 03
Campaign 333
Budget 100
```

用户输入：

``` text
150
```

系统找到：

``` sql
SELECT *
FROM campaign_instances
WHERE template_id = 100
AND status = 'ACTIVE';
```

然后产生：

``` text
UPDATE_BUDGET

111 → 150
222 → 150
333 → 150
```

所有操作进入 Queue。

------------------------------------------------------------------------

# 23. 批量操作 Action

统一抽象：

``` python
class ActionType:

    CREATE = "CREATE"
    PAUSE = "PAUSE"
    ENABLE = "ENABLE"
    UPDATE_BUDGET = "UPDATE_BUDGET"
    UPDATE_TARGETING = "UPDATE_TARGETING"
    SYNC = "SYNC"
```

未来可以继续增加：

``` text
DUPLICATE
ARCHIVE
UPDATE_BID
UPDATE_PLACEMENT
UPDATE_CREATIVE
```

------------------------------------------------------------------------

# 24. Redis + Celery 架构

正式生产环境推荐：

``` text
FastAPI
   │
   ├── PostgreSQL
   │
   └── Redis
          │
          ▼
        Celery
          │
     ┌────┼────┐
     ▼    ▼    ▼
 Worker Worker Worker
```

Celery 负责：

-   批量创建
-   批量修改预算
-   批量暂停
-   批量启用
-   定时同步
-   Insights 拉取
-   自动规则执行

------------------------------------------------------------------------

# 25. Rate Limiter

Meta API 调用需要考虑限流。

不要：

``` text
1000 accounts
     ↓
1000 requests
     ↓
同时发送
```

应该：

``` text
                    Queue
                      │
             ┌────────┼────────┐
             ▼        ▼        ▼
          Worker    Worker    Worker
             │        │        │
             └────────┼────────┘
                      ▼
                  RateLimiter
                      │
                      ▼
                   Meta API
```

建议控制：

-   Worker 并发
-   每账户请求频率
-   每 BM 请求频率
-   全局请求频率
-   错误重试速度

------------------------------------------------------------------------

# 26. Meta Batch Calling

Meta Python Business SDK 支持 Batch Calling。

Batch 的作用是将多个调用组合到一个 HTTP 请求中，以减少网络开销。

但需要注意：

> Batch 并不等于绕过 Meta API 的 Rate Limit。

因此系统仍然需要：

``` text
Queue
+
Rate Limiter
+
Retry
+
Backoff
```

------------------------------------------------------------------------

# 27. 错误分类

不要简单：

``` python
except Exception:
    print("error")
```

建议分类：

``` text
Meta API Error
│
├── AUTH
│   └── Token expired
│
├── PERMISSION
│   └── Permission denied
│
├── VALIDATION
│   └── Invalid parameter
│
├── RATE_LIMIT
│   └── Rate limit
│
├── TEMPORARY
│   └── Timeout / 5xx
│
└── UNKNOWN
```

处理策略：

``` text
RATE_LIMIT
    ↓
延迟 + Retry

TIMEOUT
    ↓
Retry

5xx
    ↓
Retry

INVALID_PARAMETER
    ↓
直接失败

PERMISSION
    ↓
账户标记异常
```

------------------------------------------------------------------------

# 28. Retry 策略

推荐 Exponential Backoff：

``` text
第一次：2 秒
第二次：4 秒
第三次：8 秒
第四次：16 秒
```

同时设置：

``` text
max_retry = 3 ~ 5
```

对于确定性的参数错误，不进行无限重试。

------------------------------------------------------------------------

# 29. Idempotency

批量系统必须支持幂等。

典型问题：

``` text
创建 Campaign
     ↓
Meta 创建成功
     ↓
服务器超时
     ↓
系统认为失败
     ↓
重新执行
     ↓
重复创建 Campaign
```

结果：

``` text
Campaign A
Campaign B
```

因此每一个 Job Item 都应该有：

``` text
template_id
account_id
operation
request_hash
meta_object_id
status
```

创建前检查：

``` python
existing = find_existing_operation(
    template_id,
    account_id,
    request_hash
)

if existing:
    return existing
```

建议数据库建立唯一约束或唯一业务 Key。

------------------------------------------------------------------------

# 30. 部分成功处理

假设：

``` text
100 个广告账户

成功：93
失败：7
```

不能把整个 Job 直接标记为失败。

应该：

``` text
Job #10231

总计：100
成功：93
失败：7
```

失败列表：

``` text
act_xxx
Token expired

act_xxx
Invalid parameter

act_xxx
Permission denied
```

用户可以：

``` text
重新执行失败任务
```

而不是重新执行全部 100 个账户。

------------------------------------------------------------------------

# 31. 数据同步

不要每次用户打开后台都直接请求 Meta API。

推荐：

``` text
Meta API
   │
   ▼
Sync Worker
   │
   ▼
PostgreSQL
   │
   ▼
Dashboard
```

定时任务：

``` text
sync_accounts
sync_campaigns
sync_adsets
sync_ads
sync_insights
```

例如每 15 分钟同步一次。

具体频率应根据业务规模、数据时效要求及 Meta API 限制进行调整。

------------------------------------------------------------------------

# 32. Insights 数据表

建议：

``` sql
CREATE TABLE ad_insights (
    id BIGSERIAL PRIMARY KEY,

    ad_account_id BIGINT,
    campaign_id VARCHAR(128),
    adset_id VARCHAR(128),
    ad_id VARCHAR(128),

    date_start DATE,
    date_stop DATE,

    spend NUMERIC(18, 4),
    impressions BIGINT,
    reach BIGINT,
    clicks BIGINT,

    ctr NUMERIC(18, 6),
    cpc NUMERIC(18, 6),
    cpm NUMERIC(18, 6),

    conversions NUMERIC(18, 4),
    conversion_value NUMERIC(18, 4),

    created_at TIMESTAMP DEFAULT NOW()
);
```

建议根据查询规模建立：

``` text
account_daily_insights
campaign_daily_insights
adset_daily_insights
ad_daily_insights
```

进行日级聚合。

------------------------------------------------------------------------

# 33. 报表

后台可以显示：

``` text
账户       Spend     Purchase     CPA     ROAS
------------------------------------------------
001        $1,203       42        $28.6   2.31
002        $980         39        $25.1   2.62
003        $1,500       31        $48.3   1.72
```

支持维度：

``` text
BM
Ad Account
Campaign
AdSet
Ad
Creative
Date
Country
```

支持指标：

``` text
Spend
Impressions
Reach
Clicks
CTR
CPC
CPM
Conversions
Conversion Value
CPA
ROAS
```

------------------------------------------------------------------------

# 34. 投放策略引擎

第二阶段可以增加 Strategy Engine。

架构：

``` text
数据
 ↓
Strategy Engine
 ↓
Rules Engine
 ↓
Action
 ↓
Task Queue
 ↓
Meta API
```

例如规则：

``` text
如果：

Spend > $50
AND CPA > $30

那么：

Pause Ad
```

或者：

``` text
如果：

ROAS > 3
AND Spend > $100

那么：

Budget × 1.2
```

------------------------------------------------------------------------

# 35. Strategy Rule 数据模型

``` sql
CREATE TABLE strategy_rules (
    id BIGSERIAL PRIMARY KEY,

    name VARCHAR(255),

    scope VARCHAR(32),

    conditions JSONB,
    actions JSONB,

    enabled BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

例如：

``` json
{
  "conditions": [
    {
      "metric": "CPA",
      "operator": ">",
      "value": 30
    },
    {
      "metric": "SPEND",
      "operator": ">",
      "value": 50
    }
  ],
  "actions": [
    {
      "type": "PAUSE_AD"
    }
  ]
}
```

------------------------------------------------------------------------

# 36. 后台页面设计

## 36.1 BM 管理

``` text
BM 管理

BM-A        账号：8      正常：7     异常：1
BM-B        账号：15     正常：14    异常：1
BM-C        账号：20     正常：20
```

点击 BM：

``` text
广告账户

☑ act_001    ACTIVE
☑ act_002    ACTIVE
☑ act_003    DISABLED
☑ act_004    ACTIVE
```

------------------------------------------------------------------------

## 36.2 投放模板

``` text
投放模板

US Sales V1
目标：Sales
预算：$100/day
国家：US
素材：3
状态：ACTIVE

[编辑] [复制] [批量投放]
```

------------------------------------------------------------------------

## 36.3 批量投放

``` text
选择模板：

[US Sales V1]

选择账户：

BM-A
 ☑ 001
 ☑ 002
 ☑ 003

BM-B
 ☑ 005
 ☑ 006

预算：

$100 / day

投放状态：

○ Paused
○ Active

             [预览]
```

------------------------------------------------------------------------

## 36.4 Job Center

``` text
批量任务

#10001
US Sales V1
100 Accounts

████████████░░░ 82%

成功 78
失败 2
执行中 20
```

------------------------------------------------------------------------

## 36.5 数据报表

``` text
账户       Spend     Purchase     CPA     ROAS
------------------------------------------------
001        $1,203       42        $28.6   2.31
002        $980         39        $25.1   2.62
003        $1,500       31        $48.3   1.72
```

------------------------------------------------------------------------

# 37. API 设计

推荐 FastAPI 路由：

``` text
/api/v1/auth
/api/v1/bms
/api/v1/ad-accounts
/api/v1/credentials
/api/v1/templates
/api/v1/creatives
/api/v1/campaigns
/api/v1/jobs
/api/v1/insights
/api/v1/strategies
```

## 37.1 BM

``` http
GET    /api/v1/bms
POST   /api/v1/bms
GET    /api/v1/bms/{id}
PATCH  /api/v1/bms/{id}
DELETE /api/v1/bms/{id}
```

## 37.2 广告账户

``` http
GET    /api/v1/ad-accounts
POST   /api/v1/ad-accounts/sync
GET    /api/v1/ad-accounts/{id}
PATCH  /api/v1/ad-accounts/{id}
```

## 37.3 模板

``` http
GET    /api/v1/templates
POST   /api/v1/templates
GET    /api/v1/templates/{id}
PATCH  /api/v1/templates/{id}
POST   /api/v1/templates/{id}/clone
```

## 37.4 批量投放

``` http
POST /api/v1/jobs/campaign-create
GET  /api/v1/jobs
GET  /api/v1/jobs/{id}
POST /api/v1/jobs/{id}/retry
POST /api/v1/jobs/{id}/cancel
```

## 37.5 批量预算

``` http
POST /api/v1/jobs/budget-update
```

## 37.6 批量启停

``` http
POST /api/v1/jobs/pause
POST /api/v1/jobs/enable
```

------------------------------------------------------------------------

# 38. 批量创建 API 示例

请求：

``` json
{
  "template_id": 1001,
  "ad_account_ids": [
    1,
    2,
    3,
    4
  ],
  "budget_override": 100,
  "status": "PAUSED"
}
```

响应：

``` json
{
  "job_id": 10231,
  "status": "QUEUED",
  "total_accounts": 4
}
```

前端随后轮询：

``` http
GET /api/v1/jobs/10231
```

------------------------------------------------------------------------

# 39. Celery Task 设计

例如：

``` python
@celery_app.task(
    bind=True,
    autoretry_for=(TemporaryMetaError,),
    retry_backoff=True,
    max_retries=3
)
def create_campaign_for_account(
    self,
    job_item_id
):
    job_item = load_job_item(job_item_id)

    validate_account(job_item)

    client = get_meta_client(
        job_item.ad_account_id
    )

    campaign = create_campaign(
        client,
        job_item
    )

    save_campaign_instance(
        job_item,
        campaign
    )
```

------------------------------------------------------------------------

# 40. 推荐项目目录

``` text
meta-ads-platform/

├── app/
│
│   ├── main.py
│
│   ├── api/
│   │   ├── auth.py
│   │   ├── bm.py
│   │   ├── accounts.py
│   │   ├── campaigns.py
│   │   ├── templates.py
│   │   ├── jobs.py
│   │   └── reports.py
│
│   ├── models/
│   │   ├── user.py
│   │   ├── business.py
│   │   ├── ad_account.py
│   │   ├── credential.py
│   │   ├── template.py
│   │   ├── creative.py
│   │   ├── campaign.py
│   │   ├── adset.py
│   │   ├── ad.py
│   │   └── job.py
│
│   ├── schemas/
│   │   ├── template.py
│   │   ├── campaign.py
│   │   └── job.py
│
│   ├── services/
│   │   ├── meta/
│   │   │   ├── client.py
│   │   │   ├── campaign.py
│   │   │   ├── adset.py
│   │   │   ├── creative.py
│   │   │   ├── ad.py
│   │   │   └── insights.py
│   │   │
│   │   ├── campaign_builder.py
│   │   ├── template_service.py
│   │   └── account_service.py
│
│   ├── workers/
│   │   ├── celery_app.py
│   │   ├── campaign_tasks.py
│   │   ├── sync_tasks.py
│   │   └── budget_tasks.py
│
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── rate_limit.py
│   │   └── logging.py
│
│   └── utils/
│
├── migrations/
├── tests/
├── docker/
│
├── docker-compose.yml
├── requirements.txt
└── README.md
```

------------------------------------------------------------------------

# 41. 安全设计

系统必须遵守 Meta 平台的授权、权限和 API 使用要求。

安全重点：

## 41.1 Token

``` text
Frontend
    ↓
FastAPI
    ↓
Encrypted Credential
    ↓
Meta Service
```

不要：

``` text
Frontend
    ↓
Meta Access Token
```

## 41.2 权限隔离

用户只能看到自己有权限管理的：

``` text
Organization
 ├── BM
 │    ├── Account
 │    └── Account
 └── Templates
```

## 41.3 Audit Log

建议增加：

``` sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT,
    action VARCHAR(64),
    resource_type VARCHAR(64),
    resource_id VARCHAR(128),

    request_data JSONB,
    response_data JSONB,

    ip_address VARCHAR(64),

    created_at TIMESTAMP DEFAULT NOW()
);
```

记录：

``` text
谁
什么时候
对哪个账户
做了什么
原参数
新参数
执行结果
```

------------------------------------------------------------------------

# 42. 生产环境部署

推荐 Docker：

``` text
docker-compose.yml

services:

  api:
    FastAPI

  worker:
    Celery Worker

  beat:
    Celery Beat

  redis:
    Redis

  postgres:
    PostgreSQL

  frontend:
    Next.js
```

结构：

``` text
                   Nginx / Load Balancer
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
             Next.js                 FastAPI
                                        │
                         ┌──────────────┼──────────────┐
                         ▼              ▼              ▼
                     PostgreSQL       Redis         Meta API
                                        │
                                        ▼
                                    Celery
                                        │
                                ┌───────┼───────┐
                                ▼       ▼       ▼
                              Worker  Worker  Worker
```

------------------------------------------------------------------------

# 43. 监控

生产环境建议监控：

``` text
API QPS
API Latency
Celery Queue Length
Worker CPU
Worker Memory
Meta API Error Rate
Meta Rate Limit
Job Success Rate
Job Failure Rate
Token Expiration
Sync Delay
```

核心指标：

``` text
batch_job_success_rate
batch_job_failure_rate
meta_api_error_rate
meta_api_rate_limit_rate
average_job_duration
queue_wait_time
```

------------------------------------------------------------------------

# 44. MVP 第一阶段

第一期不要做太大。

建议只做：

``` text
1. BM / Ad Account 管理

2. Token / 权限管理

3. Campaign Template

4. 批量创建
   ├── Campaign
   ├── AdSet
   ├── Creative
   └── Ad

5. 批量 Pause / Enable

6. 批量 Budget 修改

7. Job Center
   ├── 状态
   ├── 成功
   ├── 失败
   └── Retry
```

------------------------------------------------------------------------

# 45. 第二阶段

增加：

``` text
8. Insights

9. Dashboard

10. 素材管理

11. 数据同步

12. A/B Test

13. 自动规则

14. 自动关停
```

------------------------------------------------------------------------

# 46. 第三阶段

建设 Strategy Engine：

``` text
                    Strategy Engine
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
           Budget         Pause        Scale
            Rule           Rule         Rule
              │            │            │
              └────────────┼────────────┘
                           ▼
                       Task Queue
                           │
                           ▼
                       Meta API
```

实现：

``` text
数据
 ↓
分析
 ↓
规则判断
 ↓
动作
 ↓
任务队列
 ↓
Meta API
 ↓
结果
 ↓
数据库
```

------------------------------------------------------------------------

# 47. 推荐的最终业务模型

``` text
Organization
    │
    ├── BM
    │    │
    │    ├── Credential
    │    │
    │    └── Ad Accounts
    │         ├── Account 01
    │         ├── Account 02
    │         ├── Account 03
    │         └── Account N
    │
    ├── Campaign Templates
    │
    ├── Creatives
    │
    ├── Campaign Instances
    │
    ├── Jobs
    │
    ├── Insights
    │
    └── Strategy Rules
```

------------------------------------------------------------------------

# 48. 最终系统数据流

``` text
                 用户
                  │
                  ▼
              Web Console
                  │
                  ▼
               FastAPI
                  │
         ┌────────┼─────────┐
         ▼        ▼         ▼
       Template  Account   Job
         │        │         │
         └────────┼─────────┘
                  ▼
              Job Queue
                  │
                  ▼
              Celery Worker
                  │
                  ▼
            Campaign Builder
                  │
                  ▼
            MetaAdsService
                  │
                  ▼
         facebook-business-sdk
                  │
                  ▼
             Meta API
                  │
         ┌────────┼────────┐
         ▼        ▼        ▼
      Campaign  AdSet      Ad
         │        │        │
         └────────┼────────┘
                  ▼
              PostgreSQL
                  │
         ┌────────┴────────┐
         ▼                 ▼
      Dashboard       Strategy Engine
                           │
                           ▼
                       New Action
                           │
                           ▼
                       Job Queue
```

------------------------------------------------------------------------

# 49. 核心原则总结

## 原则一：模板优先

不要让用户重复填写几十个 Meta 参数。

应该：

``` text
一次配置
    ↓
保存 Template
    ↓
批量部署
```

------------------------------------------------------------------------

## 原则二：任务异步

不要让 HTTP 请求等待几十、几百甚至几千个广告账户完成。

应该：

``` text
HTTP Request
    ↓
Create Job
    ↓
Return job_id
    ↓
Worker Async Execute
```

------------------------------------------------------------------------

## 原则三：每个账户独立状态

不要：

``` text
100 个账户
→ 一个状态
```

应该：

``` text
Job
 ├── Account A → SUCCESS
 ├── Account B → SUCCESS
 ├── Account C → FAILED
 └── Account D → RUNNING
```

------------------------------------------------------------------------

## 原则四：幂等

任何批量操作都必须可以安全 Retry。

``` text
Retry
 ≠
Duplicate
```

------------------------------------------------------------------------

## 原则五：限流

Batch API 不能替代 Rate Limiting。

应该：

``` text
Queue
+
Concurrency Limit
+
Rate Limit
+
Backoff
+
Retry
```

------------------------------------------------------------------------

## 原则六：SDK 隔离

业务代码不要直接依赖 Meta SDK。

应该：

``` text
Business Logic
      ↓
MetaAdsService
      ↓
facebook_business
```

这样 Meta API 版本变化时只需要维护 Service 层。

------------------------------------------------------------------------

## 原则七：数据本地化

Dashboard 尽量查询 PostgreSQL：

``` text
Meta API
    ↓
Sync
    ↓
PostgreSQL
    ↓
Dashboard
```

而不是：

``` text
Dashboard
    ↓
每次实时请求 Meta
```

------------------------------------------------------------------------

# 50. MVP 开发顺序

建议按以下顺序实施：

``` text
Phase 1
│
├── FastAPI 项目
├── PostgreSQL
├── SQLAlchemy
└── 用户权限

Phase 2
│
├── BM 管理
├── Credential
└── Ad Account 同步

Phase 3
│
├── Campaign Template
├── Creative
└── Builder

Phase 4
│
├── Celery
├── Redis
├── Job
└── Retry

Phase 5
│
├── Campaign
├── AdSet
├── Ad
└── Batch Create

Phase 6
│
├── Pause
├── Enable
└── Budget Update

Phase 7
│
├── Insights
├── Dashboard
└── Sync

Phase 8
│
├── Strategy Rule
├── Auto Pause
└── Auto Scale
```

------------------------------------------------------------------------

# 51. 结论

这个系统最终应该从一个：

> "Meta 批量 API 工具"

演进成：

> **"Meta 多 BM / 多广告账户统一投放与自动化管理平台"**

核心架构：

``` text
BM
 ↓
Ad Accounts
 ↓
Campaign Template
 ↓
Campaign Job
 ↓
Celery Queue
 ↓
MetaAdsService
 ↓
facebook-business-sdk
 ↓
Meta API
 ↓
Campaign / AdSet / Ad
 ↓
Insights
 ↓
Strategy Engine
 ↓
自动化 Action
```

最关键的技术抽象是：

``` text
Campaign Template
        +
Account Deployment
        +
Job / Task
        +
Instance Mapping
        +
Strategy Rule
```

通过这五层，可以支持从几十个广告账户逐步扩展到数百、数千账户，而不需要重新设计核心业务模型。

> **合规说明：** 系统应仅使用 Meta 官方授权、官方 Marketing API
> 和账户拥有的合法权限进行操作，不应设计用于绕过平台限制、规避风控、规避封禁或其他违反
> Meta 平台政策的行为。

# Meta 账号管理模块 V1.0 — 可执行开发任务文档

> 版本：V1.0  
> 模块：Meta 账号管理 / BM → 多广告账户  
> 定位：为后续 Meta 批量投流提供稳定、可维护的广告账户资源池  
> 技术栈建议：FastAPI + SQLAlchemy + PostgreSQL + Redis + Celery + Python Business SDK

---

## 1. V1 目标

第一版只解决：

```text
Credential
   ↓
BM
   ↓
BM 下 Ad Accounts
   ↓
同步 / 状态管理
   ↓
可用广告账户资源池
   ↓
后续 Campaign Template / Batch Job
```

### V1 必须支持

- Credential 管理
- BM 新增、编辑、查看、禁用、归档
- BM 与 Credential 关联
- Credential / BM API 连接验证
- 从 Meta 拉取 BM 基础信息
- 拉取 BM 下广告账户
- 批量导入广告账户
- 广告账户列表、详情
- Meta 状态同步
- 系统启用 / 禁用
- 同步日志
- 为后续批量投放提供可用账户查询接口

### V1 不做

- Agency / Partner
- Client BM
- Catalog / Product Set
- Instagram / Page 完整资产管理
- Pixel / Dataset 完整资产中心
- Audience Network
- Strategy Engine
- 自动扩量 / 自动关停
- 复杂多租户权限
- 多 Credential 智能路由

这些只作为未来扩展钩子。

---

# 2. 模块边界

```text
Meta 账号管理
│
├── Credential
├── BM 管理
├── 广告账户管理
├── Meta 同步
├── 状态管理
└── 操作 / 同步日志
```

账号管理模块不负责 Campaign 创建。

核心职责：

> 维护可靠的 Meta BM 和 Ad Account 资源池，并准确判断账户是否允许参与后续批量投放。

---

# 3. V1 数据表

核心 4 张表：

```text
meta_credentials
businesses
ad_accounts
meta_sync_logs
```

可选：

```text
operation_logs
```

关系：

```text
Credential
    │
    ▼
  Business / BM
    │
    ├── Ad Account
    ├── Ad Account
    └── Ad Account
```

---

# 4. meta_credentials

## 4.1 PostgreSQL DDL

```sql
CREATE TABLE meta_credentials (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    app_id VARCHAR(128),
    access_token_encrypted TEXT NOT NULL,
    token_type VARCHAR(32) NOT NULL DEFAULT 'USER_TOKEN',
    expires_at TIMESTAMP NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    last_verified_at TIMESTAMP NULL,
    last_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_meta_credentials_status
    ON meta_credentials(status);
```

## 4.2 字段备注 / 默认值

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| id | BIGSERIAL | 是 | 自增 | 系统内部主键 |
| name | VARCHAR(255) | 是 | 无 | Credential 名称 |
| app_id | VARCHAR(128) | 否 | NULL | Meta App ID |
| access_token_encrypted | TEXT | 是 | 无 | 加密后的 Access Token，禁止明文存储 |
| token_type | VARCHAR(32) | 是 | USER_TOKEN | Token 类型 |
| expires_at | TIMESTAMP | 否 | NULL | Token 过期时间 |
| status | VARCHAR(32) | 是 | ACTIVE | Credential 状态 |
| last_verified_at | TIMESTAMP | 否 | NULL | 最近验证成功时间 |
| last_error | TEXT | 否 | NULL | 最近错误 |
| created_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 更新时间 |

### status

```text
ACTIVE
DISABLED
EXPIRED
INVALID
VERIFYING
```

---

# 5. businesses

## 5.1 PostgreSQL DDL

```sql
CREATE TABLE businesses (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    business_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    credential_id BIGINT NULL,
    timezone VARCHAR(64) NULL,
    currency VARCHAR(16) NULL,
    description TEXT NULL,
    sync_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    last_synced_at TIMESTAMP NULL,
    last_sync_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_business_credential
        FOREIGN KEY (credential_id)
        REFERENCES meta_credentials(id)
        ON DELETE SET NULL
);

CREATE INDEX idx_businesses_status
    ON businesses(status);

CREATE INDEX idx_businesses_credential_id
    ON businesses(credential_id);

CREATE INDEX idx_businesses_sync_status
    ON businesses(sync_status);
```

## 5.2 字段备注 / 默认值

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| id | BIGSERIAL | 是 | 自增 | 系统内部主键 |
| name | VARCHAR(255) | 是 | 无 | BM 显示名称 |
| business_id | VARCHAR(64) | 是 | 无 | Meta Business ID，唯一 |
| status | VARCHAR(32) | 是 | ACTIVE | 系统侧 BM 状态 |
| credential_id | BIGINT | 否 | NULL | 默认 Credential |
| timezone | VARCHAR(64) | 否 | NULL | BM 时区 |
| currency | VARCHAR(16) | 否 | NULL | BM 默认货币 |
| description | TEXT | 否 | NULL | 备注 |
| sync_status | VARCHAR(32) | 是 | PENDING | 最近同步状态 |
| last_synced_at | TIMESTAMP | 否 | NULL | 最近成功同步时间 |
| last_sync_error | TEXT | 否 | NULL | 最近同步错误 |
| created_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 更新时间 |

### BM status

```text
ACTIVE
DISABLED
ARCHIVED
```

### sync_status

```text
PENDING
SYNCING
SUCCESS
FAILED
```

注意：

> `status` 是业务状态，`sync_status` 是同步状态，两者不能混用。

---

# 6. ad_accounts

这是 V1 最核心的数据表。

## 6.1 PostgreSQL DDL

```sql
CREATE TABLE ad_accounts (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NOT NULL,
    account_id VARCHAR(64) NOT NULL,
    account_name VARCHAR(255) NULL,
    account_status VARCHAR(32) NULL,
    effective_status VARCHAR(32) NULL,
    currency VARCHAR(16) NULL,
    timezone VARCHAR(64) NULL,
    spend_cap BIGINT NULL DEFAULT 0,
    amount_spent BIGINT NULL DEFAULT 0,
    balance BIGINT NULL DEFAULT 0,
    disable_reason VARCHAR(255) NULL,
    system_status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    capabilities JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMP NULL,
    last_sync_error TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (business_id, account_id),

    CONSTRAINT fk_ad_account_business
        FOREIGN KEY (business_id)
        REFERENCES businesses(id)
        ON DELETE RESTRICT
);

CREATE INDEX idx_ad_accounts_business_id
    ON ad_accounts(business_id);

CREATE INDEX idx_ad_accounts_system_status
    ON ad_accounts(system_status);

CREATE INDEX idx_ad_accounts_account_status
    ON ad_accounts(account_status);

CREATE INDEX idx_ad_accounts_effective_status
    ON ad_accounts(effective_status);
```

## 6.2 字段备注 / 默认值

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| id | BIGSERIAL | 是 | 自增 | 系统内部主键 |
| business_id | BIGINT | 是 | 无 | 所属 BM |
| account_id | VARCHAR(64) | 是 | 无 | Meta Ad Account ID |
| account_name | VARCHAR(255) | 否 | NULL | 广告账户名称 |
| account_status | VARCHAR(32) | 否 | NULL | Meta 返回的账户状态 |
| effective_status | VARCHAR(32) | 否 | NULL | Meta 有效状态 |
| currency | VARCHAR(16) | 否 | NULL | 广告账户货币 |
| timezone | VARCHAR(64) | 否 | NULL | 广告账户时区 |
| spend_cap | BIGINT | 否 | 0 | Spend Cap，建议按最小货币单位保存 |
| amount_spent | BIGINT | 否 | 0 | 累计消费，按最小货币单位保存 |
| balance | BIGINT | 否 | 0 | 当前余额，按最小货币单位保存 |
| disable_reason | VARCHAR(255) | 否 | NULL | Meta 禁用原因 |
| system_status | VARCHAR(32) | 是 | ACTIVE | 系统是否允许参与批量投放 |
| capabilities | JSONB | 是 | {} | 能力扩展字段 |
| last_synced_at | TIMESTAMP | 否 | NULL | 最近同步时间 |
| last_sync_error | TEXT | 否 | NULL | 最近同步错误 |
| created_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 更新时间 |

---

# 7. 状态设计

必须区分：

```text
Meta Status
    account_status
    effective_status

System Status
    system_status
```

例如：

```text
Meta ACTIVE
System ACTIVE
```

= 正常可用。

```text
Meta DISABLED
System ACTIVE
```

= Meta 异常，系统没有主动禁用。

```text
Meta ACTIVE
System DISABLED
```

= Meta 正常，但管理员禁止参与批量投放。

## system_status

V1：

```text
ACTIVE
DISABLED
```

---

# 8. capabilities

V1 不单独建能力表，使用 JSONB。

默认：

```json
{}
```

示例：

```json
{
  "can_create_campaign": true,
  "can_create_adset": true,
  "can_create_ad": true,
  "can_read_insights": true
}
```

未来可扩展：

```json
{
  "can_create_campaign": true,
  "can_create_adset": true,
  "can_create_ad": true,
  "can_read_insights": true,
  "can_update_budget": true,
  "can_use_catalog": false
}
```

---

# 9. 金额字段

Meta 金额不要使用 FLOAT / DOUBLE。

建议：

```text
BIGINT
```

按最小货币单位保存。

例如：

```text
$10.50 → 1050
```

展示层再转换为：

```text
10.50
```

避免金额精度问题。

---

# 10. meta_sync_logs

## 10.1 DDL

```sql
CREATE TABLE meta_sync_logs (
    id BIGSERIAL PRIMARY KEY,
    business_id BIGINT NULL,
    sync_type VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'RUNNING',
    total_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_sync_log_business
        FOREIGN KEY (business_id)
        REFERENCES businesses(id)
        ON DELETE SET NULL
);

CREATE INDEX idx_meta_sync_logs_business_id
    ON meta_sync_logs(business_id);

CREATE INDEX idx_meta_sync_logs_created_at
    ON meta_sync_logs(created_at DESC);

CREATE INDEX idx_meta_sync_logs_status
    ON meta_sync_logs(status);
```

## 10.2 字段备注 / 默认值

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---|---|
| id | BIGSERIAL | 是 | 自增 | 日志 ID |
| business_id | BIGINT | 否 | NULL | 对应 BM |
| sync_type | VARCHAR(32) | 是 | 无 | BUSINESS / AD_ACCOUNT / FULL |
| status | VARCHAR(32) | 是 | RUNNING | 同步任务状态 |
| total_count | INTEGER | 是 | 0 | 总数量 |
| success_count | INTEGER | 是 | 0 | 成功数量 |
| failed_count | INTEGER | 是 | 0 | 失败数量 |
| error_message | TEXT | 否 | NULL | 错误信息 |
| started_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 开始时间 |
| finished_at | TIMESTAMP | 否 | NULL | 完成时间 |
| created_at | TIMESTAMP | 是 | CURRENT_TIMESTAMP | 创建时间 |

### sync_type

```text
BUSINESS
AD_ACCOUNT
FULL
```

### status

```text
RUNNING
SUCCESS
PARTIAL_SUCCESS
FAILED
```

---

# 11. 可选 operation_logs

如果 V1 需要审计：

```sql
CREATE TABLE operation_logs (
    id BIGSERIAL PRIMARY KEY,
    operator_id BIGINT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id BIGINT NULL,
    action VARCHAR(64) NOT NULL,
    request_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS',
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

V1 可以先建表，不一定马上做完整前端。

---

# 12. 页面结构

```text
Meta 投放
│
├── 账号管理
│   ├── BM 管理
│   ├── 广告账户
│   └── Credential
│
├── 投放模板
├── 批量任务
└── 数据报表
```

V1 账号管理：

```text
账号管理
├── BM 管理
├── 广告账户
└── Credential
```

---

# 13. BM 管理页面

路由：

```text
/ads/businesses
```

页面：

```text
┌───────────────────────────────────────────────────────────────┐
│ BM 管理                                      [+ 添加 BM]       │
├───────────────────────────────────────────────────────────────┤
│ 搜索 BM...   状态 ▼   Credential ▼          [同步全部]         │
├───────────────────────────────────────────────────────────────┤
│ BM 名称      Business ID    广告账户  正常  异常  Token  状态 │
│ ───────────────────────────────────────────────────────────── │
│ Brand Main   123456789      24       21    3    🟢     🟢    │
│ US Business  987654321       8        8    0    🟢     🟢    │
│ EU Business  555555555       5        2    3    🔴     🔴    │
└───────────────────────────────────────────────────────────────┘
```

### 列表字段

- BM 名称
- Business ID
- 广告账户数量
- 正常数量
- 异常数量
- Credential 状态
- 同步状态
- 最近同步
- BM 状态
- 操作

### 操作

```text
查看
编辑
同步
禁用
归档
```

---

# 14. 添加 BM

弹窗：

```text
┌─────────────────────────────────────┐
│ 添加 BM                             │
├─────────────────────────────────────┤
│ BM 名称 *                           │
│ [____________________________]      │
│                                     │
│ Business ID *                       │
│ [____________________________]      │
│                                     │
│ Credential *                        │
│ [选择 Credential ▼]                 │
│                                     │
│ 描述                                │
│ [____________________________]      │
│                                     │
│ [验证连接]                          │
│                                     │
│                 [取消] [保存]       │
└─────────────────────────────────────┘
```

保存流程：

```text
填写
 ↓
验证 Credential
 ↓
调用 Meta API 获取 Business
 ↓
校验 Business ID
 ↓
保存 BM
 ↓
同步 Ad Accounts
```

重复 Business ID：

```text
禁止创建重复记录
```

---

# 15. BM 详情页

路由：

```text
/ads/businesses/:id
```

```text
┌─────────────────────────────────────────────────────────────┐
│ ← BM 管理                                                   │
│                                                             │
│ Brand Main                                🟢 ACTIVE         │
│ Business ID: 123456789                                       │
│                                                             │
│ [同步] [编辑] [禁用]                                        │
├─────────────────────────────────────────────────────────────┤
│ 概览                                                        │
│                                                             │
│ 广告账户       正常       异常       Credential             │
│   24           21          3           🟢                   │
├─────────────────────────────────────────────────────────────┤
│ 广告账户                                      [导入账户]     │
│                                                             │
│ 搜索...       Meta 状态 ▼    系统状态 ▼                     │
│                                                             │
│ Account A   act_111   ACTIVE     ACTIVE      查看            │
│ Account B   act_222   ACTIVE     ACTIVE      查看            │
│ Account C   act_333   DISABLED   ACTIVE      查看            │
│ Account D   act_444   ACTIVE     DISABLED    查看            │
└─────────────────────────────────────────────────────────────┘
```

Tab：

```text
[概览] [广告账户] [同步记录]
```

未来可增加：

```text
[Page] [Instagram] [Dataset] [Catalog] [Partner]
```

---

# 16. 广告账户列表

路由：

```text
/ads/accounts
```

```text
┌────────────────────────────────────────────────────────────────┐
│ 广告账户                                       [同步全部]       │
├────────────────────────────────────────────────────────────────┤
│ BM ▼  Meta 状态 ▼  系统状态 ▼  货币 ▼  搜索...                 │
├────────────────────────────────────────────────────────────────┤
│ BM          广告账户       Account ID    Meta状态   系统状态  │
│ ───────────────────────────────────────────────────────────── │
│ Brand Main  Account A      act_111       ACTIVE      🟢       │
│ Brand Main  Account B      act_222       ACTIVE      🟢       │
│ Brand Main  Account C      act_333       DISABLED    🟢       │
│ US BM       Account D      act_444       ACTIVE      ⚫       │
└────────────────────────────────────────────────────────────────┘
```

---

# 17. 广告账户导入

不要让用户手工填写账户全部字段。

流程：

```text
选择 BM
 ↓
从 Meta 同步广告账户
 ↓
展示 Meta 返回账户
 ↓
勾选
 ↓
导入
```

页面：

```text
┌────────────────────────────────────────────────────────────┐
│ 导入广告账户                                               │
├────────────────────────────────────────────────────────────┤
│ BM：Brand Main                                             │
│                                                            │
│ [从 Meta 同步]                                             │
│                                                            │
│ ☑ Account A   act_111   ACTIVE     USD                    │
│ ☑ Account B   act_222   ACTIVE     USD                    │
│ ☐ Account C   act_333   DISABLED   USD                    │
│ ☑ Account D   act_444   ACTIVE     EUR                    │
│                                                            │
│ 已选择：3                         [取消] [导入选中]          │
└────────────────────────────────────────────────────────────┘
```

---

# 18. 广告账户详情

路由：

```text
/ads/accounts/:id
```

页面需要展示：

```text
账户名称
Account ID
所属 BM
Meta Status
Effective Status
Currency
Timezone
Spend Cap
Amount Spent
Balance
最后同步
系统状态
```

系统设置至少包含：

```text
参与批量投放 [ON/OFF]
```

---

# 19. 可投放账户判断

后端提供：

```http
GET /api/meta/ad-accounts/available-for-deployment
```

基础判断：

```text
BM.status = ACTIVE
AND
AdAccount.system_status = ACTIVE
AND
Credential.status = ACTIVE
AND
Meta Account 状态允许投放
```

前端不要自行拼接判断规则。

统一由后端 Service 判断。

---

# 20. API 设计

## Credential

```http
POST /api/meta/credentials
GET /api/meta/credentials
POST /api/meta/credentials/{id}/verify
POST /api/meta/credentials/{id}/disable
```

## BM

```http
POST /api/meta/businesses
GET /api/meta/businesses
GET /api/meta/businesses/{id}
PUT /api/meta/businesses/{id}
POST /api/meta/businesses/{id}/sync
POST /api/meta/businesses/{id}/disable
POST /api/meta/businesses/{id}/archive
```

## Ad Account

```http
GET /api/meta/ad-accounts
GET /api/meta/ad-accounts/{id}
POST /api/meta/ad-accounts/{id}/sync
POST /api/meta/ad-accounts/sync
POST /api/meta/ad-accounts/{id}/status
GET /api/meta/ad-accounts/available-for-deployment
```

## 批量导入

```http
POST /api/meta/businesses/{business_id}/ad-accounts/import
```

Request：

```json
{
  "account_ids": [
    "act_111",
    "act_222",
    "act_333"
  ]
}
```

---

# 21. Meta SDK Service 分层

禁止 Controller 直接操作 SDK。

推荐：

```text
Controller
    ↓
BusinessService / AdAccountService
    ↓
MetaClient
    ↓
facebook-business-sdk
    ↓
Meta API
```

目录：

```text
app/services/meta/
├── client.py
├── credential_service.py
├── business_service.py
├── ad_account_service.py
├── sync_service.py
└── exceptions.py
```

---

# 22. MetaClient

```python
class MetaClient:

    def __init__(self, access_token: str):
        self.access_token = access_token

    def get_business(self, business_id: str):
        pass

    def get_ad_accounts(self, business_id: str):
        pass

    def get_ad_account(self, account_id: str):
        pass
```

所有 Meta API 调用统一从这里经过，便于：

- Token 管理
- API Version
- Retry
- Rate Limit
- Error Mapping
- Logging
- Mock Test

---

# 23. Sync Service

```python
class MetaSyncService:

    def sync_business(self, business_id: int):
        pass

    def sync_ad_accounts(self, business_id: int):
        pass

    def sync_ad_account(self, ad_account_id: int):
        pass
```

流程：

```text
Business
 ↓
Credential
 ↓
Meta API
 ↓
Normalize
 ↓
Validate
 ↓
Upsert
 ↓
Update Sync Status
```

---

# 24. Upsert 规则

唯一键：

```text
business_id + account_id
```

重复导入 / 同步：

```text
INSERT if new
UPDATE if exists
```

**禁止同步覆盖 `system_status`。**

例如：

```text
管理员设置：
system_status = DISABLED

Meta 同步：
account_status = ACTIVE

最终：
account_status = ACTIVE
system_status = DISABLED
```

---

# 25. 同步任务异步化

推荐：

```text
HTTP
 ↓
创建 Sync Job
 ↓
Redis
 ↓
Celery Worker
 ↓
Meta API
 ↓
DB
```

HTTP 不应该长时间等待 Meta API。

返回：

```json
{
  "job_id": "sync_20260831_001",
  "status": "QUEUED"
}
```

---

# 26. Meta API 错误统一封装

```python
class MetaAPIError(Exception):
    pass

class MetaAuthError(MetaAPIError):
    pass

class MetaPermissionError(MetaAPIError):
    pass

class MetaRateLimitError(MetaAPIError):
    pass

class MetaResourceNotFoundError(MetaAPIError):
    pass
```

---

# 27. Token 安全

Access Token：

- 数据库加密保存
- 后端解密使用
- 前端禁止获取完整 Token
- 日志禁止打印 Token
- API Response 脱敏

前端只显示：

```text
Token：************abcd
```

---

# 28. 开发任务清单

## Phase 1：数据库

- [ ] 创建 `meta_credentials`
- [ ] 创建 `businesses`
- [ ] 创建 `ad_accounts`
- [ ] 创建 `meta_sync_logs`
- [ ] 可选创建 `operation_logs`
- [ ] Foreign Key
- [ ] Unique Constraint
- [ ] Index
- [ ] Migration

## Phase 2：Meta Client

- [ ] 初始化 Business SDK
- [ ] Credential 解密
- [ ] Business 查询
- [ ] Ad Account 查询
- [ ] Error Mapping
- [ ] API Version 配置
- [ ] 基础 Retry

## Phase 3：Credential

- [ ] CRUD
- [ ] Token 加密
- [ ] Token 验证
- [ ] Token 脱敏
- [ ] 过期检测
- [ ] 禁用

## Phase 4：BM

- [ ] CRUD
- [ ] Business ID 验证
- [ ] Meta 信息同步
- [ ] 状态管理
- [ ] 归档
- [ ] BM 详情

## Phase 5：Ad Account

- [ ] Meta 拉取
- [ ] 批量导入
- [ ] Upsert
- [ ] 列表
- [ ] 详情
- [ ] 单账户同步
- [ ] 批量同步
- [ ] System Status

## Phase 6：Sync

- [ ] Redis
- [ ] Celery
- [ ] Sync Job
- [ ] Retry
- [ ] Sync Log
- [ ] Partial Success
- [ ] 错误记录

## Phase 7：前端

- [ ] Credential 页面
- [ ] BM List
- [ ] BM Detail
- [ ] Ad Account List
- [ ] Ad Account Detail
- [ ] Import Modal
- [ ] Sync 状态
- [ ] 错误提示

## Phase 8：投放模块对接

- [ ] available-for-deployment API
- [ ] Campaign Template 对接
- [ ] Batch Job 对接

---

# 29. 验收标准

## Credential

- [ ] Token 加密保存
- [ ] 前端不返回完整 Token
- [ ] 可验证
- [ ] 无效 Token 标记 INVALID
- [ ] 可禁用

## BM

- [ ] 可新增 BM
- [ ] Business ID 唯一
- [ ] 可验证
- [ ] 可同步
- [ ] 可编辑
- [ ] 可禁用
- [ ] 可归档

## Ad Account

- [ ] 可以从 BM 拉取
- [ ] 可以批量选择导入
- [ ] 不产生重复
- [ ] 可以查看详情
- [ ] 可以同步
- [ ] 可以系统启用 / 禁用
- [ ] Meta 状态和系统状态分离

## Sync

- [ ] 异步执行
- [ ] 返回 Job ID
- [ ] 有同步日志
- [ ] 支持失败重试
- [ ] 同步失败不删除已有数据
- [ ] 显示最后同步时间和错误

## Batch 投放接口

- [ ] ACTIVE BM 才能返回
- [ ] ACTIVE System Status 账户才能返回
- [ ] Credential 正常才能返回
- [ ] Meta 状态不允许投放的账户不返回
- [ ] 返回 BM 信息
- [ ] 返回 Ad Account 信息

---

# 30. V1 项目目录

```text
app/
├── api/
│   └── meta/
│       ├── credentials.py
│       ├── businesses.py
│       └── ad_accounts.py
│
├── models/
│   └── meta/
│       ├── credential.py
│       ├── business.py
│       ├── ad_account.py
│       ├── sync_log.py
│       └── operation_log.py
│
├── schemas/
│   └── meta/
│       ├── credential.py
│       ├── business.py
│       └── ad_account.py
│
├── services/
│   └── meta/
│       ├── client.py
│       ├── credential_service.py
│       ├── business_service.py
│       ├── ad_account_service.py
│       ├── sync_service.py
│       └── exceptions.py
│
├── workers/
│   └── meta/
│       ├── sync_tasks.py
│       └── verify_tasks.py
│
└── extensions/
    ├── catalog/
    ├── partner/
    └── strategy/
```

---

# 31. 后续扩展钩子

## Catalog

V1 不创建完整 Catalog 数据模型。

只通过：

```text
capabilities
creative_config_json
Service Interface
```

预留。

未来：

```text
Catalog
Product Set
Catalog Creative
```

## Partner / Agency

V1：

```text
Business → Ad Account
```

未来：

```text
Organization
  ↓
Business
  ↓
Asset Access
  ↓
Ad Account
```

不要把 Partner 逻辑写死到 Ad Account Service。

## Strategy

未来：

```text
Insights
 ↓
Strategy Engine
 ↓
Action
 ↓
Job
 ↓
Meta API
```

账号模块只提供：

```text
可用 Ad Accounts
```

---

# 32. V1 最终数据关系

```text
┌──────────────────────┐
│  meta_credentials    │
├──────────────────────┤
│ id                   │
│ name                 │
│ app_id               │
│ access_token         │
│ token_type           │
│ expires_at           │
│ status               │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│      businesses      │
├──────────────────────┤
│ id                   │
│ name                 │
│ business_id          │
│ status               │
│ credential_id        │
│ timezone             │
│ currency             │
│ sync_status          │
│ last_synced_at       │
└──────────┬───────────┘
           │ 1:N
           ▼
┌──────────────────────┐
│     ad_accounts      │
├──────────────────────┤
│ id                   │
│ business_id          │
│ account_id           │
│ account_name         │
│ account_status       │
│ effective_status     │
│ currency             │
│ timezone             │
│ spend_cap            │
│ amount_spent         │
│ balance              │
│ system_status        │
│ capabilities         │
│ last_synced_at       │
└──────────────────────┘

businesses
    │
    └── 1:N ── meta_sync_logs
```

---

# 33. V1 完成后的业务闭环

```text
配置 Credential
      ↓
添加 BM
      ↓
验证 BM
      ↓
同步 BM
      ↓
获取 Ad Accounts
      ↓
勾选导入
      ↓
维护账户状态
      ↓
同步 Meta 状态
      ↓
形成可用账户池
      ↓
Campaign Template
      ↓
Batch Job
```

最终目标：

> **一个 BM 可以稳定维护 N 个 Ad Account，系统能够准确识别哪些账户可以参与后续批量投放。**

---

# 34. V1 设计原则

### 原则 1：先做资源池

账号管理不是投放系统本身，职责是维护可靠的 Meta 账号资源。

### 原则 2：SDK 与业务解耦

必须：

```text
Controller
 ↓
Service
 ↓
MetaClient
 ↓
Business SDK
```

### 原则 3：同步不删除历史

Meta 不返回的账户不要直接 DELETE。

### 原则 4：Meta 状态与系统状态分离

```text
Meta Status ≠ System Status
```

### 原则 5：未来功能只留钩子

```text
Catalog
Partner
Strategy
Monetization
```

V1 不实现复杂业务，但通过 JSON Config、Service Interface、Extension Directory 保留扩展能力。

---

# 35. Definition of Done

以下链路全部跑通，即认为 Meta 账号管理 V1 完成：

```text
Credential
    ↓
Verify
    ↓
Add BM
    ↓
Sync BM
    ↓
Fetch Ad Accounts
    ↓
Select Accounts
    ↓
Import
    ↓
Ad Account List
    ↓
Ad Account Detail
    ↓
Enable / Disable
    ↓
Sync
    ↓
Available For Deployment
    ↓
Campaign Template
```

**V1 核心原则：先把 `BM → 多 Ad Account → 可用账户池` 做稳定，再向完整 Meta Ads Platform 扩展。**

# API 接口文档

按业务模块组织的后端接口说明。

- 交互文档（Swagger）：http://localhost:8000/docs
- 接口总数：91（OpenAPI 口径，含 main.py 内联路由）
- 最后更新：2026-08-31

模块索引：认证 / 用户 / **BM 主账号** / **凭据管理** / **广告账户** / 素材 / 投放模板 /
任务中心 / 广告系列 / 异步任务 / 系统。
其中 4、5、6 三节为「账号统一管理」：**BM 主账号 → 凭据（加密）→ 广告账户**，三层解耦。

**两条全局约定（Meta 账号管理 V1）：**

| 约定 | 说明 |
|---|---|
| 金额单位 | 一律 **BIGINT 最小货币单位**（`$10.50` → `1050`）。后端换算见 `core/money.py`，前端见 `utils/money.ts`。`ctr / cpc / cpm / roas / risk_score` 是派生指标，保持浮点 |
| 状态分离 | Meta 侧状态（`account_status` / `effective_status`）由同步覆盖；系统侧状态（`system_status`）**同步绝不覆盖**，代表管理员是否允许该账户参与投放 |

---

## 1. 通用约定

### 1.1 基础 URL

```
http://localhost:8000
```

前端通过 Vite 代理访问（`/api` → `http://localhost:8000`，路径不改写）。

### 1.2 鉴权

除下列公开路径外，**所有 `/api/` 路径均需携带有效 JWT**（由全局鉴权中间件 `AuthEnforcementMiddleware` 强制）：

```
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /health
```

请求头：

```http
Authorization: Bearer <access_token>
```

未携带或令牌无效返回 `401`；令牌过期返回 `401` 并提示"令牌已过期"。

### 1.3 权限等级

| 标记 | 含义 |
|---|---|
| `公开` | 无需令牌 |
| `登录` | 需有效 JWT（任意角色） |
| `管理员` | 需有效 JWT 且 `role == admin` |

### 1.4 响应与错误

成功时直接返回业务对象（JSON）。

HTTP 异常统一返回：

```json
{ "error": "错误描述" }
```

| 状态码 | 场景 |
|---|---|
| 400 | 参数错误 / 业务校验失败 |
| 401 | 未认证或令牌过期 |
| 403 | 权限不足（非管理员访问管理接口） |
| 404 | 资源不存在 |
| 429 | 触发 API 频次限制 |
| 500 | 服务端异常 |

---

## 2. 认证模块 `/api/v1/auth`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 公开 | 用户登录 |
| POST | `/api/v1/auth/logout` | 公开 | 登出（后端无状态，前端清除 token） |
| GET | `/api/v1/auth/me` | 登录 | 获取当前用户信息 |

### POST /api/v1/auth/login

请求体：

```json
{ "email": "admin@fbads.com", "password": "admin123456" }
```

响应：

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user": {
    "id": "xxx",
    "email": "admin@fbads.com",
    "username": "admin",
    "role": "admin",
    "company_id": "",
    "permissions": [],
    "settings": {}
  }
}
```

错误：

- `401` 邮箱或密码错误
- `403` 账户已被禁用

> 令牌有效期 7 天，使用 HS256 签名，密钥来自 `SECRET_KEY`。

### GET /api/v1/auth/me

返回与登录响应中 `user` 相同的结构。

---

## 3. 用户管理 `/api/v1/users`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/users` | 管理员 | 用户列表（支持搜索/角色过滤） |
| POST | `/api/v1/users` | 管理员 | 创建用户 |
| GET | `/api/v1/users/{user_id}` | 登录 | 用户详情 |
| PUT | `/api/v1/users/{user_id}` | 管理员 | 更新用户 |
| DELETE | `/api/v1/users/{user_id}` | 管理员 | 删除用户 |
| POST | `/api/v1/users/{user_id}/reset-password` | 管理员 | 重置密码 |
| POST | `/api/v1/users/{user_id}/toggle-active` | 管理员 | 启用/禁用 |
| GET | `/api/v1/users/{user_id}/accounts` | 登录 | 用户可访问的广告账户 |
| PUT | `/api/v1/users/{user_id}/settings` | 登录 | 更新用户设置 |

### GET /api/v1/users

查询参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `search` | string | 按邮箱/用户名搜索 |
| `role` | string | 角色过滤（admin/manager/user） |
| `page` | int | 页码 |
| `page_size` | int | 每页条数 |

### POST /api/v1/users

```json
{
  "email": "user@example.com",
  "username": "user1",
  "password": "123456",
  "role": "user",
  "company_id": null,
  "is_active": true
}
```

返回 `201`。

### PUT /api/v1/users/{user_id}

所有字段可选：

```json
{
  "email": "new@example.com",
  "username": "newname",
  "role": "manager",
  "company_id": null,
  "is_active": true,
  "permissions": []
}
```

### POST /api/v1/users/{user_id}/reset-password

```json
{ "password": "newpassword" }
```

### GET /api/v1/users/{user_id}/accounts

```json
{
  "accounts": [
    {
      "id": "xxx",
      "account_id": "act_123456",
      "account_name": "账户A",
      "currency": "USD",
      "status": "active",
      "daily_spend_limit": 0,
      "risk_score": 0,
      "is_frozen": false
    }
  ]
}
```

---

## 4. BM 主账号 `/api/v1/meta-accounts`

对应设计文档中的 `businesses` 表（表名沿用 `meta_accounts`），全部为管理员权限。

> **三层分离**：BM 主表只保存主数据，**不再有明文 Token 列**。
> 创建/更新时传入的 `access_token` 会加密写入 `credentials` 表（见第 5 节），
> 调用 Meta API 所需 Token 由 `CredentialService.resolve_token_for_meta()` 解析。

**状态分两类，不可混用**：
- `status`：业务状态（ACTIVE / DISABLED / ARCHIVED），人工维护
- `sync_status`：同步状态（PENDING / SYNCING / SUCCESS / FAILED），同步任务维护

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/meta-accounts` | 管理员 | 列表（含凭据健康状态） |
| GET | `/api/v1/meta-accounts/{meta_id}` | 管理员 | 详情（含账户列表与统计） |
| GET | `/api/v1/meta-accounts/default` | 管理员 | 获取默认主账号 |
| POST | `/api/v1/meta-accounts` | 管理员 | 创建（Token 加密入凭据表） |
| PUT | `/api/v1/meta-accounts/{meta_id}` | 管理员 | 更新（传 `access_token` 即轮换凭据） |
| DELETE | `/api/v1/meta-accounts/{meta_id}` | 管理员 | 删除（名下凭据一并清理） |
| POST | `/api/v1/meta-accounts/{meta_id}/set-default` | 管理员 | 设为默认 |
| POST | `/api/v1/meta-accounts/{meta_id}/verify` | 管理员 | 验证 BM 与凭据能否连通 Meta |
| POST | `/api/v1/meta-accounts/{meta_id}/disable` | 管理员 | 禁用 |
| POST | `/api/v1/meta-accounts/{meta_id}/archive` | 管理员 | 归档 |
| POST | `/api/v1/meta-accounts/verify-account` | 管理员 | 校验广告账户归属该 BM |
| POST | `/api/v1/meta-accounts/{meta_id}/sync-accounts` | 管理员 | **异步**同步该 BM 下的广告账户 |
| GET | `/api/v1/meta-accounts/{meta_id}/sync-logs` | 管理员 | 该 BM 的同步日志 |
| GET | `/api/v1/meta-accounts/{meta_id}/ad-accounts/from-meta` | 管理员 | 拉取 Meta 侧账户列表（不入库，供勾选） |
| POST | `/api/v1/meta-accounts/{meta_id}/ad-accounts/import` | 管理员 | 按勾选结果导入账户 |
| GET | `/api/v1/meta-accounts/{meta_id}/credentials` | 管理员 | 该 BM 名下的凭据列表 |
| POST | `/api/v1/meta-accounts/{meta_id}/rotate-token` | 管理员 | 轮换该 BM 的 Token |

### POST /api/v1/meta-accounts

```json
{
  "name": "BM-A",
  "business_id": "1234567890",
  "access_token": "EAA...",
  "app_id": "xxx",
  "is_default": false,
  "token_type": "USER",
  "timezone": "Asia/Shanghai",
  "currency": "USD",
  "description": "主投 BM",
  "verify_before_save": true
}
```

保存流程（文档 §14）：填写 → 验证 Credential → 调用 Meta 获取 Business →
校验 Business ID → 保存 → 同步 Ad Accounts。
重复 Business ID 禁止创建。

响应（`to_dict()` 不返回任何 Token，仅返回凭据健康状态）：

```json
{
  "id": "xxx",
  "name": "BM-A",
  "business_id": "1234567890",
  "app_id": "xxx",
  "is_default": false,
  "status": "ACTIVE",
  "is_active": true,
  "sync_status": "PENDING",
  "last_synced_at": null,
  "last_sync_error": null,
  "timezone": "Asia/Shanghai",
  "currency": "USD",
  "description": "主投 BM",
  "created_at": "2026-08-31T10:00:00",
  "updated_at": "2026-08-31T10:00:00",
  "account_count": 0,
  "credential_id": "cred_xxx",
  "credential_status": "ACTIVE",
  "credential_masked": "EAAA...9zQd",
  "credential_expires_at": null,
  "credential_is_expired": false,
  "has_credential": true,
  "credential_source": "CREDENTIALS"
}
```

`credential_status` 取值：`ACTIVE` / `VERIFYING` / `EXPIRED` / `INVALID` / `DISABLED` / `NONE`（无凭据）。
`credential_source`：`CREDENTIALS`（凭据表）/ `NONE`。

### PUT /api/v1/meta-accounts/{meta_id}

所有字段可选：`name`、`business_id`、`access_token`、`app_id`、`is_default`、`status`、
`timezone`、`currency`、`description`。

> 传 `access_token` 表示**轮换**该 BM 的凭据（旧凭据转 `DISABLED`），不传则只改主数据。

### POST /api/v1/meta-accounts/{meta_id}/verify

验证该 BM 与其凭据能否连通 Meta（文档 §14 的"验证连接"）。

```json
{
  "ok": true,
  "dev_mode": false,
  "error": null,
  "business": { "id": "1234567890", "name": "Brand Main" },
  "business_id_matched": true
}
```

### POST /api/v1/meta-accounts/{meta_id}/disable 与 /archive

BM 置为 `DISABLED` / `ARCHIVED` 后，其下账户不再进入可投放账户池
（见 `GET /api/v1/accounts/available-for-deployment`）。

### POST /api/v1/meta-accounts/verify-account

校验某个广告账户是否归属指定 BM（调用 Meta API 拉取 BM 下的账户列表）。
校验用的 Token 由凭据表解析，不再读取 BM 主表明文字段。

```json
{
  "meta_account_id": "xxx",
  "account_id": "act_123456"
}
```

响应：

```json
{ "verified": true, "account_name": "账户A" }
```

> 未配置 FB 凭据或 SDK 不可用时返回 `dev_mode: true` 并放行（开发降级）。

### POST /api/v1/meta-accounts/{meta_id}/rotate-token

```json
{ "access_token": "新的明文 Token", "token_type": "USER" }
```

旧凭据保留为 `DISABLED` 便于回溯。

### POST /api/v1/meta-accounts/{meta_id}/sync-accounts

**异步**同步该 BM 下的广告账户（文档 §25：HTTP 不等待 Meta API）。

响应立即返回 `job_id`：

```json
{
  "success": true,
  "job_id": "3f2a1b9c-...",
  "status": "QUEUED",
  "message": "同步任务已提交，请通过 /sync-logs 查询结果"
}
```

同步规则（文档 §24）：
- 唯一键 `(business_id, account_id)`，已存在则 UPDATE，不存在则 INSERT
- **不覆盖 `system_status`**：管理员禁用的账户，即使 Meta 侧正常也不自动恢复
- Meta 不再返回的账户**不会自动删除**

结果与进度查询 `GET /{meta_id}/sync-logs`。

### GET /api/v1/meta-accounts/{meta_id}/sync-logs

该 BM 的同步日志（文档 §10）。**与 `audit_logs`（操作审计）职责分离**，不要混用。

```json
[
  {
    "id": "log_xxx",
    "business_id": "xxx",
    "sync_type": "AD_ACCOUNT",
    "status": "PARTIAL_SUCCESS",
    "total_count": 128,
    "success_count": 126,
    "failed_count": 2,
    "error_message": "Upsert 账户失败 act_999",
    "celery_task_id": "3f2a1b9c-...",
    "started_at": "2026-08-31T10:00:00",
    "finished_at": "2026-08-31T10:00:12"
  }
]
```

### 账户导入（文档 §17）

不要让用户手工填写账户全部字段：选择 BM → 从 Meta 拉取 → 勾选 → 导入。

**1) 拉取 Meta 侧列表（不入库）**

```http
GET /api/v1/meta-accounts/{meta_id}/ad-accounts/from-meta
```

```json
{
  "dev_mode": false,
  "total": 3,
  "accounts": [
    { "id": "act_111", "name": "Account A", "account_status": "1", "currency": "USD", "_existing": false },
    { "id": "act_222", "name": "Account B", "account_status": "1", "currency": "EUR", "_existing": true }
  ]
}
```

**2) 按勾选结果导入**

```http
POST /api/v1/meta-accounts/{meta_id}/ad-accounts/import
```

```json
{ "account_ids": ["act_111", "act_222"] }
```

响应：

```json
{
  "success": true,
  "success_count": 2,
  "failed_count": 0,
  "sync_log": { "...": "同 sync-logs 结构" }
}
```

---

## 5. 凭据管理 `/api/v1/credentials`

Access Token 的独立管理层（设计文档第 9 节）。全部为管理员权限。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/credentials` | 管理员 | 列表（可按 BM / 状态过滤，仅脱敏） |
| POST | `/api/v1/credentials` | 管理员 | 新增凭据（绑定 BM，Token 加密存储） |
| GET | `/api/v1/credentials/{id}` | 管理员 | 详情（脱敏） |
| PATCH | `/api/v1/credentials/{id}` | 管理员 | 更新元信息（类型 / 过期时间 / 状态） |
| POST | `/api/v1/credentials/{id}/rotate` | 管理员 | 轮换 Token |
| POST | `/api/v1/credentials/{id}/verify` | 管理员 | 校验 Token 是否有效 |
| POST | `/api/v1/credentials/{id}/disable` | 管理员 | 停用 |
| POST | `/api/v1/credentials/{id}/enable` | 管理员 | 启用 |
| POST | `/api/v1/credentials/{id}/reveal` | 管理员 | 查看明文（需 `confirm`，写审计日志） |
| DELETE | `/api/v1/credentials/{id}` | 管理员 | 删除 |

### POST /api/v1/credentials

```json
{
  "meta_account_id": "xxx",
  "access_token": "EAA...",
  "name": "主投凭据",
  "app_id": "1234567890",
  "token_type": "USER",
  "expires_at": "2027-01-01T00:00:00",
  "replace_active": true
}
```

- `token_type`：`USER` / `SYSTEM_USER` / `PAGE`
- `expires_at`：为空表示长期有效
- `replace_active`：为 `true` 时把该 BM 现有的生效凭据置为 `DISABLED`（即轮换语义）

响应（**不含明文**）：

```json
{
  "id": "cred_xxx",
  "meta_account_id": "xxx",
  "meta_account_name": "BM-A",
  "business_id": "1234567890",
  "token_type": "USER",
  "expires_at": null,
  "status": "ACTIVE",
  "last_error": null,
  "last_verified_at": null,
  "is_expired": false,
  "access_token_masked": "EAAA...9zQd",
  "created_at": "2026-08-29T10:00:00"
}
```

### POST /api/v1/credentials/{id}/rotate

```json
{ "access_token": "新的明文 Token", "token_type": "USER", "keep_old": true }
```

`keep_old=true`（默认）时旧凭据保留为 `DISABLED`；为 `false` 时直接删除旧凭据。

### POST /api/v1/credentials/{id}/verify

调用 Meta `/me` 校验 Token 可用性。通过则刷新 `last_verified_at`；
失败则把凭据标记为 `INVALID` 并写入 `last_error`。

```json
{
  "credential_id": "cred_xxx",
  "valid": true,
  "dev_mode": false,
  "error": null,
  "token_info": { "id": "123", "name": "张三" },
  "status": "ACTIVE",
  "last_verified_at": "2026-08-29T10:00:00",
  "last_error": null
}
```

> 未配置 `FB_ACCESS_TOKEN` 时返回 `dev_mode: true`，不做真实网络调用。

### POST /api/v1/credentials/{id}/enable

已过期凭据**不允许直接启用**，需先调用 `rotate` 更换 Token，否则返回 400。

### POST /api/v1/credentials/{id}/reveal

```json
{ "confirm": true }
```

必须显式传 `confirm=true`，否则返回 400。返回明文并记录审计日志
（`action=REVEAL_CREDENTIAL`，含操作人与来源 IP）。

> 凭据解密失败（如 `SECRET_KEY` 被更换）时返回 500，提示改用 `rotate` 重新写入。

---

## 6. 广告账户 `/api/v1/accounts`

对应文档 §6 的 `ad_accounts` 表。

**三条核心约定：**

1. **Meta 状态与系统状态分离**（§7）
   - `account_status` / `effective_status`：Meta 返回，同步覆盖
   - `system_status`：系统侧是否允许参与批量投放，**同步绝不覆盖**
2. **金额一律 BIGINT 最小货币单位**（§9）：`$10.50` → `1050`，换算见 `core/money.py`
3. **唯一键 `(business_id, account_id)`**（§24）：同一 `act_xxx` 可挂多个 BM，同一 BM 内不重复

### 6.1 账户 CRUD

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/accounts` | 登录 | 列表（非管理员仅看已分配账户） |
| GET | `/api/v1/accounts/available-for-deployment` | 登录 | **可投放账户池**（判断规则由后端计算） |
| GET | `/api/v1/accounts/{account_pk}` | 登录 | 详情 |
| POST | `/api/v1/accounts` | 管理员 | 创建（归属 BM 必填，默认校验归属） |
| PUT | `/api/v1/accounts/{account_pk}` | 管理员 | 更新（含变更归属 BM） |
| POST | `/api/v1/accounts/bulk` | 管理员 | 批量停用 / 启用 / 删除 / 转移归属 |
| POST | `/api/v1/accounts/{account_pk}/transfer` | 管理员 | 转移 BM 归属 |
| DELETE | `/api/v1/accounts/{account_pk}` | 管理员 | 删除 |
| POST | `/api/v1/accounts/{account_pk}/freeze` | 管理员 | 停用（system_status=DISABLED） |
| POST | `/api/v1/accounts/{account_pk}/unfreeze` | 管理员 | 启用（system_status=ACTIVE） |
| POST | `/api/v1/accounts/{account_pk}/assign` | 管理员 | 分配用户 |
| POST | `/api/v1/accounts/{account_pk}/unassign` | 管理员 | 取消分配 |
| GET | `/api/v1/accounts/{account_pk}/users` | 管理员 | 已分配用户列表 |

> 注意：路径参数 `{account_pk}` 是**系统内部主键**，不是 Meta 的 `act_xxx`。

### 6.0 可投放账户池

```http
GET /api/v1/accounts/available-for-deployment?business_id=xxx
```

判断规则**全部由后端 `AdAccountService` 计算，前端不得自行拼接**（文档 §19）：

```text
BM.status = ACTIVE
AND AdAccount.system_status = ACTIVE
AND Credential.status = ACTIVE 且未过期
AND Meta 侧账户状态允许投放
```

响应自带 BM 与凭据上下文（脱敏），投放模块可直接使用：

```json
{
  "total": 1,
  "accounts": [
    {
      "id": "acc_xxx",
      "account_id": "act_111",
      "account_name": "Account A",
      "currency": "USD",
      "system_status": "ACTIVE",
      "account_status": "1",
      "business": { "id": "bm_xxx", "name": "BM-A", "business_id": "1234567890" },
      "credential": { "id": "cred_xxx", "status": "ACTIVE", "is_expired": false, "masked": "EAAA...9zQd" }
    }
  ]
}
```

> `JobService.create_job()` 创建批量任务时会用同一套规则预校验，
> 不可投放的账户会被剔除，全部不可用时直接报错。

#### GET /api/v1/accounts

查询参数：`search`、`system_status`、`account_status`、`business_id`、`page`、`page_size`。

- `system_status`：`ACTIVE` / `DISABLED`
- `account_status`：Meta 侧状态（如 `1` / `2`）
- `business_id`：按归属 BM 过滤

总数通过响应头 **`X-Total-Count`** 返回（响应体保持为数组）。

账户字段（所有账户出口一致，含 `/users/{id}/accounts`）：

```json
{
  "id": "acc_xxx",
  "account_id": "act_123456",
  "account_name": "账户A",
  "currency": "USD",
  "timezone": "America/New_York",
  "business_id": "bm_xxx",
  "business_name": "BM-A",
  "account_status": "1",
  "effective_status": "ACTIVE",
  "disable_reason": null,
  "system_status": "ACTIVE",
  "system_status_reason": null,
  "system_status_at": null,
  "capabilities": {},
  "spend_cap": 100000,
  "amount_spent": 45230,
  "balance": 54770,
  "daily_spend_limit": 100000,
  "monthly_spend_limit": 3000000,
  "risk_score": 0.12,
  "last_synced_at": "2026-08-31T10:00:00",
  "last_sync_error": null,
  "created_at": "2026-08-31T09:00:00",
  "updated_at": "2026-08-31T10:00:00"
}
```

> 金额字段均为**最小货币单位**（分）。`$1000.00` → `100000`。

#### POST /api/v1/accounts

```json
{
  "business_id": "bm_xxx",
  "account_id": "act_123456",
  "account_name": "账户A",
  "currency": "USD",
  "timezone": "America/New_York",
  "system_status": "ACTIVE",
  "daily_spend_limit": 100000,
  "monthly_spend_limit": 3000000,
  "risk_score": 0,
  "skip_verification": false
}
```

返回 `201`。

- `business_id` **必填**（V1 中账户必须归属某个 BM）
- 默认先调用 Meta 校验该账户确实在此 BM 下，校验不通过返回 400 且不落库
- 同一 BM 内 `account_id` 重复返回 400；跨 BM 允许重复

#### PUT /api/v1/accounts/{account_pk}

全部可选：`account_name`、`currency`、`timezone`、`system_status`、
`system_status_reason`、`daily_spend_limit`、`monthly_spend_limit`、`risk_score`、
`business_id`。

> Meta 侧字段（`account_status` / `amount_spent` 等）由同步写入，不在此修改。
> 变更 `business_id` 时同样要做归属校验。

#### POST /api/v1/accounts/{account_pk}/transfer

```json
{ "business_id": "yyy", "skip_verification": false }
```

默认调用 Meta 校验归属，校验不通过不写库；`skip_verification` 仅在 BM 凭据失效时的应急开关。

> V1 中 `business_id` 为 NOT NULL，**不允许通过本接口解除归属**（传 `null` 返回 400）。
> 如需停用账户请改用 `POST /{account_pk}/freeze`。

#### POST /api/v1/accounts/bulk

```json
{
  "action": "transfer",
  "account_ids": ["pk1", "pk2"],
  "business_id": "yyy",
  "skip_verification": false
}
```

`action` 取值：`freeze` / `unfreeze` / `delete` / `transfer`（`freeze` / `unfreeze`
即批量切换 `system_status`）。`action=transfer` 时 `business_id` 必填。

响应（**单条失败不影响其余条目**）：

```json
{
  "success": true,
  "action": "transfer",
  "success_count": 2,
  "failed_count": 1,
  "errors": [{ "account_id": "act_123", "error": "验证未通过，广告账户未归属该主账号（BM）" }]
}
```

#### POST /api/v1/accounts/{account_pk}/assign

```json
{ "user_ids": ["user_id_1", "user_id_2"] }
```

### 6.2 账户运营接口

以下接口的 `{account_id}` 为 Meta 广告账户 ID（`act_xxx` 或纯数字），全部需登录。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/accounts/{account_id}/sync` | 从 Meta 同步广告系列 |
| GET | `/api/v1/accounts/{account_id}/campaigns` | 本地已同步的系列列表 |
| GET | `/api/v1/accounts/{account_id}/spend-today` | 今日花费（`spend` 主单位 / `spend_minor` 最小单位） |
| GET | `/api/v1/accounts/{account_id}/performance` | 性能趋势 |
| GET | `/api/v1/accounts/{account_id}/fraud-score` | 欺诈评分 |
| GET | `/api/v1/accounts/{account_id}/daily-report` | 日报告 |
| GET | `/api/v1/accounts/{account_id}/weekly-report` | 周报告 |
| POST | `/api/v1/accounts/{account_id}/risk-check` | 执行风控检查 |
| GET | `/api/v1/accounts/{account_id}/risk-events` | 风险事件列表 |
| POST | `/api/v1/accounts/{account_id}/freeze` | 冻结账户 |
| GET | `/api/v1/accounts/{account_id}/safe-publish-interval` | 建议发布间隔 |
| GET | `/api/v1/accounts/{account_id}/publish-frequency-check` | 发布频次检查 |

#### POST /api/v1/accounts/{account_id}/sync

```json
{ "status": "success", "account_id": "act_123", "created": 5, "updated": 3 }
```

#### GET /api/v1/accounts/{account_id}/spend-today

```json
{ "account_id": "act_123", "spend": 1234.56, "currency": "USD" }
```

#### GET /api/v1/accounts/{account_id}/performance

查询参数：`days`（默认 30）

```json
{ "account_id": "act_123", "days": 30, "data": [ { "date": "...", "spend": 100, "impressions": 5000 } ] }
```

#### GET /api/v1/accounts/{account_id}/fraud-score

查询参数：`window_days`（默认 7）

```json
{ "account_id": "act_123", "fraud_score": 0.45, "risk_level": "medium", "threshold": 0.7 }
```

风险等级：`>0.8 critical` / `>0.6 high` / `>0.4 medium` / 否则 `low`

#### GET /api/v1/accounts/{account_id}/daily-report

查询参数：`report_date`（`YYYY-MM-DD`，默认今天）

无数据时返回 `404`；日期格式错误返回 `400`。

#### GET /api/v1/accounts/{account_id}/risk-events

查询参数：`limit`（默认 50）

```json
{
  "account_id": "act_123",
  "events": [
    {
      "id": "xxx",
      "event_type": "UNUSUAL_SPEND",
      "risk_level": "HIGH",
      "title": "异常花费检测",
      "description": "...",
      "is_resolved": false,
      "created_at": "2026-08-29T10:00:00"
    }
  ]
}
```

#### POST /api/v1/accounts/{account_id}/freeze

查询参数：`reason`（必填，字符串）

```json
{ "status": "success", "account_id": "act_123", "message": "Account frozen successfully" }
```

#### GET /api/v1/accounts/{account_id}/safe-publish-interval

```json
{
  "account_id": "act_123",
  "suggested_interval_minutes": 6,
  "rate_limit": { "minute": {...}, "hour": {...}, "day": {...} }
}
```

#### GET /api/v1/accounts/{account_id}/publish-frequency-check

查询参数：`hours`（默认 24）

```json
{
  "account_id": "act_123",
  "hours": 24,
  "safe": true,
  "current_usage": { ... },
  "recommendation": "可以发布"
}
```

判定规则：分钟用量 < 10 且小时用量 < 200。

---

## 7. 素材库 `/api/v1/media`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/media/upload` | 登录 | 上传素材（multipart/form-data） |
| GET | `/api/v1/media` | 登录 | 素材列表 |
| DELETE | `/api/v1/media/{asset_id}` | 登录 | 删除素材 |

### POST /api/v1/media/upload

表单字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file` | File | 必填，图片或视频 |
| `meta_account_id` | string | 可选，关联 BM |
| `account_id` | string | 可选，关联广告账户 |

限制（服务端白名单）：

- 图片：jpg / jpeg / png / gif / webp
- 视频：mp4 / mov / avi / mkv / webm
- 单文件上限 200MB

### GET /api/v1/media

查询参数：`meta_account_id`、`account_id`、`asset_type`（`image` / `video`）

响应 `MediaItem`：

```json
{
  "id": "xxx",
  "name": "创意图1",
  "asset_type": "image",
  "meta_account_id": null,
  "account_id": null,
  "url": "/uploads/xxx.png",
  "fb_hash": "xxx",
  "fb_video_id": null,
  "width": 1080,
  "height": 1080,
  "size": 204800,
  "mime_type": "image/png",
  "duration": null,
  "status": "active",
  "error": null,
  "created_at": "2026-08-29T10:00:00"
}
```

---

## 8. 投放模板 `/api/v1/templates`

**Campaign Template 是系统最核心的业务对象**：一次配置，批量部署到多个广告账户。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/templates` | 登录 | 列表（可 `?status=` 过滤） |
| POST | `/api/v1/templates` | 管理员 | 创建 |
| GET | `/api/v1/templates/{template_id}` | 登录 | 详情 |
| PATCH | `/api/v1/templates/{template_id}` | 管理员 | 局部更新 |
| POST | `/api/v1/templates/{template_id}/clone` | 管理员 | 复制 |
| DELETE | `/api/v1/templates/{template_id}` | 管理员 | 删除（软删除，置 ARCHIVED） |

### POST /api/v1/templates

```json
{
  "name": "US Sales V1",
  "objective": "OUTCOME_SALES",
  "buying_type": "AUCTION",
  "special_ad_categories": [],
  "budget_type": "DAILY",
  "daily_budget": 100,
  "lifetime_budget": null,
  "bid_strategy": null,
  "optimization_goal": "OFFSITE_CONVERSIONS",
  "billing_event": "IMPRESSIONS",
  "targeting_json": {
    "geo_locations": { "countries": ["US"] },
    "age_min": 18,
    "age_max": 65,
    "genders": [1, 2]
  },
  "placement_json": {},
  "creative_config_json": {
    "page_id": "123456",
    "creatives": [
      {
        "headline": "限时优惠",
        "primary_text": "优质商品，立即选购",
        "description": "满减活动",
        "cta": "LEARN_MORE",
        "landing_url": "https://example.com/landing",
        "image_hash": "abc123",
        "asset_id": "素材表ID"
      }
    ]
  }
}
```

返回 `201`。模板名称重复返回 `400`。

### 字段说明

| 字段 | 说明 |
|---|---|
| `objective` | 推广目标：`OUTCOME_SALES` / `OUTCOME_TRAFFIC` / `OUTCOME_ENGAGEMENT` / `OUTCOME_LEADS` / `OUTCOME_AWARENESS` |
| `budget_type` | `DAILY`（日预算）/ `LIFETIME`（总预算） |
| `optimization_goal` | 优化目标，如 `LINK_CLICKS` / `OFFSITE_CONVERSIONS` / `IMPRESSIONS` / `REACH` |
| `billing_event` | 计费事件，如 `IMPRESSIONS` / `LINK_CLICKS` |
| `targeting_json` | 定向配置（Meta 原生 targeting 结构，JSONB） |
| `placement_json` | 版位配置 |
| `creative_config_json` | 素材文案配置 |

> Meta 易变参数统一放 JSON 字段，API 参数变化时无需改表结构。

### PATCH /api/v1/templates/{template_id}

仅更新传入的字段（`exclude_unset=True`）。

### POST /api/v1/templates/{template_id}/clone

复制模板，新名称为 `原名称 - 副本`，返回 `201`。

---

## 9. 任务中心 `/api/v1/jobs`

批量投放、启停、改预算统一走异步 Job。全部需登录。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/jobs/campaign-create` | 批量创建 Campaign/AdSet/Ad |
| POST | `/api/v1/jobs/budget-update` | 批量修改预算 |
| POST | `/api/v1/jobs/pause` | 批量暂停 |
| POST | `/api/v1/jobs/enable` | 批量启用 |
| POST | `/api/v1/jobs/schedule` | 创建**定时**投放任务 |
| GET | `/api/v1/jobs/scheduled` | 待执行的定时任务列表 |
| GET | `/api/v1/jobs` | 任务列表 |
| GET | `/api/v1/jobs/{job_id}` | 任务详情（含子项，前端轮询） |
| POST | `/api/v1/jobs/{job_id}/dispatch-now` | 定时任务提前立即执行 |
| POST | `/api/v1/jobs/{job_id}/retry` | 只重跑失败子项 |
| POST | `/api/v1/jobs/{job_id}/cancel` | 取消任务 |

### POST /api/v1/jobs/campaign-create

```json
{
  "template_id": "xxx",
  "ad_account_ids": ["1", "2", "3"],
  "budget_override": 100,
  "status": "PAUSED"
}
```

响应（**立即返回，不等待 Meta API**）：

```json
{ "job_id": "xxx", "status": "PENDING", "total_accounts": 3, "scheduled_at": null }
```

- `budget_override` 留空则使用模板预算（美元/天）
- `status` 默认 `PAUSED`，避免创建后立即产生花费

随后前端轮询 `GET /api/v1/jobs/{job_id}` 查看进度。

### POST /api/v1/jobs/schedule（定时投放）

请求体在 `campaign-create` 基础上增加 `scheduled_at`：

```json
{
  "template_id": "xxx",
  "ad_account_ids": ["1", "2"],
  "budget_override": 100,
  "status": "PAUSED",
  "scheduled_at": "2026-08-30T18:00:00+08:00"
}
```

响应：

```json
{ "job_id": "xxx", "status": "QUEUED", "total_accounts": 2, "scheduled_at": "2026-08-30T10:00:00" }
```

约束与行为：

- `scheduled_at` 支持 ISO 8601，可带时区偏移（`+08:00`）或 `Z`；不带时区时按 UTC 处理
- **必须晚于当前时间**，否则返回 `400`
- 任务以 `QUEUED` 状态落库，由 Celery 的 `eta` 机制在指定时刻触发
- 返回的 `scheduled_at` 已换算为 UTC

### GET /api/v1/jobs/scheduled

查询参数：`limit`（默认 50，最大 200）

返回**尚未执行**的定时任务（`scheduled_at` 非空且状态为 `PENDING`/`QUEUED`），按计划执行时间升序。

### POST /api/v1/jobs/{job_id}/dispatch-now

把定时任务提前为立即执行。会先撤销 Celery 中原定的延迟投递，避免到点后重复执行。

返回更新后的 Job 对象。

### POST /api/v1/jobs/budget-update

```json
{ "template_id": "xxx", "ad_account_ids": ["1","2"], "budget_override": 150 }
```

`ad_account_ids` 省略时，自动取该模板**已部署的全部账户**（从 `campaign_instances` 反查）。

### POST /api/v1/jobs/pause  与  /enable

```json
{ "template_id": "xxx", "ad_account_ids": ["1","2"] }
```

### GET /api/v1/jobs

查询参数：`status`、`limit`（默认 50，最大 200）

```json
[
  {
    "id": "xxx",
    "template_id": "xxx",
    "action_type": "CREATE",
    "status": "PARTIAL_SUCCESS",
    "total_accounts": 100,
    "success_count": 93,
    "failed_count": 7,
    "params": { "budget_override": 100, "status": "PAUSED" },
    "created_by": "user_id",
    "error_message": null,
    "scheduled_at": null,
    "celery_task_id": null,
    "created_at": "2026-08-29T10:00:00",
    "started_at": "...",
    "finished_at": "..."
  }
]
```

### GET /api/v1/jobs/{job_id}

在列表结构基础上附加 `items` 数组：

```json
{
  "id": "xxx",
  "status": "PARTIAL_SUCCESS",
  "items": [
    {
      "id": "xxx",
      "job_id": "xxx",
      "ad_account_id": "1",
      "status": "FAILED",
      "meta_campaign_id": null,
      "adset_ids": null,
      "ad_ids": null,
      "error_code": "190",
      "error_message": "Access token has expired",
      "error_category": "AUTH",
      "retry_count": 1,
      "request_hash": "abc...",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### POST /api/v1/jobs/{job_id}/retry

只重跑 **FAILED** 子项，已成功的账户不受影响：

```json
{ "job_id": "xxx", "retried": 7 }
```

无失败项时返回 `400`。

### POST /api/v1/jobs/{job_id}/cancel

未完成的子项标记为 `SKIPPED`。

若该任务是尚未到点的定时任务，会同时调用 Celery 的 `revoke` 撤销延迟投递，
确保到点后不会被重复执行。

---

## 10. 广告系列 `/api/v1/campaigns`

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/accounts/{account_id}/campaigns` | 登录 | 本地已同步系列列表 |
| POST | `/api/v1/campaigns/batch-publish` | 登录 | 批量投放（旧接口） |
| POST | `/api/v1/campaigns/{campaign_id}/pause` | 登录 | 暂停系列 |
| POST | `/api/v1/campaigns/{campaign_id}/resume` | 登录 | 恢复系列 |

### POST /api/v1/campaigns/batch-publish

```json
{
  "account_id": "act_123",
  "campaigns": [ { "name": "系列A", "objective": "OUTCOME_SALES" } ],
  "publish_type": "immediate",
  "start_time": null,
  "interval_minutes": null,
  "max_daily_campaigns": 10,
  "enable_risk_check": true,
  "enable_frequency_check": true,
  "notify_on_complete": false,
  "notify_email": null
}
```

响应：

```json
{
  "status": "submitted",
  "account_id": "act_123",
  "campaign_count": 1,
  "publish_type": "immediate",
  "message": "批量投放任务已接收，将在后台处理"
}
```

触发频次上限时返回 `429`。

> 建议新功能改用 `/api/v1/jobs/campaign-create`（模板化 + 真实异步执行）。

### POST /api/v1/campaigns/{campaign_id}/pause

```json
{ "status": "success", "campaign_id": "123", "state": "PAUSED" }
```

系列不存在返回 `404`。Meta 调用失败时会记录警告，但本地状态仍更新。

---

## 11. 异步任务 `/api/v1/tasks`

Celery 任务提交与查询（与 Job Center 是两套体系：`tasks` 是单次 Celery 任务，`jobs` 是业务批量任务）。

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/tasks/fetch-insights` | 登录 | 提交拉取洞察任务 |
| POST | `/api/v1/tasks/generate-report` | 登录 | 提交报表生成任务 |
| GET | `/api/v1/tasks/{task_id}` | 登录 | 查询任务状态 |

### POST /api/v1/tasks/fetch-insights

查询参数：`account_id`

```json
{ "status": "submitted", "task_id": "celery-task-id", "account_id": "act_123" }
```

### POST /api/v1/tasks/generate-report

```json
{ "account_id": "act_123", "report_type": "daily", "date": "2026-08-28" }
```

`report_type` 仅支持 `daily` / `weekly`，否则 `400`。

### GET /api/v1/tasks/{task_id}

```json
{
  "task_id": "celery-task-id",
  "status": "SUCCESS",
  "result": { ... },
  "error": null
}
```

---

## 12. 系统

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/health` | 公开 | 健康检查 |

```json
{
  "status": "healthy",
  "app": "Facebook Ads Automation",
  "version": "1.0.0",
  "environment": "development"
}
```

---

## 附录 A：Job 状态机

任务状态：

```text
PENDING → VALIDATING → QUEUED → RUNNING → SUCCESS
                                        ├→ PARTIAL_SUCCESS（部分成功）
                                        └→ FAILED
                                  └→ CANCELLED
```

| 状态 | 含义 |
|---|---|
| `PENDING` | 已创建，等待执行 |
| `VALIDATING` | 校验中 |
| `QUEUED` | 已排程（定时任务：已投递到 Celery，等待到达 `scheduled_at`） |
| `RUNNING` | 执行中 |
| `SUCCESS` | 全部子项成功 |
| `PARTIAL_SUCCESS` | 部分成功（可重跑失败项） |
| `FAILED` | 全部失败 |
| `CANCELLED` | 已取消 |

子项状态：`PENDING` / `RUNNING` / `SUCCESS` / `FAILED` / `SKIPPED`

**部分成功语义**：100 个账户成功 93 个 → Job 为 `PARTIAL_SUCCESS`，
可只重跑失败的 7 个，而非全部 100 个。

---

## 附录 B：Meta 错误分类

`error_category` 取值与处理策略：

| 分类 | 触发场景 | 处理策略 |
|---|---|---|
| `AUTH` | Token 过期/失效（错误码 190/102/104 等） | 标记凭据 INVALID，更换 Token |
| `PERMISSION` | 权限不足（200/10/294，或 100+subcode 33） | 标记账户/凭据异常，不重试 |
| `VALIDATION` | 参数错误（100 及其他校验码） | 直接失败，不重试 |
| `RATE_LIMIT` | 限流（4/17/32/613/8000x） | 延迟后指数退避重试 |
| `TEMPORARY` | 超时 / 5xx / 服务暂不可用 | 指数退避重试 |
| `UNKNOWN` | 未归类 | 记录并失败 |

重试策略：`2s → 4s → 8s`，最多 3 次；仅对可重试分类生效。

---

## 附录 C：限流规则

基于 Redis 的账户维度窗口限流（`services/rate_limit.py`）：

| 窗口 | 上限 |
|---|---|
| 分钟 | 10 次 |
| 小时 | 200 次 |
| 天 | 10000 次 |

全局中间件 `RateLimitMiddleware` 对 `/api/v1/accounts/` 路径生效，超限返回 `429`。

Meta API 侧限流由 `MetaAdsService` 在调用前等待处理。

---

## 附录 D：已下线接口

| 原接口 | 状态 | 替代方案 |
|---|---|---|
| `POST /api/v1/publish/batch` | 已移除 | `POST /api/v1/jobs/campaign-create` |
| `GET /api/v1/publish/tasks` | 已移除 | `GET /api/v1/jobs` |

下线原因：同步阻塞（HTTP 请求内串行调用 Meta API）、
按「账户 × 素材 × 文案」笛卡尔积每个组合创建一个 Campaign，
不符合模板化部署模型。

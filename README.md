# Meta Ads 批量投流系统

面向 **多 Business Manager（BM）/ 多广告账户** 的 Meta Ads 批量投放与自动化管理平台。

> 完整的启动步骤见 **[docs/STARTUP.md](docs/STARTUP.md)**，
> 架构设计依据见 **[meta_ads_batch_delivery_system_design.md](meta_ads_batch_delivery_system_design.md)**。

## 🎯 项目概述

系统的核心抽象不是「BM × 广告账户」，而是：

> **一个 Campaign Template 如何被部署到多个 Ad Account。**

```text
Campaign Template
        │
   ┌────┼────┬────────┐
   ▼    ▼    ▼        ▼
Account A  B  C  ...  Account N
   │    │    │        │
Campaign  Campaign  Campaign ...     ← 模板的一次部署
   │
 AdSet
   │
  Ads
```

用户配置一次模板，即可批量部署到任意数量的广告账户；
规模从 20 个账户扩展到 5000 个，核心业务模型不变。

核心能力：

- **账号统一管理**：BM 主账号、广告账户、凭据分离管理
- **投放模板化**：Campaign Template（目标/预算/定向/素材/文案一次配置）
- **批量创建**：模板 → 多账户，异步生成 Campaign / AdSet / Ad
- **批量操作**：启停、预算调整（按模板批量作用于已部署实例）
- **异步任务队列**：Celery + Redis，HTTP 请求不阻塞
- **限流与重试**：Meta API 错误分类 + 指数退避 + 账户级限流
- **幂等与部分成功**：重复提交不重复创建，失败可单独重跑
- **实例映射**：Template × 账户 → Meta 对象 ID 的完整映射
- **数据报表**：洞察数据采集、日报/周报
- **风险控制**：风控事件检测与自动化处理

## 🏗 技术栈

| 层级 | 技术 |
|---|---|
| 后端 API | Python + FastAPI |
| ORM / 数据库 | SQLAlchemy 2.0 + PostgreSQL |
| Schema 校验 | Pydantic v2 |
| 异步队列 | Celery 5 |
| Cache / Broker | Redis |
| 定时调度 | **Celery Beat**（原 APScheduler 已迁移） |
| 数据库迁移 | **Alembic** |
| Meta SDK | facebook-business-sdk |
| 前端 | Vue3 + Vite + Element Plus |

## 📋 项目结构

```text
fb-ads/
├── main.py                  # FastAPI 入口（含中间件装配）
├── celery_app.py            # Celery 应用 + Beat 调度配置
├── celery_worker.py         # Worker 入口
├── cli.py                   # CLI 工具（建库/建管理员/启动组件/状态检查）
│
├── api/                     # API 路由层
│   ├── users.py             # 用户管理
│   ├── credentials.py       # ★ 凭据管理（Token 加密存、轮换/校验/启停）
│   ├── accounts.py          # 广告账户（归属过滤 / 转移 / 批量操作）
│   ├── meta_accounts.py     # BM 主账号（主数据，不存明文 Token）
│   ├── media.py             # 素材库
│   ├── templates.py         # 投放模板（核心）
│   └── jobs.py              # Job Center（异步批量投放入口）
│
├── models/                  # 数据模型（SQLAlchemy）
│   ├── meta_account.py      # BM 主账号
│   ├── ad_account.py        # 广告账户
│   ├── template.py          # ★ Campaign Template（核心业务对象）
│   ├── instance.py          # ★ Campaign/AdSet/Ad 三层实例映射
│   ├── credential.py        # ★ 加密凭据
│   ├── job.py               # ★ Job / JobItem（Job Center）
│   ├── audit_log.py         # ★ 审计日志
│   ├── campaign.py  ad_group.py  ad.py
│   ├── creative_asset.py    # 素材
│   ├── insights.py          # 洞察数据
│   ├── risk_control.py      # 风控事件/规则
│   ├── publish_task.py      # 旧同步发布任务（历史遗留）
│   └── user.py
│
├── services/
│   ├── meta/                # ★ Meta API 封装层（SDK 隔离）
│   │   ├── client.py        #   多账户独立 Session 客户端
│   │   ├── service.py       #   MetaAdsService（重试/限流/错误分类）
│   │   └── errors.py        #   错误分类（AUTH/PERMISSION/RATE_LIMIT...）
│   ├── campaign_builder.py  # ★ Campaign/AdSet/Creative/Ad Builder
│   ├── job_service.py       # ★ Job 创建与派发
│   ├── credential_service.py# ★ 凭据解析（账户 → 解密 Token）
│   ├── rate_limit.py        # 限流管理器
│   ├── fb_client.py         # 旧版客户端（历史遗留）
│   ├── ads_manager.py       # 广告同步/报表
│   ├── risk_detector.py     # 风控检测
│   ├── analytics.py         # 数据分析
│   └── notifications.py     # 通知
│
├── tasks/
│   ├── celery_tasks.py      # Celery 任务（洞察/风控/报表/通知）
│   └── campaign_tasks.py    # ★ 批量投放任务（Job 编排与执行）
│
├── core/
│   ├── database.py          # 引擎/Session/Base
│   ├── auth.py              # JWT 认证
│   ├── security.py          # ★ 凭据加解密（Fernet）
│   ├── audit.py             # ★ 审计日志写入（自动脱敏敏感字段）
│   ├── enums.py             # ★ 状态机/错误分类/动作类型
│   ├── middleware.py        # 日志/限流/统一鉴权中间件
│   ├── redis_client.py      # Redis 封装
│   └── logger.py
│
├── migrations/              # ★ Alembic 迁移
│   ├── env.py
│   └── versions/0001_campaign_template_and_jobs.py
├── scripts/
│   └── migrate_tokens_to_credentials.py   # ★ 明文 Token 加密迁移
├── docs/
│   └── STARTUP.md           # 启动流程文档
├── frontend/                # Vue3 前端
├── alembic.ini
└── requirements.txt
```

★ 标记为按设计文档新增/重构的模块。

## 🚀 快速开始

完整步骤见 [docs/STARTUP.md](docs/STARTUP.md)，摘要如下：

```bash
# 1. 安装依赖
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
cd frontend && npm install && cd ..

# 2. 配置环境变量
cp .env.example .env      # 重点：SECRET_KEY、DB_*、REDIS_*、FB_*

# 3. 初始化数据库结构（Alembic）
alembic upgrade head
# Windows 若提示命令未识别（venv 未激活），改用：
# .\venv\Scripts\python.exe -m alembic upgrade head

# 4. 迁移存量明文 Token 到加密凭据表（重要）
python scripts/migrate_tokens_to_credentials.py --dry-run
python scripts/migrate_tokens_to_credentials.py

# 5. 创建管理员
python cli.py create-admin
```

### 启动组件（需 4 个进程）

```bash
# 终端 1：API
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 终端 2：Worker（执行异步任务）
# Windows 上 prefork 多进程会报 WinError 5，必须加 --pool=solo；
# 也可直接用 CLI，它会按平台自动选择进程池：
python cli.py run-worker
# 等价于：
#   Windows   celery -A celery_app worker --loglevel=info --pool=solo
#   Linux/Mac celery -A celery_app worker --loglevel=info --concurrency=4

# 终端 3：Beat（定时触发，必须启动）
celery -A celery_app beat --loglevel=info

# 终端 4：前端
cd frontend && npm run dev
```

> **Beat 与 Worker 必须成对启动**：Beat 负责把定时任务投递到队列，
> Worker 负责执行；缺少任一方，定时任务都不会真正运行。

### Windows 一键脚本

| 脚本 | 作用 |
|---|---|
| `start_all_win.bat` | 一键启动全部：API + Worker + Beat + 前端 |
| `start_fb_ads.bat` | 仅 API |
| `start_celery_win.bat` | 仅 Worker（`--pool=solo`） |
| `start_beat_win.bat` | 仅 Beat 定时调度 |
| `start_frontend_win.bat` | 仅前端 |

## 🧩 核心架构

### 1. 批量投放链路

```text
选择模板 → 选择账户 → POST /api/v1/jobs/campaign-create
                              │
                              ▼  立即返回 job_id（不阻塞）
                        CampaignJob（PENDING）
                              │
                        Celery 派发（每账户一个子任务）
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                 Account A  Account B  Account C     ← 每账户独立状态
                    │
            CampaignDeploymentBuilder
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   Campaign      AdSet        Ads
        │
   写入 campaign_instances / adset_instances / ad_instances
```

- **原则一 模板优先**：一次配置，批量部署
- **原则二 任务异步**：HTTP 不等待 Meta API
- **原则三 每账户独立状态**：100 个账户不是一个状态
- **原则四 幂等**：`campaign_instances` 唯一约束 `(template_id, ad_account_id)`，Retry ≠ Duplicate
- **部分成功**：成功 93 / 失败 7 → `PARTIAL_SUCCESS`，可只重跑失败的 7 个

### 2. SDK 隔离（原则六）

业务代码不直接依赖 Meta SDK：

```text
业务层 → MetaAdsService → facebook_business → Meta Marketing API
```

`MetaAdsService` 统一处理：

- **错误分类**：`AUTH / PERMISSION / VALIDATION / RATE_LIMIT / TEMPORARY / UNKNOWN`
- **重试策略**：仅对 RATE_LIMIT、TEMPORARY 做指数退避（2s → 4s → 8s），参数错误直接失败
- **限流**：账户维度窗口限流，超限等待而非放行

### 3. 多账户凭据（原则：多 BM / 多账户）

`MetaClient` 为每个账户构造**独立 Session**，不使用 `FacebookAdsApi.init()`（全局单例，
在并发 Worker 下会串号）。凭据解析优先级：

```text
credentials 表（加密）→ meta_accounts.access_token（兼容历史明文）→ 全局配置兜底
```

### 4. 定时调度

定时任务由 **Celery Beat** 统一管理（原 APScheduler 已移除），
配置位于 `celery_app.conf.beat_schedule`：

| 任务 | 周期 | 环境变量 |
|---|---|---|
| `fetch-insights` | 每 2 小时 | `SCHEDULE_FETCH_INSIGHTS_CRON` |
| `risk-check` | 每小时 | `SCHEDULE_RISK_CHECK_CRON` |
| `daily-reports` | 每天 8 点 | `SCHEDULE_REPORT_DAILY_CRON` |
| `weekly-reports` | 每周一 9 点 | `SCHEDULE_REPORT_WEEKLY_CRON` |

## 🔌 API 文档

- **完整接口文档（按模块）**：[docs/API.md](docs/API.md)
- 交互文档（Swagger）：http://localhost:8000/docs

基础 URL：`http://localhost:8000`

> 所有 `/api/` 路径均需 `Authorization: Bearer <token>`（登录接口除外）。

### 投放模板

```http
GET    /api/v1/templates            # 列表（可 ?status=ACTIVE 过滤）
POST   /api/v1/templates            # 创建
GET    /api/v1/templates/{id}
PATCH  /api/v1/templates/{id}       # 局部更新
POST   /api/v1/templates/{id}/clone # 复制
DELETE /api/v1/templates/{id}       # 软删除（置 ARCHIVED）
```

创建模板示例：

```json
{
  "name": "US Sales V1",
  "objective": "OUTCOME_SALES",
  "budget_type": "DAILY",
  "daily_budget": 100,
  "optimization_goal": "OFFSITE_CONVERSIONS",
  "billing_event": "IMPRESSIONS",
  "targeting_json": { "geo_locations": { "countries": ["US"] }, "age_min": 18, "age_max": 65, "genders": [1, 2] },
  "creative_config_json": {
    "page_id": "xxx",
    "creatives": [
      { "headline": "标题", "primary_text": "正文", "description": "描述",
        "cta": "LEARN_MORE", "landing_url": "https://example.com", "image_hash": "xxx" }
    ]
  }
}
```

### Job Center（批量投放）

```http
POST   /api/v1/jobs/campaign-create   # 批量创建
POST   /api/v1/jobs/schedule          # 定时投放（指定执行时间）
GET    /api/v1/jobs/scheduled         # 待执行的定时任务
POST   /api/v1/jobs/budget-update     # 批量改预算
POST   /api/v1/jobs/pause             # 批量暂停
POST   /api/v1/jobs/enable            # 批量启用
GET    /api/v1/jobs                   # 任务列表
GET    /api/v1/jobs/{id}              # 详情（含子项，前端轮询进度）
POST   /api/v1/jobs/{id}/dispatch-now # 定时任务提前立即执行
POST   /api/v1/jobs/{id}/retry        # 只重跑失败子项
POST   /api/v1/jobs/{id}/cancel       # 取消
```

> **定时投放**复用 Job 体系：创建时传入 `scheduled_at`，任务以 `QUEUED` 落库，
> 由 Celery 的 eta 机制在指定时刻触发；取消时会 revoke 撤销，避免重复执行。

提交批量创建：

```json
// 请求
{ "template_id": "xxx", "ad_account_ids": ["1","2","3"], "budget_override": 100, "status": "PAUSED" }

// 响应（立即返回，不等待 Meta API）
{ "job_id": "xxx", "status": "PENDING", "total_accounts": 3 }
```

任务状态机：

```text
PENDING → VALIDATING → QUEUED → RUNNING → SUCCESS
                                        ├→ PARTIAL_SUCCESS（部分成功）
                                        └→ FAILED / CANCELLED
```

子项状态：`PENDING / RUNNING / SUCCESS / FAILED / SKIPPED`

### 其他

```http
/api/v1/auth          # 登录 / 当前用户
/api/v1/bms（现 meta-accounts）  # BM 主账号
/api/v1/accounts      # 广告账户（同步/冻结/分配等）
/api/v1/media         # 素材库
/api/v1/users         # 用户管理
```

> 旧接口 `POST /api/v1/publish/batch` **已下线**（同步阻塞 + 笛卡尔积爆炸），
> 请改用 `/api/v1/jobs/campaign-create`。

## 🔐 凭据安全

三层分离（管理后台 → 主账号管理 / 凭据管理 / 广告账户）：

```text
BM 主账号 meta_accounts        广告账户 ad_accounts
    │  只存主数据                   │  只存 meta_account_id
    │  不存明文 Token               │  不存任何 Token
    └──────────► 凭据 credentials ◄┘
                  Fernet 加密存储
                  过期检测 / 失效标记 / 轮换
```

- Access Token 加密存储于 `credentials` 表（Fernet，密钥由 `SECRET_KEY` 派生）
- 前端永不接触明文 Token；API 默认返回脱敏值（`EAAA...9zQd`）
- 查看明文需走 `POST /api/v1/credentials/{id}/reveal` 且显式 `confirm=true`，**写入审计日志**
- Token 支持过期检测（`expires_at`）与权限异常标记（`status=INVALID`）
- 解析优先级：`credentials`（加密）→ `meta_accounts.access_token`（历史明文兼容）→ 全局配置兜底
- **过期凭据不回退全局 Token**：多 BM 场景下回退会造成"用 A 的身份操作 B 的账户"的串号事故
- 迁移存量明文数据：

```bash
python scripts/migrate_tokens_to_credentials.py --dry-run
python scripts/migrate_tokens_to_credentials.py
python scripts/migrate_tokens_to_credentials.py --purge   # 确认无误后清空明文列
```

> ⚠️ `SECRET_KEY` 变更后历史密文无法解密，请务必备份。

## 🗄 数据库迁移

```bash
alembic upgrade head                              # 升级
alembic revision --autogenerate -m "说明"         # 生成新迁移
alembic current / history                         # 查看版本
```

存量库（早期由 `create_all` 建表）接入方式见 [docs/STARTUP.md](docs/STARTUP.md#4-初始化数据库)。

## 📊 数据模型关系

### 账号资源池（Meta 账号管理 V1）

```text
Credential (credentials，Fernet 加密)
    │  一个 BM 可有多条凭据，轮换时旧的转 DISABLED 留痕
    ▼
MetaAccount (meta_accounts = businesses)
    │  status      业务状态 ACTIVE / DISABLED / ARCHIVED（人工维护）
    │  sync_status 同步状态 PENDING / SYNCING / SUCCESS / FAILED（同步维护）
    │
    └─1:N─► AdAccount (ad_accounts)
                business_id + account_id 唯一（同一 act_xxx 可挂多个 BM）
                account_status / effective_status  Meta 侧（同步覆盖）
                system_status                      系统侧（同步不覆盖）
                    ↓
                available-for-deployment 可投放账户池
```

`meta_sync_logs` 记录每次**同步**的结果（成功/失败数、错误明细）；
`audit_logs` 记录**人的操作**审计。两者职责分离，不混用。

### 投放链路

```text
CampaignTemplate
    │ (template_id, ad_account_id) 唯一
    ├─► CampaignInstance ── AdSetInstance ── AdInstance
    │
    └─► CampaignJob ── CampaignJobItem（每账户一条，含幂等 hash）

AdAccount ├─ Campaign ─ AdGroup ─ Ad
          ├─ AccountInsight / CampaignInsight / AdInsight
          └─ RiskEvent
```

### 金额约定

所有金额字段一律 **BIGINT 最小货币单位**（`$10.50` → `1050`），避免浮点精度问题：

| 范围 | 字段 |
|---|---|
| 账户 | `spend_cap` / `amount_spent` / `balance` / `daily_spend_limit` / `monthly_spend_limit` |
| 投放 | `campaign_templates.daily_budget` / `lifetime_budget`、`publish_tasks.daily_budget` |
| 数据 | `campaigns` / `ad_groups` / `ads` 的 `spend`、`budget`、`daily_budget`、`bid_amount`；三张 `*_insights` 的 `spend` |

- 后端换算：`core/money.py`（`to_minor` / `to_major` / `format_money`）
- 前端换算：`frontend/src/utils/money.ts`
- **例外**：`ctr` / `cpc` / `cpm` / `roas` / `conversion_rate` / `risk_score` / `fraud_score`
  是派生指标不是金额，保持浮点；但计算它们时需先转主单位。

## 🛡 风险控制

- 异常花费、低质量广告、欺诈模式、政策违规检测
- 自动暂停低效系列、冻结高风险账户、发送告警

```env
RISK_DAILY_SPEND_LIMIT=10000
RISK_DAILY_CTR_THRESHOLD=0.02
RISK_DAILY_CPC_THRESHOLD=5.0
RISK_FRAUD_SCORE_THRESHOLD=0.7
RISK_ACCOUNT_FREEZE_DAYS=3
```

## 🐳 Docker 部署

```yaml
services:
  postgres:
    image: postgres:14
    environment:
      POSTGRES_DB: fb_ads_db
      POSTGRES_PASSWORD: password

  redis:
    image: redis:7

  api:
    build: .
    command: uvicorn main:app --host 0.0.0.0 --port 8000
    ports: ["8000:8000"]
    depends_on: [postgres, redis]

  worker:
    build: .
    command: celery -A celery_app worker --loglevel=info
    depends_on: [postgres, redis]

  beat:
    build: .
    command: celery -A celery_app beat --loglevel=info
    depends_on: [postgres, redis]

  frontend:
    build: ./frontend
    ports: ["5173:80"]
    depends_on: [api]
```

> `beat` 为单点服务，**不要**部署多个副本，否则定时任务会重复触发。

## 🧪 运行测试

```bash
python -m pytest tests -q
```

- 测试使用 `tests/conftest.py` 中的独立 SQLite 库并在事务内回滚，**不会写入开发/生产库**。
- `TestClient` 依赖 `httpx`，已列入 `requirements.txt`；缺失时 `tests/conftest.py` 会直接导入失败。
- 新增用例请统一使用 conftest 的 `db` fixture，不要在用例里 `SessionLocal()` 直接连业务库。
- 接口级用例见 `tests/test_account_management.py`：独立内存库 + 真实 JWT 鉴权，
  覆盖「BM 主账号 / 凭据 / 广告账户」三层分离管理（含加密存储、脱敏、轮换、批量操作）。

## 🔧 开发指南

**新增 Meta API 能力**：在 `services/meta/service.py` 中添加方法，业务层只调用该服务，不直接 import SDK。

**新增异步任务**：

```python
# tasks/campaign_tasks.py
@shared_task(bind=True, name="campaign.my_task")
def my_task(self, job_item_id: str):
    ...
```

> **新增任务模块后必须在 `celery_app.py` 中显式导入**。
> `autodiscover_tasks(['tasks'])` 只导入 `tasks` 包本身，不会递归导入子模块；
> 漏了这一步，Worker 会报 `Received unregistered task`，Job 永远卡在 `QUEUED`。

**新增定时任务**：在 `celery_app.conf.beat_schedule` 中注册，重启 Beat 生效。

**新增 API**：在 `api/` 下新建模块（统一 `prefix="/api/v1/..."`），并在 `main.py` 中 `include_router`。

## 📝 日志

- 位置：`logs/app.log`
- 控制台：文本格式；文件：JSON 格式
- 敏感信息（Token）自动脱敏，不写入普通日志

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改
4. 推送分支并开启 Pull Request

## 📄 许可

MIT License

---

**最后更新**：2026-08-29

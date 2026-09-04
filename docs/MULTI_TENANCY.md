# 多租户（SaaS 租户隔离）设计

> 目标：把「用户隔离」从**开发约定**变成**框架强制**。
> 相关代码：`core/tenant.py`、`models/tenant.py`、`migrations/versions/0006_multi_tenant.py`

---

## 一、模式选型

| 模式 | 隔离性 | 运维成本 | 租户规模上限 | 本项目 |
|---|---|---|---|---|
| 1. 独立数据库（Database per Tenant） | ★★★★★ | 极高（每次 DDL × N） | ~百级 | ✗ |
| 2. 独立 Schema（Schema per Tenant） | ★★★★ | 高（连接路由复杂） | ~千级 | ✗ |
| 3. **共享表 + tenant_id 行级隔离** | ★★★ | 低（一套表、一套迁移） | 百万级 | ✅ 采用 |

选型理由：

- 租户多、单租户数据量不大，模式 1/2 的运维成本远大于收益
- 需要跨租户统计（平台运营看板）与统一版本升级
- 模式 3 的唯一风险——**漏写 `WHERE tenant_id = ?`**——由本设计的四道防线消除

> 进阶：若未来出现强合规大客户，可为其单独部署实例（模式 1），
> 代码无需改动——`tenant_id` 天然兼容"单租户单库"。

---

## 二、数据模型

### 2.1 三层结构

```
tenants（租户/组织，隔离根节点）
 ├── users                    租户成员（tenant_id 可空 → 平台管理员）
 ├── meta_accounts（BM）      ── 唯一约束 (tenant_id, business_id)
 │    ├── ad_accounts         ── 核心资产
 │    │    ├── campaigns → ad_groups → ads
 │    │    ├── account_insights / risk_events
 │    ├── credentials        加密 Token，租户级敏感数据
 │    └── meta_sync_logs
 ├── creative_assets          素材
 ├── campaign_templates       投放模板
 │    └── campaign_instances → adset_instances → ad_instances
 ├── campaign_jobs → campaign_job_items
 ├── publish_tasks → published_ads
 └── audit_logs               操作审计（tenant_id 可空 → 平台级操作）

risk_rules                    平台共享 + 租户覆盖（tenant_id 可空 → 平台内置）
```

### 2.2 两种隔离级别

| Mixin | 语义 | tenant_id | 查询条件 | 用于 |
|---|---|---|---|---|
| `TenantMixin` | 严格隔离 | NOT NULL | `tenant_id = :current` | 绝大多数业务表 |
| `SharedTenantMixin` | 平台共享 + 租户覆盖 | 可空 | `tenant_id = :current OR tenant_id IS NULL` | `risk_rules` |

例外说明：

- `users.tenant_id` 可空 → **平台管理员**不属于任何租户，用于跨租户运维
- `audit_logs.tenant_id` 可空 → 平台级操作（开通租户等）不属于任何租户
- `risk_rules.tenant_id` 为空 → 平台内置规则，所有租户可见且**只读**

### 2.3 租户表字段

`tenants`：`id / name / slug(唯一) / status / plan / 联系人 / 配额 / features / settings / expires_at`

- 配额字段 `max_users`、`max_meta_accounts`、`max_ad_accounts`、`max_templates`：
  **NULL = 不限制，0 = 禁止**（不要用 0 表示不限，语义容易反）
- 状态：`ACTIVE`（正常）/ `SUSPENDED`（欠费停用，只读）/ `ARCHIVED`（归档）
- `Tenant.check_quota(name, used)` 统一判断配额

---

## 三、强制隔离机制（四道防线）

### 防线 1：模型层

租户级表必须继承 `TenantMixin`，否则不该被建出来。

```python
class AdAccount(TenantMixin, Base):
    __tablename__ = "ad_accounts"
```

### 防线 2：读 —— 全局 ORM 事件自动注入 WHERE

`core/tenant.py` 通过 SQLAlchemy 的 `do_orm_execute` 事件，给**所有** ORM 查询
自动加上租户条件，覆盖：

- `session.query(Model)` / `select(Model)`
- JOIN 后的别名实体（`include_aliases=True`）
- **relationship 的 lazy load**（防止通过 `bm.ad_accounts` 这类关系越权读取）

```python
@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state):
    ...
    state.statement = state.statement.options(
        with_loader_criteria(TenantMixin, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(SharedTenantMixin,
                             lambda cls: or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None)),
                             include_aliases=True),
    )
```

### 防线 3：写 —— 自动填充 + 越权拦截

`before_flush` 事件：

1. 新建对象 `tenant_id` 为空 → 自动填当前租户
2. **无租户上下文且未显式指定 `tenant_id` → 直接拒绝**（见下方"写入侧始终严格"）
3. 把对象 `tenant_id` 改成别的租户 → 抛 `PermissionError`（防"数据搬家"）
4. 修改平台共享数据（`tenant_id` 为空的记录）→ 抛 `PermissionError`

> `SharedTenantMixin` 的表**故意不自动填充**：空值代表"平台内置数据"，
> 是合法取值。业务代码要给租户创建自定义规则时必须**显式**传 `tenant_id`。

### 防线 4：上下文 —— ContextVar 随请求/任务生命周期绑定

租户 ID 存在 `ContextVar` 中，天然并发安全，不需要给每个函数传参数。

```python
with tenant_scope("tenant_abc"):      # 切换到指定租户
    ...
with bypass_tenant():                 # 绕过过滤（仅限平台运营/系统任务）
    ...
```

---

## 四、请求链路

```
登录 /api/v1/auth/login
    └─ 签发 JWT：{sub: user_id, tid: tenant_id, role, ...}
            │
            ▼
HTTP 请求（Authorization: Bearer <jwt>）
    │
    ├─ AuthEnforcementMiddleware：校验令牌合法性（白名单路由除外）
    │
    ├─ Depends(get_db)                       ← 隔离主入口（async generator）
    │      └─ 从 JWT 的 tid claim 解析租户 → set_current_tenant_id()
    │
    ├─ Depends(get_current_active_user)      ← 用库里的实时 tenant_id 覆盖一次
    │
    └─ 路由 / Service 层：正常写 db.query(...)，租户条件自动注入
```

两个关键实现细节：

1. **`get_db` 必须是 async generator**。FastAPI 会把同步依赖放到线程池执行，
   线程池内对 `ContextVar` 的修改**不会**传播回主上下文；async 依赖在主上下文
   执行，其设置的值能被后续（包括线程池中的同步路由）继承。
   因此**所有** `Depends(get_db)` 的路由自动获得隔离能力，即使该路由
   没有显式依赖 `get_current_active_user`。

2. **令牌里带 `tid`**，让 `get_db` 在没有 `current_user` 依赖时也能建立上下文。
   同时 `get_current_active_user` 会用数据库里的实时 `tenant_id` 覆盖一次，
   避免令牌过期后租户归属不一致。

---

## 五、Celery 任务接入

Worker 没有 HTTP 请求，必须自己建立租户上下文，否则：
新建记录的 `tenant_id` 为 NOT NULL 会直接报错。

```python
from core.tenant import for_all_tenants, resolve_tenant_of, tenant_task

# 单租户任务：先按 job_id 解析租户，再在租户上下文中执行任务体
@shared_task(bind=True, name="campaign.execute_job")
@tenant_task(lambda self, job_id: resolve_tenant_of(CampaignJob, job_id))
def execute_campaign_job(self, job_id: str):
    ...

# 编排任务：需要遍历所有租户 → 显式绕过过滤
@shared_task(bind=True, name="meta.sync_all_businesses")
@for_all_tenants
def sync_all_businesses_task(self):
    ...
```

已接入：`tasks/campaign_tasks.py`、`tasks/meta_sync_tasks.py`、`tasks/celery_tasks.py`。

---

## 六、索引与性能

行级隔离下，**高频查询索引必须以 `tenant_id` 打头**，
否则单租户的数据被全表数据淹没，索引选择性极差。

迁移 0006 已按此原则重建索引（示例）：

| 表 | 索引 |
|---|---|
| `ad_accounts` | `(tenant_id, business_id)`、`(tenant_id, system_status)`、`(tenant_id, account_status)` |
| `account_insights` | `(tenant_id, ad_account_id, date)`、`(tenant_id, date)` |
| `campaign_jobs` | `(tenant_id, status)`、`(tenant_id, created_at)` |
| `audit_logs` | `(tenant_id, created_at)`、`(tenant_id, resource_type, resource_id)` |

**新表 checklist**：加 `tenant_id` 列 → 加外键 → 加 `(tenant_id, 高频过滤列)` 复合索引。

---

## 七、迁移与历史数据

```bash
alembic upgrade head     # 执行 0006_multi_tenant
```

0006 做的事（**保留全部历史数据**）：

1. 建 `tenants` 表
2. 创建默认租户 `default`，把**所有历史数据回填**到该租户
   （先加可空列 → 回填 → 再收紧 NOT NULL）
3. 加索引、外键、复合索引
4. 唯一约束调整
   - `meta_accounts.business_id` 全局唯一 → `(tenant_id, business_id)` 唯一
   - `risk_rules.name` 全局唯一 → 平台/租户两组**部分唯一索引**
5. `users.role`：`admin` → `tenant_admin`

初始化管理员：

```bash
python cli.py create-admin                       # 归属 default 租户的租户管理员
python cli.py create-admin --platform            # 跨租户的平台管理员
python cli.py create-admin --tenant-slug acme    # 指定租户
```

---

## 八、开发规范

### ✅ 正确

```python
# 普通业务代码：什么都不用做，自动隔离
accounts = db.query(AdAccount).filter(AdAccount.system_status == "ACTIVE").all()

# 按 id 查询拿不到别的租户数据 → 直接返回 404
account = db.query(AdAccount).filter(AdAccount.id == account_id).first()
if not account:
    raise HTTPException(404, "账户不存在")
```

### ⚠️ 需要显式声明的场景

```python
# 平台运营跨租户查询
with bypass_tenant():
    total = db.query(AdAccount).count()

# 定时任务按对象归属切换租户
with tenant_scope(job.tenant_id):
    ...

# 给租户创建"平台共享表"的自定义记录 → 必须显式传 tenant_id
db.add(RiskRule(name="我的规则", rule_type="fraud", tenant_id=current_user.tenant_id))
```

### ❌ 禁止

- 在业务接口里用 `bypass_tenant()`（只有 `require_platform_admin` 的接口可以）
- 手工拼接 `UPDATE ... SET tenant_id = ...` 迁移数据（会被守卫拦截，走 Alembic）
- 新增租户级业务表时不继承 `TenantMixin`

### 严格模式

`settings.TENANT_STRICT_MODE = True`（生产建议开启）后：
执行租户级查询却没有租户上下文时**直接抛错**，而不是"不过滤返回全量"。
宁可报错，也绝不返回跨租户数据。

- API 进程在 `init_db()` 时按该配置设置
- **Worker 进程在 `celery_app.py` 中按同一配置设置**。
  这一点很关键：Worker 不走 `init_db()`，若不单独设置，某条任务的租户解析
  失败时会退化成"不加任何过滤"的跨租户裸读
- `PermissionError` 由 `main.py` 的全局异常处理器转成 **403 + `detail`**，
  不会退化成 500

### 写入侧始终严格

写入守卫**不受** `TENANT_STRICT_MODE` 控制——租户级表的 `tenant_id` 是 NOT NULL，
无上下文写入必然失败，早失败并给出明确信息好过数据库抛 `IntegrityError`。

典型触发场景：**平台管理员（`tenant_id` 为空）直接调用业务创建接口**。
平台账号只能做平台级操作（开通租户、跨租户查询），
要操作具体业务数据必须先切换到目标租户，或在创建对象时显式传 `tenant_id`。

`bypass_tenant()` 同理：它只放开**读**过滤，不允许创建无主数据。

---

## 九、接口清单

| 方法 | 路径 | 权限 |
|---|---|---|
| GET | `/api/v1/tenants/current` | 租户成员 |
| PATCH | `/api/v1/tenants/current` | 租户管理员 |
| GET | `/api/v1/tenants` | 平台管理员 |
| POST | `/api/v1/tenants` | 平台管理员（开通租户 + 管理员账号） |
| POST | `/api/v1/tenants/{id}/status` | 平台管理员（启停/归档） |
| GET | `/api/v1/tenants/{id}/usage` | 平台管理员（配额用量） |

登录响应新增 `user.tenant_id` 与 `user.is_platform_admin`；
`/api/v1/auth/me` 同步返回。

---

## 十、验证清单

上线前建议逐条验证：

- [ ] 租户 A 的账号登录后，看不到租户 B 的账户/模板/任务/素材
- [ ] 租户 A 直接拿租户 B 的资源 id 调详情接口 → 404 而非 200
- [ ] 租户 A 创建的数据自动带上自己的 `tenant_id`
- [ ] 租户 A 无法修改平台内置风控规则
- [ ] 平台管理员能看到全部租户；`GET /api/v1/tenants/{id}/usage` 正确统计
- [ ] Celery 任务（Job 执行、Meta 同步、洞察拉取）写入的 `tenant_id` 正确
- [ ] 定时任务（跨租户编排）能遍历全部账户
- [ ] 平台管理员调业务创建接口返回 **403 明确提示**，而不是 500
- [ ] `TENANT_STRICT_MODE=true` 下，API 与 Worker 行为一致

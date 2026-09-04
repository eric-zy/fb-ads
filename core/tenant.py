"""多租户隔离核心（SaaS Tenant Isolation）

==========================================================================
一、模式选型
==========================================================================
SaaS 三种主流租户隔离模式：

┌─────────────────────┬────────┬──────────┬──────────┬──────────────────┐
│ 模式                │ 隔离性 │ 运维成本 │ 扩展上限 │ 适用场景          │
├─────────────────────┼────────┼──────────┼──────────┼──────────────────┤
│ 1. 独立数据库        │ ★★★★★ │ 极高     │ ~百级    │ 金融/医疗强合规   │
│ 2. 独立 Schema       │ ★★★★  │ 高       │ ~千级    │ 中大型 B 端       │
│ 3. 共享表 + tenant_id│ ★★★   │ 低       │ 百万级   │ 通用 SaaS（本项目）│
└─────────────────────┴────────┴──────────┴──────────┴──────────────────┘

本项目采用 **模式 3：共享库 + 共享 Schema + tenant_id 行级隔离**。
原因：租户数量多、单租户数据量不大、需要跨租户统计与统一升级；
模式 1/2 每次 DDL 都要按租户重复执行，在这个体量下不划算。

模式 3 的唯一风险是"代码漏写 WHERE tenant_id = ?"，因此本模块用
**ORM 全局事件**把隔离从"约定"升级为"框架强制"，见下文第三节。

==========================================================================
二、三层模型
==========================================================================
    tenants（租户/组织）
        ├── users        租户下的账号
        ├── meta_accounts（BM）
        │       ├── ad_accounts
        │       │       ├── campaigns → ad_groups → ads
        │       │       ├── account_insights / risk_events
        │       ├── credentials（加密 Token）
        │       └── meta_sync_logs
        ├── creative_assets（素材）
        ├── campaign_templates → campaign_instances → adset_instances → ad_instances
        ├── campaign_jobs → campaign_job_items
        ├── publish_tasks → published_ads
        └── audit_logs

    risk_rules 为"平台共享 + 租户覆盖"表（tenant_id 可为 NULL）。

==========================================================================
三、强制隔离机制（四道防线）
==========================================================================
1. 【模型层】租户级业务表必须继承 `TenantMixin`，强制带 `tenant_id` 外键
2. 【读】`do_orm_execute` 事件给所有 SELECT 自动注入
   `WHERE tenant_id = :current_tenant`（含 lazy load 关系，防侧信道泄漏）
3. 【写】`before_flush` 事件给所有新对象自动填充 `tenant_id`；
   并拦截"把对象改到别的租户"的越权 UPDATE
4. 【上下文】租户 ID 存在 `ContextVar` 中，随请求/任务生命周期绑定，
   线程池 / asyncio 并发下天然隔离，不需要给每个函数传 tenant_id 参数

需要跨租户访问（平台运营后台、定时任务）时，必须**显式**声明：

    with bypass_tenant():                 # 关闭过滤（仅限平台管理员/系统任务）
        rows = db.query(User).all()

    with tenant_scope("tenant_abc"):      # 切换到指定租户
        do_something()

==========================================================================
四、性能约定
==========================================================================
行级隔离下，**所有高频查询索引必须以 tenant_id 打头**，
否则单租户数据被全表数据淹没，索引选择性极差。
迁移脚本已按此原则重建复合索引。
"""
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator, Optional

from sqlalchemy import Column, ForeignKey, String, event, or_
from sqlalchemy.orm import (
    ORMExecuteState,
    Session,
    declared_attr,
    relationship,
    with_loader_criteria,
)
from sqlalchemy.orm.attributes import get_history

from core.logger import logger


# --------------------------------------------------------------------------
# 上下文变量
# --------------------------------------------------------------------------
# 当前租户 ID。None 表示"无租户上下文"：
#   - 未登录请求（登录接口本身）
#   - 系统级任务（Celery 定时任务、数据回填脚本）
# 此时不加过滤，由调用方自行保证安全。
_current_tenant_id: ContextVar[Optional[str]] = ContextVar(
    "current_tenant_id", default=None
)

# 过滤总开关。平台管理员跨租户查询时置为 False。
_tenant_filter_enabled: ContextVar[bool] = ContextVar(
    "tenant_filter_enabled", default=True
)

# 严格模式：为 True 时，执行租户级查询却没有租户上下文直接抛错，
# 宁可报错也绝不返回跨租户数据。由 settings.TENANT_STRICT_MODE 控制。
_tenant_strict: ContextVar[bool] = ContextVar("tenant_strict", default=False)


# --------------------------------------------------------------------------
# 租户混入类
# --------------------------------------------------------------------------
class TenantMixin:
    """租户级数据混入：注入 `tenant_id` 外键。

    继承后该表自动获得：
        - 列：`tenant_id`（外键 tenants.id，带索引）
        - 关系：`tenant`
        - SELECT 自动过滤、INSERT 自动填充（由本模块事件驱动）

    子类可覆盖的类属性：
        `__tenant_nullable__ = True`  → 允许 tenant_id 为空
            （如 users：平台管理员不属于任何租户，需要跨租户操作）

    注意：子类若自行定义 `__table_args__`，请**手动**把 `tenant_id`
    加入复合索引（行级隔离下索引必须以 tenant_id 打头，否则选择性极差）。
    """

    __tenant_filter__ = "strict"  # 严格隔离：仅本租户可见
    __tenant_nullable__ = False

    @declared_attr
    def tenant_id(cls):
        return Column(
            String(50),
            ForeignKey("tenants.id"),
            nullable=cls.__tenant_nullable__,
            index=True,
            comment="所属租户（行级隔离键）",
        )

    @declared_attr
    def tenant(cls):
        return relationship("Tenant")

    @property
    def tenant_scoped(self) -> bool:  # pragma: no cover - 语义标记
        return True


class SharedTenantMixin:
    """平台共享 + 租户覆盖数据混入（如风控规则模板）。

    `tenant_id IS NULL` → 平台内置数据，所有租户可见
    `tenant_id = X`     → 租户 X 自定义数据，仅 X 可见

    查询条件为：`tenant_id = :current OR tenant_id IS NULL`
    """

    __tenant_filter__ = "shared"
    __tenant_nullable__ = True

    @declared_attr
    def tenant_id(cls):
        return Column(
            String(50),
            ForeignKey("tenants.id"),
            nullable=True,
            index=True,
            comment="所属租户；NULL = 平台内置数据（所有租户可见）",
        )

    @declared_attr
    def tenant(cls):
        return relationship("Tenant")


# --------------------------------------------------------------------------
# 上下文读写 API
# --------------------------------------------------------------------------
def get_current_tenant_id() -> Optional[str]:
    """获取当前租户 ID（无上下文时返回 None）"""
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id: Optional[str]) -> Optional[Token]:
    """设置当前租户 ID，返回可用于还原的 Token"""
    return _current_tenant_id.set(tenant_id)


def reset_current_tenant_id(token: Optional[Token]) -> None:
    """还原租户上下文"""
    if token is not None:
        try:
            _current_tenant_id.reset(token)
        except ValueError:
            # Token 来自另一个 Context（如线程池复制），忽略即可
            pass


def set_strict_mode(enabled: bool) -> None:
    """开启/关闭严格模式（生产建议开启，见文档第六节）"""
    _tenant_strict.set(bool(enabled))


@contextmanager
def tenant_scope(tenant_id: Optional[str]) -> Iterator[None]:
    """切换租户上下文

    典型场景：Celery 异步任务按账户所属租户执行。

        @celery_app.task
        def sync_business(meta_account_id: str):
            with tenant_scope(resolve_tenant(meta_account_id)):
                ...
    """
    token = set_current_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_current_tenant_id(token)


@contextmanager
def bypass_tenant() -> Iterator[None]:
    """绕过租户过滤（跨租户查询）

    ⚠️ 仅限：平台运营后台、数据迁移脚本、定时任务。
    业务接口一律禁止使用——使用者必须自行校验调用者权限。
    """
    token = _tenant_filter_enabled.set(False)
    try:
        yield
    finally:
        _tenant_filter_enabled.reset(token)


def is_filtering_enabled() -> bool:
    """当前是否启用了租户过滤"""
    return _tenant_filter_enabled.get()


def resolve_tenant_from_token(token: str) -> Optional[str]:
    """从 JWT 中解析租户 ID（`tid` claim）

    登录接口会把 `tenant_id` 写入 token 的 `tid` claim，
    这样即使某个路由忘了加 `Depends(get_current_active_user)`，
    `get_db` 也能直接依据 token 建立租户上下文——这是隔离的兜底防线。

    解析失败一律返回 None（绝不抛异常）：
    令牌本身的合法性由 `AuthEnforcementMiddleware` 与 `get_current_active_user`
    负责校验，这里只负责"尽力而为"地提取租户。
    """
    if not token:
        return None
    try:
        import jwt  # 局部导入，避免 core.tenant 与 core.auth 循环依赖

        from config.settings import settings

        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False}
        )
    except Exception:  # noqa: BLE001 - 任何解析异常都视为"无租户上下文"
        return None
    return payload.get("tid") or payload.get("tenant_id")


def resolve_tenant_from_request(request) -> Optional[str]:
    """从 HTTP 请求的 Authorization 头解析租户 ID"""
    header = None
    try:
        header = request.headers.get("Authorization")
    except Exception:  # pragma: no cover - 非标准 request 对象
        return None
    if not header or not header.startswith("Bearer "):
        return None
    return resolve_tenant_from_token(header.split(" ", 1)[1])


def resolve_tenant_of(model, value, column: str = "id") -> Optional[str]:
    """按主键/业务键解析某条记录所属的租户（用于 Celery 任务）

    任务只收到 `job_id` / `account_id`，而租户上下文必须自己建立，
    因此统一走这里查一次归属租户。

    Args:
        model:  模型类（如 CampaignJob）
        value:  要匹配的值
        column: 匹配列名，默认主键 `id`
    """
    from core.database import SessionLocal

    db = SessionLocal()
    try:
        with bypass_tenant():
            obj = db.query(model).filter(getattr(model, column) == value).first()
        return getattr(obj, "tenant_id", None) if obj else None
    except Exception as e:  # noqa: BLE001 - 解析失败不应让任务崩溃
        logger.warning(f"[tenant] 解析 {model.__name__}.{column}={value} 的租户失败: {e}")
        return None
    finally:
        db.close()


def tenant_task(resolver):
    """Celery 任务装饰器：先解析租户，再在租户上下文中执行任务体

    用法（`@shared_task` 在外层，本装饰器在内层）：

        @shared_task(bind=True, name="campaign.execute_job")
        @tenant_task(lambda self, job_id: resolve_tenant_of(CampaignJob, job_id))
        def execute_campaign_job(self, job_id: str):
            ...

    任务体内创建的 ORM 对象会自动带上正确的 tenant_id，
    查询也只在本租户范围内进行。
    """
    import functools

    def decorator(task_fn):
        @functools.wraps(task_fn)
        def wrapper(*args, **kwargs):
            try:
                tenant_id = resolver(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[tenant] 租户解析异常，任务将在无租户上下文下执行: {e}")
                tenant_id = None
            with tenant_scope(tenant_id):
                return task_fn(*args, **kwargs)

        return wrapper

    return decorator


def for_all_tenants(task_fn):
    """Celery 编排任务装饰器：跨租户执行（如"遍历所有账户派发子任务"）

    编排任务本身需要看到全量数据，因此绕过租户过滤；
    它派发出的子任务仍应通过 `tenant_task` 建立各自的租户上下文。
    """
    import functools

    @functools.wraps(task_fn)
    def wrapper(*args, **kwargs):
        with bypass_tenant():
            return task_fn(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------
# 全局 ORM 事件：读过滤
# --------------------------------------------------------------------------
@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(orm_execute_state: ORMExecuteState) -> None:
    """给所有 ORM SELECT 自动注入租户过滤条件

    覆盖范围：
        - `session.query(Model)` / `select(Model)`
        - JOIN 后的别名实体（include_aliases=True）
        - relationship 的 lazy load / selectinload（防止通过关系越权读取）
    """
    # 只处理 ORM 查询：
    # - is_column_load：列延迟加载，不涉及实体行
    # - not is_orm_statement：纯 SQL 文本查询，无法安全注入 ORM 条件
    if not orm_execute_state.is_select or orm_execute_state.is_column_load:
        return
    if not orm_execute_state.is_orm_statement:
        return
    if orm_execute_state.execution_options.get("skip_tenant_filter", False):
        return

    tenant_id = _current_tenant_id.get()

    if not _tenant_filter_enabled.get():
        return

    if not tenant_id:
        if _tenant_strict.get():
            raise PermissionError(
                "严格租户模式下缺少租户上下文，拒绝执行查询（请检查是否遗漏 "
                "Depends(get_current_active_user) 或 tenant_scope()）"
            )
        return

    orm_execute_state.statement = orm_execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.tenant_id == tenant_id,
            include_aliases=True,
        ),
        with_loader_criteria(
            SharedTenantMixin,
            lambda cls: or_(cls.tenant_id == tenant_id, cls.tenant_id.is_(None)),
            include_aliases=True,
        ),
    )


# --------------------------------------------------------------------------
# 全局 ORM 事件：写填充 + 越权拦截
# --------------------------------------------------------------------------
@event.listens_for(Session, "before_flush")
def _apply_tenant_write_guard(session, flush_context, instances) -> None:
    """写入侧租户守卫

    1. 新建对象：`tenant_id` 为空时自动填充当前租户
    2. 新建对象：无租户上下文且未显式指定 `tenant_id` → **直接拒绝**
       （租户级表的 tenant_id 是 NOT NULL，晚在数据库报 IntegrityError
        不如早在这里报清晰的错误；典型触发场景是平台管理员误调业务接口）
    3. 已存在对象：禁止把 `tenant_id` 改成别的租户（越权搬家）
    4. 平台共享数据（tenant_id 为空）：租户上下文下一律只读
    """
    tenant_id = _current_tenant_id.get()
    strict = _tenant_strict.get()

    for obj in session.new:
        if isinstance(obj, TenantMixin):
            if getattr(obj, "tenant_id", None) is None:
                if tenant_id is None:
                    # 不受 TENANT_STRICT_MODE 控制：这类写入必然失败，
                    # 早失败 + 明确信息，好过数据库抛 NOT NULL。
                    raise PermissionError(
                        f"缺少租户上下文，无法创建 {type(obj).__name__}："
                        "平台账号请先切换到某个租户，或在创建对象时显式赋值 tenant_id"
                    )
                obj.tenant_id = tenant_id
        elif isinstance(obj, SharedTenantMixin):
            # 共享表**故意不自动填充**：tenant_id 为 NULL 是"平台内置数据"的
            # 合法取值。若当前处在某个租户上下文中却留空，多半是业务代码漏传，
            # 记录 warning 便于排查（不阻断，平台规则本来就该留空）。
            if getattr(obj, "tenant_id", None) is None and tenant_id:
                logger.warning(
                    f"[tenant] {type(obj).__name__} 在租户 {tenant_id} 上下文中创建但 "
                    "tenant_id 为空，将作为平台共享数据对所有租户可见；"
                    "如非预期请显式赋值 tenant_id"
                )

    if not _tenant_filter_enabled.get():
        return

    for obj in session.dirty:
        if not isinstance(obj, (TenantMixin, SharedTenantMixin)):
            continue

        # (a) 平台共享数据（tenant_id 为空）：租户上下文下一律只读，
        #     否则租户 A 就能改掉所有人都在用的平台风控规则。
        if isinstance(obj, SharedTenantMixin) and getattr(obj, "tenant_id", None) is None:
            if tenant_id is not None:
                raise PermissionError(
                    f"平台共享数据只读，禁止修改：{type(obj).__name__}(id={obj.id})"
                )
            if strict:
                raise PermissionError(
                    f"缺少租户上下文，拒绝修改平台共享数据 {type(obj).__name__}"
                )
            continue

        history = get_history(obj, "tenant_id")
        if not history.has_changes():
            continue
        added = [v for v in history.added if v is not None]
        if not added:
            continue
        # (b) 越权搬家：把对象从当前租户改挂到别的租户
        #     无上下文的系统任务 / 显式 bypass 的迁移脚本不受此限制
        if tenant_id is not None and any(v != tenant_id for v in added):
            raise PermissionError(
                f"禁止跨租户修改：{type(obj).__name__}(id={obj.id}) "
                f"试图从 {history.deleted} 迁移到 {added}"
            )
        if tenant_id is None and strict:
            raise PermissionError(
                f"缺少租户上下文，拒绝修改 {type(obj).__name__} 的 tenant_id"
            )


# --------------------------------------------------------------------------
# 业务辅助
# --------------------------------------------------------------------------
def assert_same_tenant(obj, tenant_id: Optional[str] = None) -> None:
    """显式断言对象属于当前租户（API 层用于返回 404 而不是 403）

    用法：
        obj = db.query(AdAccount).filter(...).first()
        if not obj:
            raise HTTPException(404)   # 自动过滤已保证拿不到别的租户数据
    """
    if obj is None:
        return
    expected = tenant_id if tenant_id is not None else get_current_tenant_id()
    actual = getattr(obj, "tenant_id", None)
    if expected is not None and actual != expected:
        logger.warning(
            f"[tenant] 越权访问被拦截: {type(obj).__name__} id={getattr(obj, 'id', None)} "
            f"tenant={actual} expected={expected}"
        )
        raise PermissionError("资源不属于当前租户")

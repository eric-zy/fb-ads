"""多租户隔离回归测试

隔离是安全底线，一旦被绕过就是跨租户数据泄漏，因此单独立一个测试文件：
自建内存 SQLite，不依赖 conftest 的共享 engine（避免数据互相污染）。

覆盖：
    1. 读取隔离（含 relationship lazy load）
    2. 平台共享数据（tenant_id 为空）的可见性
    3. bypass_tenant 跨租户访问
    4. 新建对象自动填充 tenant_id
    5. 禁止跨租户"数据搬家"
    6. 平台共享数据对租户只读
    7. 无租户上下文时拒绝创建租户级数据（平台管理员误调业务接口）
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base
from core.tenant import bypass_tenant, tenant_scope
from models import AdAccount, CampaignTemplate, MetaAccount, RiskRule, Tenant
from models.tenant import TenantStatus


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def two_tenants(db):
    """两个租户 + 各一条广告账户 + 各一个模板 + 一条平台风控规则"""
    db.add_all(
        [
            Tenant(id="t1", name="租户A", slug="tenant-a", status=TenantStatus.ACTIVE.value),
            Tenant(id="t2", name="租户B", slug="tenant-b", status=TenantStatus.ACTIVE.value),
            RiskRule(id="r0", name="平台规则", rule_type="spend_anomaly"),  # 平台共享
        ]
    )
    db.commit()

    with tenant_scope("t1"):
        db.add(MetaAccount(id="bm1", name="BM-A", business_id="111"))
        db.add(AdAccount(id="acc1", business_id="bm1", account_id="act_1"))
        db.add(CampaignTemplate(id="tp1", name="模板A"))
        db.commit()

    with tenant_scope("t2"):
        db.add(MetaAccount(id="bm2", name="BM-B", business_id="222"))
        db.add(AdAccount(id="acc2", business_id="bm2", account_id="act_2"))
        db.add(CampaignTemplate(id="tp2", name="模板B"))
        db.commit()
    return db


def test_read_isolation(two_tenants):
    db = two_tenants
    with tenant_scope("t1"):
        assert [a.id for a in db.query(AdAccount).all()] == ["acc1"]
        assert [t.name for t in db.query(CampaignTemplate).all()] == ["模板A"]

    with tenant_scope("t2"):
        assert [a.id for a in db.query(AdAccount).all()] == ["acc2"]
        assert [t.name for t in db.query(CampaignTemplate).all()] == ["模板B"]


def test_lazy_load_is_isolated(two_tenants):
    """通过关系访问同样要被隔离，否则就是侧信道泄漏"""
    db = two_tenants
    with tenant_scope("t2"):
        bm = db.query(MetaAccount).first()
        assert [a.id for a in bm.ad_accounts] == ["acc2"]


def test_id_probe_returns_nothing(two_tenants):
    """租户 B 拿租户 A 的主键查询 → 查不到（应表现为 404 而不是 403）"""
    db = two_tenants
    with tenant_scope("t2"):
        assert db.query(AdAccount).filter(AdAccount.id == "acc1").first() is None


def test_shared_data_visibility(two_tenants):
    """平台规则（tenant_id 为空）所有租户可见；租户自定义规则仅自己可见"""
    db = two_tenants
    with tenant_scope("t1"):
        db.add(RiskRule(id="r1", name="租户A规则", rule_type="fraud", tenant_id="t1"))
        db.commit()
        assert sorted(r.name for r in db.query(RiskRule).all()) == ["平台规则", "租户A规则"]

    with tenant_scope("t2"):
        assert [r.name for r in db.query(RiskRule).all()] == ["平台规则"]


def test_bypass_tenant_sees_all(two_tenants):
    db = two_tenants
    with bypass_tenant():
        assert sorted(a.id for a in db.query(AdAccount).all()) == ["acc1", "acc2"]


def test_auto_fill_tenant_id(two_tenants):
    db = two_tenants
    with tenant_scope("t1"):
        tpl = CampaignTemplate(id="tp3", name="模板C")
        db.add(tpl)
        db.commit()
        assert tpl.tenant_id == "t1"


def test_create_without_tenant_context_rejected(db):
    """无租户上下文时创建租户级数据 → 明确拒绝，而不是数据库抛 NOT NULL

    典型场景：平台管理员（tenant_id 为空）误调业务创建接口。
    """
    with tenant_scope(None):
        db.add(CampaignTemplate(id="tpx", name="无主模板"))
        with pytest.raises(PermissionError):
            db.commit()
    db.rollback()


def test_bypass_allows_read_but_not_orphan_create(db):
    """bypass 只放开读过滤，不允许创建无主数据（否则会留下脏数据）"""
    with bypass_tenant(), tenant_scope(None):
        db.add(CampaignTemplate(id="tpy", name="bypass 创建"))
        with pytest.raises(PermissionError):
            db.commit()
    db.rollback()


def test_cross_tenant_move_blocked(two_tenants):
    db = two_tenants
    with tenant_scope("t1"):
        acc = db.query(AdAccount).first()
        acc.tenant_id = "t2"
        with pytest.raises(PermissionError):
            db.commit()
    db.rollback()


def test_platform_shared_data_readonly_for_tenant(two_tenants):
    db = two_tenants
    with tenant_scope("t2"):
        rule = db.query(RiskRule).filter(RiskRule.id == "r0").first()
        rule.threshold = 999
        with pytest.raises(PermissionError):
            db.commit()
    db.rollback()

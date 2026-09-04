"""Pytest配置和Fixture"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from core.database import Base, get_db
from core.tenant import reset_current_tenant_id, set_current_tenant_id
from config.settings import settings
from models import Tenant

# 多租户：所有测试共享的虚拟租户。
# 业务表的 tenant_id 为 NOT NULL，缺少租户上下文时写入会直接失败，
# 因此用 autouse fixture 统一建立上下文（与生产 get_db 的行为一致）。
DEFAULT_TEST_TENANT_ID = "test_tenant"
DEFAULT_TEST_TENANT_SLUG = "test-tenant"

# 测试数据库：**内存 SQLite**。
# 早期用文件库 ./test.db，一旦模型变更（如 Meta 账号管理 V1 重构），
# 残留的旧文件不会随 create_all 更新结构，导致用例报"no such column"。
# 内存库每次运行都是全新结构，彻底避免这类陈旧 schema 问题。
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def _ensure_default_tenant():
    """建表后立刻播种默认租户（内存库每次运行都是全新的）"""
    session = TestingSessionLocal()
    try:
        if not session.query(Tenant).filter(Tenant.id == DEFAULT_TEST_TENANT_ID).first():
            session.add(
                Tenant(id=DEFAULT_TEST_TENANT_ID, name="测试租户", slug=DEFAULT_TEST_TENANT_SLUG)
            )
            session.commit()
    finally:
        session.close()


_ensure_default_tenant()


@pytest.fixture(autouse=True)
def tenant_context():
    """为每个用例建立默认租户上下文

    隔离框架要求：业务表写入必须有 tenant_id。
    这里在主上下文设置，sync 路由（运行于线程池，继承上下文副本）同样生效。
    """
    token = set_current_tenant_id(DEFAULT_TEST_TENANT_ID)
    yield
    reset_current_tenant_id(token)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture
def client():
    """提供测试客户端"""
    return TestClient(app)

@pytest.fixture
def db():
    """提供测试数据库session"""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

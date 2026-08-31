"""Pytest配置和Fixture"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from core.database import Base, get_db
from config.settings import settings

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

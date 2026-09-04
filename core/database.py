from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from typing import AsyncIterator

from fastapi import Request

from config.settings import settings
from core.logger import logger
from core.tenant import resolve_tenant_from_request, reset_current_tenant_id, set_current_tenant_id

# SQLAlchemy 基类
Base = declarative_base()

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    echo=settings.DEBUG,
    pool_pre_ping=True,  # 检查连接是否有效
)

# 创建session工厂
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_sync_db():
    """同步数据库 session 生成器（供 Celery 任务、脚本等非 HTTP 场景使用）

    注意：它不会建立租户上下文，调用方需自行 `with tenant_scope(tid):`。
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


async def get_db(request: Request = None) -> AsyncIterator[Session]:
    """数据库 session 依赖注入（**同时建立租户上下文**）

    这里是多租户隔离的主入口：
    从请求头的 JWT 中解析 `tid` claim 并写入 ContextVar，
    `core.tenant` 注册的 ORM 事件随后会自动给所有查询加上 `tenant_id` 过滤。

    用 async generator 而不是同步 generator，是因为 FastAPI 会把同步依赖
    放到线程池执行，线程池内对 ContextVar 的修改**不会**传播到主上下文；
    async 依赖在主上下文执行，设置的值能被后续（含线程池中的同步路由）继承。

    所有 `Depends(get_db)` 的路由因此自动获得隔离能力，
    即使该路由没有显式依赖 `get_current_active_user`。
    """
    db = SessionLocal()
    token = None
    try:
        if request is not None:
            tenant_id = resolve_tenant_from_request(request)
            if tenant_id:
                token = set_current_tenant_id(tenant_id)
        yield db
    except Exception as e:
        logger.error(f"Database error: {str(e)}")
        db.rollback()
        raise
    finally:
        reset_current_tenant_id(token)
        db.close()


def init_db():
    """初始化数据库

    开发环境自动建表；生产环境请使用 alembic upgrade head 管理表结构。
    """
    logger.info("Initializing database...")
    # core.tenant 在 models 导入时即注册全局 ORM 过滤钩子，此处确保已加载
    import core.tenant as tenant_mod  # noqa: F401

    tenant_mod.set_strict_mode(settings.TENANT_STRICT_MODE)
    Base.metadata.create_all(bind=engine)
    logger.info(
        f"Database initialized successfully "
        f"(tenant_isolation=on, strict_mode={settings.TENANT_STRICT_MODE})"
    )


def close_db():
    """关闭数据库连接"""
    engine.dispose()
    logger.info("Database connections closed")

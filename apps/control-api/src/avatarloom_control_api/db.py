"""数据库连接管理。"""

from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from avatarloom_control_api.config import Settings
from avatarloom_control_api.models import Base

logger = logging.getLogger(__name__)


def create_engine(settings: Settings) -> AsyncEngine:
    """创建 async engine。

    SQLite 默认不开 PRAGMA foreign_keys——所有 ondelete 声明静默失效。
    这里在每次连接建立时强制开启。
    """
    engine = create_async_engine(
        settings.db_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False} if "sqlite" in settings.db_url else {},
    )
    # SQLite 外键开关——ondelete="SET NULL"/"CASCADE" 等 FK 约束依赖此 PRAGMA
    if "sqlite" in settings.db_url:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_fk(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """创建所有表（开发用）。生产用 Alembic 迁移。

    注意：create_all 不写 alembic_version 表——后续跑 `alembic upgrade head`
    会因表已存在而失败。生产部署应先 `alembic upgrade head` 再启动服务，
    而非依赖此方法。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db(engine: AsyncEngine) -> None:
    """删除所有表（测试用）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

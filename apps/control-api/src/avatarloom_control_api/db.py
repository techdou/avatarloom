"""数据库连接管理。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from avatarloom_control_api.config import Settings
from avatarloom_control_api.models import Base


def create_engine(settings: Settings) -> AsyncEngine:
    """创建 async engine。"""
    return create_async_engine(
        settings.db_url,
        echo=False,
        future=True,
        # SQLite 需要这个
        connect_args={"check_same_thread": False} if "sqlite" in settings.db_url else {},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """创建所有表（开发用）。生产用 Alembic 迁移。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db(engine: AsyncEngine) -> None:
    """删除所有表（测试用）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供 db session。"""
    async with session_factory() as session:
        yield session

"""FastAPI 依赖注入。

get_db 提供数据库 session。session_factory 由 create_app 注入到 app.state。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """从 app.state 取 session_factory 创建 session。

    create_app 把 session_factory 存到 app.state.session_factory。
    """
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session

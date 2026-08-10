"""FastAPI app 工厂。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from avatarloom_control_api.auth import verify_token
from avatarloom_control_api.config import Settings, ensure_dirs, load_settings
from avatarloom_control_api.db import create_engine, create_session_factory, init_db
from avatarloom_control_api.routers import (
    artifacts,
    assets,
    avatars,
    blocks,
    health,
    personas,
    profiles,
    projects,
    runs,
    secrets,
    sessions,
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI app。"""
    if settings is None:
        settings = load_settings()

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))

    ensure_dirs(settings)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 启动：建表（开发用；生产用 alembic upgrade head）
        await init_db(engine)
        if not settings.api_token and not settings.auth_disabled:
            logger.warning(
                "AVATARLOOM_API_TOKEN 未设置且未显式 AVATARLOOM_AUTH_DISABLED=1——"
                "所有端点返回 401（fail-closed）。生产环境必须设置 token。"
            )
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.settings = settings
        logger.info("Control API started on %s:%d", settings.host, settings.port)
        yield
        # 关闭
        await engine.dispose()
        logger.info("Control API stopped")

    app = FastAPI(
        title="AvatarLoom Control API",
        description="Composable Digital Human Runtime — Control Plane",
        version="0.1.0",
        lifespan=lifespan,
        # 全局鉴权：token 未配置且未显式关闭鉴权时 fail-closed（401）；
        # 显式开发模式或配置 token 后，所有 router 自动受保护。
        dependencies=[Depends(verify_token)],
    )

    # 提前挂上 settings——verify_token 从 app.state 读 api_token，
    # 不依赖 lifespan 是否已执行（lifespan 里的赋值保留，二者一致）。
    app.state.settings = settings

    # CORS——白名单（allow_credentials=True 时不能用通配符）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # 注册路由
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(avatars.router, prefix="/api/avatars", tags=["avatars"])
    app.include_router(personas.router, prefix="/api/personas", tags=["personas"])
    app.include_router(blocks.router, prefix="/api/blocks", tags=["blocks"])
    app.include_router(profiles.router, prefix="/api/profiles", tags=["profiles"])
    app.include_router(secrets.router, prefix="/api/secrets", tags=["secrets"])
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
    app.include_router(assets.router, prefix="/api/assets", tags=["assets"])

    return app

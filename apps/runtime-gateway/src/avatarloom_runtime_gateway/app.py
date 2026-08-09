"""Runtime Gateway FastAPI app。

浏览器唯一入口：
- GET /api/health：健康检查
- GET /api/profiles：列出可用 Profile
- GET /ws/realtime：WebSocket 主通道
- GET /：基本信息

WS 生命周期：
  1. 浏览器 connect /ws/realtime
  2. 发 session.start（带 profile_id/persona_id）
  3. Gateway 装配 Orchestrator，start_session
  4. 浏览器持续发二进制 PCM 上行 / JSON 控制
  5. Gateway 持续发 JSON 事件 + 二进制 PCM/JPEG 下行
  6. 浏览器发 session.stop 或断开 → Gateway shutdown session
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# 注入项目根到 sys.path，让 runtime/ 和 blocks/ 可 import
# （runtime/blocks 是扁平 namespace 包，不是 workspace 成员）
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 加载项目根 .env 到 os.environ（不覆盖已有环境变量）。
# Block 的 apiKeyEnv（如 VISION_API_KEY）按文档优先级 ".env < 环境变量" 从
# os.environ 读取；pydantic-settings 的 env_file 只填 Settings 字段、不进
# os.environ，这里补齐。
from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env", override=False)

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from avatarloom_runtime_gateway.auth import verify_http_token, verify_ws_access  # noqa: E402
from avatarloom_runtime_gateway.config import Settings, load_settings  # noqa: E402
from avatarloom_runtime_gateway.control_client import (  # noqa: E402
    CatalogUnavailable,
    list_runtime_profile_ids,
)
from avatarloom_runtime_gateway.management import router as management_router  # noqa: E402
from avatarloom_runtime_gateway.ws_handler import WebSocketSession  # noqa: E402

logger = logging.getLogger(__name__)


def _prepare_runtime_dirs(settings: Settings) -> None:
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    Path(settings.artifacts_root).mkdir(parents=True, exist_ok=True)
    Path(settings.runs_root).mkdir(parents=True, exist_ok=True)


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


def _build_lifespan(settings: Settings) -> Any:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        if not settings.api_token and not settings.auth_disabled:
            logger.warning(
                "AVATARLOOM_API_TOKEN 未设置且未显式 AVATARLOOM_AUTH_DISABLED=1——"
                "WS 握手 fail-closed（拒绝连接）。生产环境必须设置 token。"
            )
        logger.info("Runtime Gateway started on %s:%d", settings.host, settings.port)
        yield
        logger.info("Runtime Gateway stopped")

    return lifespan


def _add_cors(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_basic_routes(app: FastAPI, settings: Settings) -> None:
    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "name": "AvatarLoom Runtime Gateway",
            "version": "0.1.0",
            "ws_endpoint": "/ws/realtime",
            "default_profile": settings.default_profile,
        }

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/profiles", dependencies=[Depends(verify_http_token)])
    async def list_profiles() -> dict[str, Any]:
        """Control API 为事实源；仅控制面离线时使用本地只读镜像。"""
        try:
            profiles = await list_runtime_profile_ids(settings)
        except CatalogUnavailable:
            logger.warning("control API unavailable; listing local profile mirrors")
            profiles_dir = Path(settings.workspace_root) / "profiles"
            profiles = [f.stem for f in sorted(profiles_dir.glob("*.yaml"))]
        # mock 始终有内置 fallback，不依赖数据库或镜像存在。
        return {
            "profiles": sorted(set(profiles) | {"mock"}),
            "default": settings.default_profile,
        }


def _register_websocket_routes(app: FastAPI, settings: Settings) -> None:
    @app.websocket("/ws/realtime")
    async def ws_realtime(ws: WebSocket) -> None:
        """主 WS 通道。先过 Origin + token 校验（仅显式开发模式放行空 token）。"""
        if not await verify_ws_access(ws, settings):
            return  # 已拒绝：accept 前 close，握手失败（HTTP 403），零资源分配
        await ws.accept()
        session = WebSocketSession(ws, settings)
        try:
            await session.run()
        except WebSocketDisconnect:
            logger.info("client disconnected")
        except Exception:
            logger.exception("ws session error")
        finally:
            await session.cleanup()


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 Runtime Gateway app。"""
    if settings is None:
        settings = load_settings()

    _configure_logging(settings)
    _prepare_runtime_dirs(settings)

    app = FastAPI(
        title="AvatarLoom Runtime Gateway",
        description="Composable Digital Human Runtime — Browser WebSocket Entry",
        version="0.1.0",
        lifespan=_build_lifespan(settings),
    )

    _add_cors(app, settings)
    _register_basic_routes(app, settings)
    app.include_router(management_router)
    _register_websocket_routes(app, settings)

    return app

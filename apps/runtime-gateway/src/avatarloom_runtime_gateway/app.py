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

import asyncio
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
from avatarloom_runtime_gateway.ws_handler import (  # noqa: E402
    WebSocketSession,
    get_active_orchestrator,
)

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 Runtime Gateway app。"""
    if settings is None:
        settings = load_settings()

    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    Path(settings.artifacts_root).mkdir(parents=True, exist_ok=True)
    Path(settings.runs_root).mkdir(parents=True, exist_ok=True)

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

    app = FastAPI(
        title="AvatarLoom Runtime Gateway",
        description="Composable Digital Human Runtime — Browser WebSocket Entry",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

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

    @app.get("/api/profiles")
    async def list_profiles() -> dict[str, Any]:
        """列出 profiles/ 目录下的 yaml。"""
        profiles_dir = Path(settings.workspace_root) / "profiles"
        profiles: list[str] = []
        if profiles_dir.exists():
            for f in sorted(profiles_dir.glob("*.yaml")):
                profiles.append(f.stem)
        return {"profiles": profiles, "default": settings.default_profile}

    # ------------------------------------------------------------------
    # 管理端点：组件健康看板 + 记忆管理（均走 fail-closed HTTP 鉴权）
    # ------------------------------------------------------------------

    @app.get("/api/health/blocks", dependencies=[Depends(verify_http_token)])
    async def blocks_health() -> dict[str, Any]:
        """当前 Orchestrator 的 Block 健康明细（积木看板数据源）。"""
        orch = get_active_orchestrator()
        if orch is None:
            return {"active": False, "profile_id": None, "degraded": {}, "blocks": []}

        blocks_out: list[dict[str, Any]] = []
        for category, block_ref in orch.config.blocks.items():
            entry: dict[str, Any] = {
                "category": category,
                "block_id": None,
                "deployment": block_ref.deployment,
                "status": "absent",
                "detail": "未装配（optional 跳过或装配失败）",
                "latency_ms": None,
            }
            block = orch.blocks.get(category)
            if block is None:
                blocks_out.append(entry)
                continue
            entry["block_id"] = block.manifest().block_id
            try:
                hs = await asyncio.wait_for(block.health(), timeout=2.0)
                entry["status"] = hs.status
                entry["latency_ms"] = hs.latency_ms
                entry["detail"] = hs.message or ""
            except TimeoutError:
                entry["status"] = "unhealthy"
                entry["detail"] = "health() 超时（>2s）"
            except Exception as e:
                entry["status"] = "unhealthy"
                entry["detail"] = str(e)[:200]
            blocks_out.append(entry)

        return {
            "active": True,
            "profile_id": orch.config.profile_id,
            "degraded": orch.degraded_blocks,
            "blocks": blocks_out,
        }

    @app.get("/api/memory", dependencies=[Depends(verify_http_token)])
    async def list_memory(persona_id: str | None = None) -> dict[str, Any]:
        """列出指定 persona（默认当前会话 persona）的记忆条目。"""
        orch = get_active_orchestrator()
        mem = orch.blocks.get("memory") if orch else None
        agent = persona_id or (orch.sessions.first_active_persona_id() if orch else None)
        if mem is None or not bool(getattr(mem, "active", False)):
            return {"active": False, "persona_id": agent, "items": []}
        list_fn = getattr(mem, "list_memories", None)
        items = await list_fn(agent) if (list_fn and agent) else []
        return {"active": True, "persona_id": agent, "items": items}

    @app.post("/api/memory", dependencies=[Depends(verify_http_token)])
    async def add_memory(payload: dict[str, Any]) -> dict[str, Any]:
        """手动写入一条记忆（记忆管理页）。body: {"text": "...", "persona_id": "..."}。"""
        orch = get_active_orchestrator()
        mem = orch.blocks.get("memory") if orch else None
        text = str(payload.get("text") or "").strip()
        agent = str(payload.get("persona_id") or "") or (
            orch.sessions.first_active_persona_id() if orch else None
        )
        if mem is None or not bool(getattr(mem, "active", False)):
            return {"ok": False, "error": "memory block 未启用"}
        if not text:
            return {"ok": False, "error": "text 不能为空"}
        if not agent:
            return {"ok": False, "error": "缺少 persona_id"}
        add_fn = getattr(mem, "add_memory", None)
        ok = await add_fn(text, agent) if add_fn else False
        return {"ok": ok, "error": None if ok else "写入失败（见 gateway 日志）"}

    @app.delete("/api/memory/{memory_id}", dependencies=[Depends(verify_http_token)])
    async def delete_memory(memory_id: str) -> dict[str, Any]:
        """删除一条记忆（按 Mem0 memory id）。"""
        orch = get_active_orchestrator()
        mem = orch.blocks.get("memory") if orch else None
        if mem is None or not bool(getattr(mem, "active", False)):
            return {"ok": False, "error": "memory block 未启用"}
        delete_fn = getattr(mem, "delete_memory", None)
        ok = await delete_fn(memory_id) if delete_fn else False
        return {"ok": ok, "error": None if ok else "删除失败（见 gateway 日志）"}

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

    return app

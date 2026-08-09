"""Gateway 管理端点集成测试：组件健康看板 + 记忆管理 + HTTP fail-closed 鉴权。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import avatarloom_runtime_gateway.ws_handler as wh
from avatarloom_runtime_gateway.app import create_app
from avatarloom_runtime_gateway.config import Settings
from httpx import ASGITransport, AsyncClient


class _FakeBlock:
    def __init__(self, block_id: str, status: str = "healthy"):
        self._block_id = block_id
        self._status = status

    def manifest(self):
        return SimpleNamespace(block_id=self._block_id)

    async def health(self):
        from avatarloom_sdk import HealthStatus

        return HealthStatus(block_id=self._block_id, status=self._status)


class _FakeSessions:
    def first_active_persona_id(self) -> str | None:
        return "demo-assistant"


class _FakeOrchestrator:
    """注入 gateway 的假 orchestrator——验证端点映射与结构，不装配真实 Block。"""

    def __init__(self):
        self.config = SimpleNamespace(
            profile_id="mock",
            blocks={
                "vad": SimpleNamespace(deployment="mock"),
                "tts": SimpleNamespace(deployment="mock"),
                "vision": SimpleNamespace(deployment="mock"),
            },
        )
        self.blocks = {
            "vad": _FakeBlock("vad.mock", status="healthy"),
            "tts": _FakeBlock("tts.mock", status="degraded"),
            # vision 故意不装配 → absent
        }
        self.degraded_blocks = {"tts": "tts.mock"}
        self.sessions = _FakeSessions()


@asynccontextmanager
async def _gateway_client(
    tmp_path: Path, **overrides
) -> AsyncIterator[tuple[AsyncClient, object]]:
    base = {
        "workspace_root": str(tmp_path),
        "artifacts_root": str(tmp_path / "artifacts"),
        "runs_root": str(tmp_path / "runs"),
        "default_profile": "mock",
        "auth_disabled": True,
    }
    base.update(overrides)
    app = create_app(Settings(**base))
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as ac,
        app.router.lifespan_context(app),
    ):
        yield ac, app


class TestBlocksHealth:
    async def test_inactive_without_orchestrator(self, tmp_path: Path) -> None:
        async with _gateway_client(tmp_path) as (c, _):
            r = await c.get("/api/health/blocks")
            assert r.status_code == 200
            data = r.json()
            assert data["active"] is False
            assert data["blocks"] == []

    async def test_reports_block_states(self, tmp_path: Path, monkeypatch) -> None:
        fake = _FakeOrchestrator()
        monkeypatch.setattr(wh, "_active_orchestrator", fake)
        try:
            async with _gateway_client(tmp_path) as (c, _):
                r = await c.get("/api/health/blocks")
                assert r.status_code == 200
                data = r.json()
                assert data["active"] is True
                assert data["profile_id"] == "mock"
                assert data["degraded"] == {"tts": "tts.mock"}
                by_cat = {b["category"]: b for b in data["blocks"]}
                assert by_cat["vad"]["status"] == "healthy"
                assert by_cat["vad"]["block_id"] == "vad.mock"
                assert by_cat["tts"]["status"] == "degraded"
                assert by_cat["vision"]["status"] == "absent"
                assert by_cat["vision"]["block_id"] is None
        finally:
            monkeypatch.setattr(wh, "_active_orchestrator", None)


class TestMemoryEndpoints:
    async def test_inactive_memory_returns_safe(self, tmp_path: Path) -> None:
        async with _gateway_client(tmp_path) as (c, _):
            r = await c.get("/api/memory")
            assert r.status_code == 200
            assert r.json() == {"active": False, "persona_id": None, "items": []}

            r2 = await c.post("/api/memory", json={"text": "x", "persona_id": "p"})
            assert r2.json()["ok"] is False

            r3 = await c.delete("/api/memory/mem_xxx")
            assert r3.json()["ok"] is False

    async def test_memory_routes_fail_closed(self, tmp_path: Path) -> None:
        """auth_disabled=False 且无 token → 管理端点 401。"""
        async with _gateway_client(tmp_path, auth_disabled=False) as (c, _):
            assert (await c.get("/api/health/blocks")).status_code == 401
            assert (await c.get("/api/memory")).status_code == 401
            assert (await c.post("/api/memory", json={"text": "x"})).status_code == 401
            assert (await c.delete("/api/memory/m1")).status_code == 401

    async def test_memory_with_token_works(self, tmp_path: Path) -> None:
        async with _gateway_client(tmp_path, api_token="s3cret") as (c, _):
            assert (await c.get("/api/memory")).status_code == 401
            r = await c.get(
                "/api/memory", headers={"Authorization": "Bearer s3cret"}
            )
            assert r.status_code == 200
            assert r.json()["active"] is False

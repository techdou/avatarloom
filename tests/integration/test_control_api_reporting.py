"""Session/Run 生命周期上报端点测试（gateway → control-api 数据链）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from avatarloom_control_api.app import create_app
from avatarloom_control_api.config import Settings
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    db_path = tmp_path / "test.db"
    settings = Settings(
        db_url=f"sqlite+aiosqlite:///{db_path}",
        workspace_root=str(tmp_path),
        artifacts_root=str(tmp_path / "artifacts"),
        runs_root=str(tmp_path / "runs"),
        auth_disabled=True,
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as ac,
        app.router.lifespan_context(app),
    ):
        yield ac


class TestSessionReporting:
    async def test_report_start_then_end(self, client: AsyncClient) -> None:
        # 上报开始
        r = await client.post(
            "/api/sessions",
            json={
                "id": "sess_001",
                "profile_id": "mock",
                "persona_id": "demo",
                "status": "active",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "sess_001"
        assert body["status"] == "active"
        assert body["ended_at"] is None

        # 上报收尾
        r = await client.patch(
            "/api/sessions/sess_001",
            json={"status": "closed"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "closed"
        assert body["ended_at"] is not None

        # 列表可查
        r = await client.get("/api/sessions")
        assert r.status_code == 200
        assert any(s["id"] == "sess_001" for s in r.json())

    async def test_report_start_is_idempotent_upsert(self, client: AsyncClient) -> None:
        """gateway 重试时重复 POST 不 409——upsert 更新。"""
        for _ in range(2):
            r = await client.post(
                "/api/sessions",
                json={"id": "sess_dup", "profile_id": "mock"},
            )
            assert r.status_code == 200
        r = await client.get("/api/sessions/sess_dup")
        assert r.status_code == 200

    async def test_patch_unknown_session_404(self, client: AsyncClient) -> None:
        r = await client.patch("/api/sessions/nope", json={"status": "closed"})
        assert r.status_code == 404


class TestRunReporting:
    async def test_report_lifecycle(self, client: AsyncClient) -> None:
        # session 先建（run.session_id 外键引用）
        await client.post("/api/sessions", json={"id": "sess_r1", "profile_id": "mock"})

        # run 开始
        r = await client.post(
            "/api/runs",
            json={
                "id": "run_20260817_001",
                "session_id": "sess_r1",
                "profile_id": "mock",
                "persona_id": "demo",
                "status": "running",
                "run_dir": "run_20260817_001",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "running"

        # run 收尾（带 metrics + 文本）
        r = await client.patch(
            "/api/runs/run_20260817_001",
            json={
                "status": "completed",
                "metrics": {"first_text_ms": 120, "first_audio_ms": 480},
                "user_text": "你好",
                "assistant_text": "你好呀",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"
        assert body["ended_at"] is not None
        assert body["metrics"]["first_text_ms"] == 120
        assert body["user_text"] == "你好"
        assert body["assistant_text"] == "你好呀"

        # 按 session 过滤可查
        r = await client.get("/api/runs", params={"session_id": "sess_r1"})
        assert r.status_code == 200
        assert len(r.json()) == 1

    async def test_report_run_idempotent_upsert(self, client: AsyncClient) -> None:
        await client.post("/api/sessions", json={"id": "sess_r2", "profile_id": "mock"})
        for _ in range(2):
            r = await client.post(
                "/api/runs",
                json={"id": "run_dup", "session_id": "sess_r2"},
            )
            assert r.status_code == 200

    async def test_patch_unknown_run_404(self, client: AsyncClient) -> None:
        r = await client.patch("/api/runs/nope", json={"status": "completed"})
        assert r.status_code == 404

    async def test_run_id_pattern_rejected(self, client: AsyncClient) -> None:
        """非法 run id（路径穿越字符）被 RESOURCE_ID_PATTERN 拒绝。"""
        await client.post("/api/sessions", json={"id": "sess_r3", "profile_id": "mock"})
        r = await client.post(
            "/api/runs",
            json={"id": "../evil", "session_id": "sess_r3"},
        )
        assert r.status_code == 422

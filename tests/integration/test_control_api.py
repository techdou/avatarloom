"""Control API 集成测试。

用 httpx.AsyncClient(ASGITransport) 直接打 app，无需起真实服务。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from avatarloom_control_api.app import create_app
from avatarloom_control_api.config import Settings
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[AsyncClient]:
    """起 app + 测试 db，yield httpx client。"""
    db_path = tmp_path / "test.db"
    settings = Settings(
        db_url=f"sqlite+aiosqlite:///{db_path}",
        workspace_root=str(tmp_path),
        artifacts_root=str(tmp_path / "artifacts"),
        runs_root=str(tmp_path / "runs"),
    )
    app = create_app(settings)
    # lifespan 会建表
    transport = ASGITransport(app=app)
    # 两个 with 不能合并：lifespan 管 app 生命周期，AsyncClient 管 HTTP
    async with (
        AsyncClient(transport=transport, base_url="http://test") as ac,
        app.router.lifespan_context(app),
    ):
        yield ac


class TestHealth:
    async def test_health_ok(self, client: AsyncClient) -> None:
        r = await client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["db_ok"] is True


class TestProjectsCRUD:
    async def test_create_and_get(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/projects",
            json={
                "id": "proj_1",
                "name": "Test Project",
            },
        )
        assert r.status_code == 201
        created = r.json()
        assert created["id"] == "proj_1"
        assert created["name"] == "Test Project"

        r = await client.get("/api/projects/proj_1")
        assert r.status_code == 200
        assert r.json()["name"] == "Test Project"

    async def test_list(self, client: AsyncClient) -> None:
        await client.post("/api/projects", json={"id": "p1", "name": "One"})
        await client.post("/api/projects", json={"id": "p2", "name": "Two"})
        r = await client.get("/api/projects")
        assert r.status_code == 200
        assert len(r.json()) == 2

    async def test_404_on_missing(self, client: AsyncClient) -> None:
        r = await client.get("/api/projects/nonexistent")
        assert r.status_code == 404

    async def test_duplicate_create_conflict(self, client: AsyncClient) -> None:
        await client.post("/api/projects", json={"id": "dup", "name": "A"})
        r = await client.post("/api/projects", json={"id": "dup", "name": "B"})
        assert r.status_code == 409

    async def test_update(self, client: AsyncClient) -> None:
        await client.post("/api/projects", json={"id": "u", "name": "Old"})
        r = await client.patch("/api/projects/u", json={"name": "New"})
        assert r.status_code == 200
        assert r.json()["name"] == "New"

    async def test_delete(self, client: AsyncClient) -> None:
        await client.post("/api/projects", json={"id": "del", "name": "X"})
        r = await client.delete("/api/projects/del")
        assert r.status_code == 200
        r = await client.get("/api/projects/del")
        assert r.status_code == 404


class TestPersonasCRUD:
    async def test_full_crud(self, client: AsyncClient) -> None:
        # create
        r = await client.post(
            "/api/personas",
            json={
                "id": "demo",
                "name": "Demo Assistant",
                "label": "Assistant",
                "prompt": "你是 AvatarLoom 演示助手",
            },
        )
        assert r.status_code == 201
        # get
        r = await client.get("/api/personas/demo")
        assert r.json()["prompt"] == "你是 AvatarLoom 演示助手"
        # list
        r = await client.get("/api/personas")
        assert len(r.json()) == 1
        # update
        r = await client.patch("/api/personas/demo", json={"name": "Updated"})
        assert r.json()["name"] == "Updated"
        # delete
        r = await client.delete("/api/personas/demo")
        assert r.status_code == 200


class TestBlocksCRUD:
    async def test_create_and_filter_by_category(self, client: AsyncClient) -> None:
        await client.post(
            "/api/blocks",
            json={
                "id": "vad.mock",
                "name": "Mock VAD",
                "category": "vad",
            },
        )
        await client.post(
            "/api/blocks",
            json={
                "id": "tts.mock",
                "name": "Mock TTS",
                "category": "tts",
            },
        )
        # 全部
        r = await client.get("/api/blocks")
        assert len(r.json()) == 2
        # 按 category 过滤
        r = await client.get("/api/blocks", params={"category": "vad"})
        assert len(r.json()) == 1
        assert r.json()[0]["id"] == "vad.mock"


class TestProfilesCRUD:
    async def test_full_crud(self, client: AsyncClient) -> None:
        blocks = {
            "vad": {"id": "vad.mock", "deployment": "mock"},
            "llm": {"id": "llm.mock", "deployment": "mock"},
        }
        r = await client.post(
            "/api/profiles",
            json={
                "id": "mock",
                "name": "Mock Profile",
                "blocks": blocks,
            },
        )
        assert r.status_code == 201
        r = await client.get("/api/profiles/mock")
        assert r.json()["blocks"]["vad"]["id"] == "vad.mock"


class TestSecretsCRUD:
    async def test_create_does_not_store_value(self, client: AsyncClient, monkeypatch) -> None:
        monkeypatch.setenv("TEST_SECRET_KEY", "super-secret-value")
        r = await client.post(
            "/api/secrets",
            json={
                "id": "sec_1",
                "name": "LLM Key",
                "env_var": "TEST_SECRET_KEY",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["is_set"] is True
        assert "value" not in data  # 不存 value
        assert data["env_var"] == "TEST_SECRET_KEY"

    async def test_unset_env_shows_false(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/secrets",
            json={
                "id": "sec_2",
                "name": "Missing",
                "env_var": "DEFINITELY_NOT_SET_XYZ",
            },
        )
        assert r.json()["is_set"] is False

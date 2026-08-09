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
        auth_disabled=True,
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


# ---------------------------------------------------------------------------
# Avatar + Asset（核心：数字人形象资产管理）
# ---------------------------------------------------------------------------


class TestAvatarsCRUD:
    """Avatar CRUD——独立于 Persona 的形象资产实体。"""

    async def test_create_avatar_without_persona(self, client: AsyncClient) -> None:
        """能独立创建 Avatar，不依赖 Persona（验收标准 1）。"""
        # 先建 project
        await client.post("/api/projects", json={"id": "p1", "name": "P"})
        r = await client.post(
            "/api/avatars",
            json={
                "id": "av1",
                "project_id": "p1",
                "name": "客服小妹",
                "avatar_block": "avatar.static",
                "description": " demo 形象",
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "客服小妹"
        assert data["avatar_block"] == "avatar.static"
        assert data["description"] == " demo 形象"
        # 资产字段初始为 null
        assert data["portrait_path"] is None
        assert data["idle_video_path"] is None

    async def test_list_with_thumbnail_field(self, client: AsyncClient) -> None:
        await client.post("/api/projects", json={"id": "p1", "name": "P"})
        await client.post("/api/avatars", json={"id": "a1", "project_id": "p1", "name": "A1"})
        await client.post("/api/avatars", json={"id": "a2", "project_id": "p1", "name": "A2"})
        r = await client.get("/api/avatars")
        assert len(r.json()) == 2
        # 列表项含 portrait_path 字段（前端用于显示缩略图）
        assert "portrait_path" in r.json()[0]


class TestAvatarAssets:
    """Avatar 资产上传/预览/删除——核心验收。"""

    async def _setup_avatar(self, client: AsyncClient) -> str:
        """创建 project + avatar，返回 avatar_id。"""
        await client.post("/api/projects", json={"id": "p1", "name": "P"})
        await client.post(
            "/api/avatars",
            json={
                "id": "av-assets",
                "project_id": "p1",
                "name": "Assets Test",
            },
        )
        return "av-assets"

    async def test_upload_portrait_updates_avatar(self, client: AsyncClient) -> None:
        """上传肖像图后 Avatar.portrait_path 自动更新（验收标准 2/7）。"""
        avatar_id = await self._setup_avatar(client)
        # 1x1 PNG
        png_bytes = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "0d0a2db4000000004945"
            "4e44ae426082"
        )
        r = await client.post(
            f"/api/avatars/{avatar_id}/assets",
            data={"kind": "portrait"},
            files={"file": ("face.png", png_bytes, "image/png")},
        )
        assert r.status_code == 201
        asset = r.json()
        assert asset["kind"] == "portrait"
        assert asset["name"] == "face.png"
        assert asset["mime_type"] == "image/png"
        assert asset["avatar_id"] == avatar_id

        # Avatar 的 portrait_path 应被更新
        r = await client.get(f"/api/avatars/{avatar_id}")
        assert r.json()["portrait_path"] is not None
        assert asset["path"] in r.json()["portrait_path"]

    async def test_list_avatar_assets(self, client: AsyncClient) -> None:
        """列出某 Avatar 的所有资产。"""
        avatar_id = await self._setup_avatar(client)
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "0d0a2db4000000004945"
            "4e44ae426082"
        )
        await client.post(
            f"/api/avatars/{avatar_id}/assets",
            data={"kind": "portrait"},
            files={"file": ("a.png", png, "image/png")},
        )
        r = await client.get(f"/api/avatars/{avatar_id}/assets")
        assert r.status_code == 200
        assets = r.json()
        assert len(assets) == 1
        assert assets[0]["kind"] == "portrait"

    async def test_download_asset_file(self, client: AsyncClient) -> None:
        """下载/预览资产文件（验收标准 2）。"""
        avatar_id = await self._setup_avatar(client)
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "0d0a2db4000000004945"
            "4e44ae426082"
        )
        upload = await client.post(
            f"/api/avatars/{avatar_id}/assets",
            data={"kind": "portrait"},
            files={"file": ("face.png", png, "image/png")},
        )
        asset_id = upload.json()["id"]
        r = await client.get(f"/api/assets/{asset_id}/file")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert len(r.content) > 0

    async def test_delete_asset_clears_avatar_ref(self, client: AsyncClient) -> None:
        """删资产后 Avatar 的 portrait_path 应被清空。"""
        avatar_id = await self._setup_avatar(client)
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c63000100000005000100"
            "0d0a2db4000000004945"
            "4e44ae426082"
        )
        upload = await client.post(
            f"/api/avatars/{avatar_id}/assets",
            data={"kind": "portrait"},
            files={"file": ("f.png", png, "image/png")},
        )
        asset_id = upload.json()["id"]
        # 确认 portrait_path 已设
        assert (await client.get(f"/api/avatars/{avatar_id}")).json()["portrait_path"] is not None
        # 删
        r = await client.delete(f"/api/assets/{asset_id}")
        assert r.status_code == 200
        # portrait_path 应清空
        assert (await client.get(f"/api/avatars/{avatar_id}")).json()["portrait_path"] is None

    async def test_wrong_mime_rejected(self, client: AsyncClient) -> None:
        """portrait kind 上传非图片应被拒。"""
        avatar_id = await self._setup_avatar(client)
        r = await client.post(
            f"/api/avatars/{avatar_id}/assets",
            data={"kind": "portrait"},
            files={"file": ("f.txt", b"not an image", "text/plain")},
        )
        assert r.status_code == 400

    async def test_voice_text_endpoint(self, client: AsyncClient) -> None:
        """设置 voice_ref_text。"""
        avatar_id = await self._setup_avatar(client)
        r = await client.post(
            f"/api/avatars/{avatar_id}/voice-text",
            json={"text": "你好，这是音色参考文本。"},
        )
        assert r.status_code == 200
        assert r.json()["voice_ref_text"] == "你好，这是音色参考文本。"


class TestPersonaAvatarDecoupling:
    """Avatar 和 Persona 解耦——Persona.avatar_id 外键引用 Avatar（验收标准 6/9）。"""

    async def test_persona_references_avatar(self, client: AsyncClient) -> None:
        """Persona 通过 avatar_id 引用 Avatar，不嵌套 avatar_ref JSON。"""
        await client.post("/api/projects", json={"id": "p1", "name": "P"})
        await client.post(
            "/api/avatars",
            json={
                "id": "av-decouple",
                "project_id": "p1",
                "name": "形象 A",
            },
        )
        r = await client.post(
            "/api/personas",
            json={
                "id": "persona-1",
                "name": "客服人设",
                "prompt": "你是客服",
                "avatar_id": "av-decouple",
            },
        )
        assert r.status_code == 201
        assert r.json()["avatar_id"] == "av-decouple"

    async def test_persona_without_avatar_ok(self, client: AsyncClient) -> None:
        """Persona 可以不绑 Avatar（纯文字人设）。"""
        r = await client.post(
            "/api/personas",
            json={
                "id": "persona-bare",
                "name": "纯文字人设",
                "prompt": "test",
            },
        )
        assert r.status_code == 201
        assert r.json()["avatar_id"] is None

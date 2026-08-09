"""Control API 安全边界集成测试。

覆盖：
- Bearer token 鉴权：Settings.api_token 生效、env 兜底、显式空 = 开发模式
- 资源 ID pattern：路径穿越/空格/斜杠 422，合法字符（含点）放行
- 资产路径防穿越：DB path 被篡改时不服务/不删除 root 外文件
- kind=other 强制二进制下载
- 上传扩展名白/黑名单
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from avatarloom_control_api.app import create_app
from avatarloom_control_api.config import Settings
from avatarloom_control_api.models import Asset
from httpx import ASGITransport, AsyncClient

_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000100"
    "0d0a2db4000000004945"
    "4e44ae426082"
)


@asynccontextmanager
async def _client(tmp_path: Path, **overrides) -> AsyncIterator[tuple[AsyncClient, object]]:
    """按 overrides 构造 Settings 起 app，yield (httpx client, app)。"""
    base = {
        "db_url": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "workspace_root": str(tmp_path),
        "artifacts_root": str(tmp_path / "artifacts"),
        "runs_root": str(tmp_path / "runs"),
        # 非鉴权测试默认走显式开发模式；鉴权契约由 TestTokenAuth 单独覆盖。
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


async def _setup_avatar(client: AsyncClient, avatar_id: str = "av-sec") -> str:
    await client.post("/api/projects", json={"id": "p1", "name": "P"})
    await client.post(
        "/api/avatars",
        json={"id": avatar_id, "project_id": "p1", "name": "Sec Test"},
    )
    return avatar_id


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------


class TestTokenAuth:
    async def test_settings_token_enforced(self, tmp_path: Path) -> None:
        """Settings(api_token=...) 直接生效——不再只看环境变量。"""
        async with _client(tmp_path, api_token="s3cret") as (c, _):
            assert (await c.get("/api/health")).status_code == 401
            assert (
                await c.get("/api/health", headers={"Authorization": "Bearer wrong"})
            ).status_code == 401
            assert (
                await c.get("/api/health", headers={"Authorization": "Bearer s3cret"})
            ).status_code == 200

    async def test_env_token_still_works(self, tmp_path: Path, monkeypatch) -> None:
        """环境变量 AVATARLOOM_API_TOKEN 仍被 Settings 吸收并生效。"""
        monkeypatch.setenv("AVATARLOOM_API_TOKEN", "env-token")
        async with _client(tmp_path) as (c, _):
            assert (await c.get("/api/health")).status_code == 401
            assert (
                await c.get("/api/health", headers={"Authorization": "Bearer env-token"})
            ).status_code == 200

    async def test_empty_token_is_dev_mode(self, tmp_path: Path) -> None:
        """空 token + 显式 auth_disabled=True → 开发模式放行。"""
        async with _client(tmp_path, auth_disabled=True) as (c, _):
            assert (await c.get("/api/health")).status_code == 200

    async def test_explicit_empty_overrides_env(self, tmp_path: Path, monkeypatch) -> None:
        """显式 Settings(api_token="", auth_disabled=True) 优先于 env——Settings 是权威来源。"""
        monkeypatch.setenv("AVATARLOOM_API_TOKEN", "env-token")
        async with _client(tmp_path, api_token="", auth_disabled=True) as (c, _):
            assert (await c.get("/api/health")).status_code == 200

    async def test_empty_token_fail_closed_by_default(self, tmp_path: Path) -> None:
        """空 token 且未显式关闭鉴权（默认）→ 401（fail-closed，生产漏配不再裸奔）。"""
        async with _client(tmp_path, auth_disabled=False) as (c, _):
            assert (await c.get("/api/health")).status_code == 401


# ---------------------------------------------------------------------------
# 资源 ID pattern
# ---------------------------------------------------------------------------


class TestResourceIdPattern:
    @pytest.mark.parametrize("bad_id", ["../evil", "a b", "/abs", "a/b", "a\\b", "..", "-x"])
    async def test_bad_project_ids_422(self, tmp_path: Path, bad_id: str) -> None:
        async with _client(tmp_path) as (c, _):
            r = await c.post("/api/projects", json={"id": bad_id, "name": "x"})
            assert r.status_code == 422, f"id={bad_id!r} 应被拒"

    @pytest.mark.parametrize("ok_id", ["p1", "proj_1", "my-proj", "a.b.c", "A9"])
    async def test_good_project_ids_201(self, tmp_path: Path, ok_id: str) -> None:
        async with _client(tmp_path) as (c, _):
            r = await c.post("/api/projects", json={"id": ok_id, "name": "x"})
            assert r.status_code == 201, f"id={ok_id!r} 应放行"

    async def test_block_id_with_dot_allowed(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            r = await c.post(
                "/api/blocks",
                json={"id": "vad.mock", "name": "Mock VAD", "category": "vad"},
            )
            assert r.status_code == 201

    async def test_persona_bad_id_422(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            r = await c.post(
                "/api/personas",
                json={"id": "../persona", "name": "x", "prompt": ""},
            )
            assert r.status_code == 422

    async def test_secret_bad_id_422(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            r = await c.post(
                "/api/secrets",
                json={"id": "../x", "name": "k", "env_var": "WHATEVER"},
            )
            assert r.status_code == 422


# ---------------------------------------------------------------------------
# 资产路径防穿越
# ---------------------------------------------------------------------------


class TestAssetPathTraversal:
    async def _insert_tampered_asset(self, app, path: str) -> None:
        """模拟 DB 被写入非法 path（正常路径由服务端生成，这里测试兜底）。"""
        async with app.state.session_factory() as s:
            s.add(
                Asset(
                    id="asset_evil",
                    kind="other",
                    name="evil.txt",
                    path=path,
                    mime_type="text/plain",
                    size_bytes=3,
                    avatar_id=None,
                    extra_metadata={},
                )
            )
            await s.commit()

    async def test_download_dotdot_blocked(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("secret-data")
        async with _client(tmp_path) as (c, app):
            await self._insert_tampered_asset(app, "../../outside.txt")
            r = await c.get("/api/assets/asset_evil/file")
            assert r.status_code == 400
            assert b"secret-data" not in r.content

    async def test_download_absolute_path_blocked(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("secret-data")
        async with _client(tmp_path) as (c, app):
            await self._insert_tampered_asset(app, str(outside.resolve()))
            r = await c.get("/api/assets/asset_evil/file")
            assert r.status_code == 400

    async def test_delete_dotdot_blocked_and_file_kept(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("keep-me")
        async with _client(tmp_path) as (c, app):
            await self._insert_tampered_asset(app, "../../outside.txt")
            r = await c.delete("/api/assets/asset_evil")
            assert r.status_code == 400
            assert outside.exists(), "root 外文件不应被删除"


# ---------------------------------------------------------------------------
# kind=other 强制二进制下载 + 上传扩展名
# ---------------------------------------------------------------------------


class TestAssetKindOther:
    async def test_other_forced_octet_stream_attachment(self, tmp_path: Path) -> None:
        """kind=other 即使声明 image/png，下载也强制 octet-stream + attachment。"""
        async with _client(tmp_path) as (c, _):
            avatar_id = await _setup_avatar(c)
            up = await c.post(
                f"/api/avatars/{avatar_id}/assets",
                data={"kind": "other"},
                files={"file": ("payload.png", _PNG_1PX, "image/png")},
            )
            assert up.status_code == 201
            asset_id = up.json()["id"]
            r = await c.get(f"/api/assets/{asset_id}/file")
            assert r.status_code == 200
            assert r.headers["content-type"] == "application/octet-stream"
            assert "attachment" in r.headers["content-disposition"]

    async def test_media_kind_keeps_mime(self, tmp_path: Path) -> None:
        """对照组：portrait 仍按真实 mime 返回（不冤杀预览）。"""
        async with _client(tmp_path) as (c, _):
            avatar_id = await _setup_avatar(c)
            up = await c.post(
                f"/api/avatars/{avatar_id}/assets",
                data={"kind": "portrait"},
                files={"file": ("face.png", _PNG_1PX, "image/png")},
            )
            asset_id = up.json()["id"]
            r = await c.get(f"/api/assets/{asset_id}/file")
            assert r.headers["content-type"].startswith("image/png")


class TestUploadExtension:
    async def test_executable_ext_rejected_for_portrait(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            avatar_id = await _setup_avatar(c)
            r = await c.post(
                f"/api/avatars/{avatar_id}/assets",
                data={"kind": "portrait"},
                files={"file": ("evil.exe", _PNG_1PX, "image/png")},
            )
            assert r.status_code == 400

    async def test_uppercase_ext_allowed(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            avatar_id = await _setup_avatar(c)
            r = await c.post(
                f"/api/avatars/{avatar_id}/assets",
                data={"kind": "portrait"},
                files={"file": ("face.PNG", _PNG_1PX, "image/png")},
            )
            assert r.status_code == 201
            assert r.json()["path"].endswith(".png")

    async def test_html_rejected_for_other(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            avatar_id = await _setup_avatar(c)
            r = await c.post(
                f"/api/avatars/{avatar_id}/assets",
                data={"kind": "other"},
                files={"file": ("page.html", b"<script>1</script>", "text/html")},
            )
            assert r.status_code == 400

    async def test_benign_ext_allowed_for_other(self, tmp_path: Path) -> None:
        async with _client(tmp_path) as (c, _):
            avatar_id = await _setup_avatar(c)
            r = await c.post(
                f"/api/avatars/{avatar_id}/assets",
                data={"kind": "other"},
                files={"file": ("archive.bin", b"\x00\x01", "application/octet-stream")},
            )
            assert r.status_code == 201

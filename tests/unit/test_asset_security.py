"""资产安全边界单测：resolve_asset_path 防穿越 + 上传扩展名白/黑名单。

纯函数级，不起 app。HTTPException 断言 status_code。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from avatarloom_control_api.routers.assets import _safe_upload_ext, resolve_asset_path
from fastapi import HTTPException


class TestResolveAssetPath:
    """DB 里的相对路径 resolve 后必须留在 assets_root 内。"""

    def test_normal_relative_path_ok(self, tmp_path: Path) -> None:
        root = tmp_path / "assets"
        p = resolve_asset_path(root, "avatars/av1/portrait/asset_x.png")
        assert p == (root / "avatars/av1/portrait/asset_x.png").resolve()

    def test_dotdot_traversal_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(HTTPException) as ei:
            resolve_asset_path(tmp_path / "assets", "../../outside.txt")
        assert ei.value.status_code == 400

    def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        with pytest.raises(HTTPException) as ei:
            resolve_asset_path(tmp_path / "assets", str(outside))
        assert ei.value.status_code == 400

    def test_nested_dotdot_that_stays_inside_ok(self, tmp_path: Path) -> None:
        """resolve 后仍在 root 内的合法路径（a/../b）不冤杀。"""
        root = tmp_path / "assets"
        p = resolve_asset_path(root, "avatars/../keep.txt")
        assert p == (root / "keep.txt").resolve()


class TestSafeUploadExt:
    """扩展名白名单（媒体 kind）+ 黑名单（kind=other）。"""

    def test_media_kind_allowed_ext(self) -> None:
        assert _safe_upload_ext("portrait", "face.png", "image/png") == ".png"

    def test_media_kind_ext_case_insensitive(self) -> None:
        assert _safe_upload_ext("portrait", "face.PNG", "image/png") == ".png"

    def test_media_kind_disallowed_ext_400(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _safe_upload_ext("portrait", "evil.exe", "image/png")
        assert ei.value.status_code == 400

    def test_media_kind_svg_rejected(self) -> None:
        """svg 是同源可渲染 Active Content，媒体白名单不含它。"""
        with pytest.raises(HTTPException) as ei:
            _safe_upload_ext("image", "x.svg", "image/svg+xml")
        assert ei.value.status_code == 400

    def test_media_kind_no_ext_falls_back_to_default(self) -> None:
        assert _safe_upload_ext("portrait", None, "image/png") == ".png"
        assert _safe_upload_ext("voice_ref", "noext", "audio/wav") == ".wav"

    def test_other_allows_benign_ext(self) -> None:
        assert _safe_upload_ext("other", "data.bin", "application/octet-stream") == ".bin"

    def test_other_blocks_html(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _safe_upload_ext("other", "page.html", "text/html")
        assert ei.value.status_code == 400

    def test_other_blocks_executable(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _safe_upload_ext("other", "tool.exe", "application/octet-stream")
        assert ei.value.status_code == 400

    def test_oversized_ext_rejected(self) -> None:
        with pytest.raises(HTTPException) as ei:
            _safe_upload_ext("other", "x." + "a" * 32, "application/octet-stream")
        assert ei.value.status_code == 400

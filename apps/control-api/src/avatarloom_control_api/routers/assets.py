"""Assets 路由——Avatar 资产文件的上传/下载/预览/删除。

资产存储：相对 assets_root 的路径，按 avatar_id/kind 分类。
文件服务：通过 StreamingResponse 返回，带正确 Content-Type。
"""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Asset, Avatar
from avatarloom_control_api.schemas import AssetOut, EmptyResponse

router = APIRouter()

# 允许的资产 kind 和对应 mime 前缀
_KIND_MIME_PREFIX: dict[str, str] = {
    "portrait": "image/",
    "idle_video": "video/",
    "voice_ref": "audio/",
    "image": "image/",
    "video": "video/",
    "audio": "audio/",
    "other": "",
}

# 文件大小上限（50MB）——防止滥用
_MAX_SIZE = 50 * 1024 * 1024


def _assets_root(request_db: AsyncSession) -> Path:
    """从 app.state.settings 取 assets_root。"""
    # db 依赖拿到 request，但更简单是从 settings 取——通过 app.state
    # 实际用法：在路由里从 request.app.state.settings 取
    return Path("./data/assets")  # 默认；app 启动时会被覆盖


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(asset_id: str, db: AsyncSession = Depends(get_db)) -> Asset:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.get("/{asset_id}/file")
async def download_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
) -> FileResponse:
    """下载/预览资产文件。带正确 Content-Type，浏览器可直接渲染。"""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset not found")
    # 资产根 = settings.artifacts_root / "avatar_assets"（和上传路径一致）
    assets_root = Path(request.app.state.settings.artifacts_root) / "avatar_assets"
    path = assets_root / asset.path
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset file missing on disk")
    media_type = (
        asset.mime_type or mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
    )
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=asset.name,
    )


@router.delete("/{asset_id}", response_model=EmptyResponse)
async def delete_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
) -> EmptyResponse:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset not found")
    # 删文件
    assets_root = Path(request.app.state.settings.artifacts_root) / "avatar_assets"
    path = assets_root / asset.path
    if path.exists():
        await anyio.to_thread.run_sync(path.unlink)
    # 清 Avatar 的当前引用（如果是 portrait/idle_video/voice_ref）
    if asset.avatar_id and asset.kind in ("portrait", "idle_video", "voice_ref"):
        avatar = await db.get(Avatar, asset.avatar_id)
        if avatar:
            field_map = {
                "portrait": "portrait_path",
                "idle_video": "idle_video_path",
                "voice_ref": "voice_ref_path",
            }
            field = field_map.get(asset.kind)
            if field and getattr(avatar, field) == asset.path:
                setattr(avatar, field, None)
                if asset.kind == "voice_ref":
                    avatar.voice_ref_text = None
    await db.delete(asset)
    await db.commit()
    return EmptyResponse()


# ---------------------------------------------------------------------------
# 给 avatars 路由用的上传辅助函数（不直接暴露为路由）
# ---------------------------------------------------------------------------


async def save_upload(
    upload: UploadFile,
    kind: str,
    avatar_id: str,
    db: AsyncSession,
    assets_root: Path,
) -> Asset:
    """保存上传文件为 Asset，更新 Avatar 的当前引用字段。"""
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    # 校验 kind
    if kind not in _KIND_MIME_PREFIX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid kind: {kind}")

    # 校验 mime（portrait 必须是图片等）
    mime = upload.content_type or ""
    expected_prefix = _KIND_MIME_PREFIX[kind]
    if expected_prefix and not mime.startswith(expected_prefix):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"kind={kind} requires {expected_prefix}* mime, got {mime}",
        )

    # 读内容 + 校验大小
    content = await upload.read()
    if len(content) > _MAX_SIZE:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large: {len(content)} bytes (max {_MAX_SIZE})",
        )

    # 写文件：assets_root/avatars/{avatar_id}/{kind}/{uuid}{ext}
    ext = Path(upload.filename or "").suffix or _default_ext(kind, mime)
    asset_id = f"asset_{uuid.uuid4().hex[:20]}"
    rel_dir = f"avatars/{avatar_id}/{kind}"
    abs_dir = assets_root / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{asset_id}{ext}"
    rel_path = f"{rel_dir}/{filename}"
    abs_path = assets_root / rel_path
    await anyio.to_thread.run_sync(abs_path.write_bytes, content)

    # 建 Asset 记录
    asset = Asset(
        id=asset_id,
        kind=kind,
        name=upload.filename or filename,
        path=rel_path,
        mime_type=mime or None,
        size_bytes=len(content),
        avatar_id=avatar_id,
        extra_metadata={},
    )
    db.add(asset)

    # 更新 Avatar 的当前引用字段
    field_map = {
        "portrait": "portrait_path",
        "idle_video": "idle_video_path",
        "voice_ref": "voice_ref_path",
    }
    field = field_map.get(kind)
    if field:
        setattr(avatar, field, rel_path)

    await db.commit()
    await db.refresh(asset)
    return asset


def _default_ext(kind: str, mime: str) -> str:
    """根据 kind/mime 推断默认扩展名。"""
    if kind in ("portrait", "image"):
        return ".png"
    if kind in ("idle_video", "video"):
        return ".mp4"
    if kind in ("voice_ref", "audio"):
        return ".wav"
    return ".bin"

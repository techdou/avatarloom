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

# 各媒体 kind 允许的扩展名（小写、含点）——名单外的扩展名不落盘，
# 防 .exe/.html/.svg 等可执行/Active Content 文件落盘后被下载渲染（同源 XSS）。
_ALLOWED_EXT: dict[str, frozenset[str]] = {
    "portrait": frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}),
    "image": frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}),
    "idle_video": frozenset({".mp4", ".webm", ".mov", ".m4v"}),
    "video": frozenset({".mp4", ".webm", ".mov", ".m4v"}),
    "voice_ref": frozenset({".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".opus"}),
    "audio": frozenset({".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".opus"}),
}

# kind=other 是自由扩展名（配合下载时强制 application/octet-stream + attachment），
# 但仍禁掉可执行/同源可渲染的 Active Content 扩展名，双保险。
_BLOCKED_OTHER_EXT = frozenset(
    {
        ".html", ".htm", ".xhtml", ".svg", ".xml", ".js", ".mjs",
        ".exe", ".dll", ".com", ".scr", ".msi", ".bat", ".cmd", ".ps1", ".sh",
        ".jar", ".php", ".asp", ".aspx", ".jsp",
    }
)

# 扩展名长度上限——文件名拼接收敛（asset_id + ext 落盘）
_MAX_EXT_LEN = 16


def _looks_like_image(content: bytes) -> bool:
    """轻量魔数校验：图片类上传不得只是扩展名/Content-Type 伪装。

    只覆盖确定性强的图片容器（PNG/JPEG/GIF/WebP/BMP）；视频/音频容器
    （MP4/WebM/WAV 等）起始原子不唯一，硬校验会误伤合法文件，保持现状。
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if content.startswith(b"\xff\xd8\xff"):
        return True
    if content.startswith((b"GIF87a", b"GIF89a")):
        return True
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return True
    return content.startswith(b"BM")


def resolve_asset_path(assets_root: Path, rel_path: str) -> Path:
    """把 DB 里的相对路径 resolve 成绝对路径，防目录穿越。

    resolve 后必须仍在 assets_root 内——拒绝 ``..`` 穿越与绝对路径
    （DB 记录被篡改/手工插入时兜底；正常路径由 save_upload 服务端生成）。
    越界 → 400。
    """
    root = assets_root.resolve()
    candidate = (root / rel_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid asset path")
    return candidate


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
    """下载/预览资产文件。带正确 Content-Type，浏览器可直接渲染。

    kind=other 例外：强制 application/octet-stream + attachment 下载——
    other 无 mime 白名单，若按上传时声明的 mime（如 image/png、text/html）
    内联渲染，等于给同源 Active Content 开后门（XSS）。
    """
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset not found")
    # 资产根 = settings.artifacts_root / "avatar_assets"（和上传路径一致）
    assets_root = Path(request.app.state.settings.artifacts_root) / "avatar_assets"
    path = resolve_asset_path(assets_root, asset.path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset file missing on disk")
    if asset.kind == "other":
        return FileResponse(
            path=str(path),
            media_type="application/octet-stream",
            filename=asset.name,  # FileResponse 默认 content_disposition_type=attachment
        )
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
    # 删文件（resolve 防穿越：DB path 被篡改时不动 assets_root 外的文件）
    assets_root = Path(request.app.state.settings.artifacts_root) / "avatar_assets"
    path = resolve_asset_path(assets_root, asset.path)
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

    # 读内容 + 校验大小——先读 MAX_SIZE+1 字节判断超限，避免数 GB body 全读进内存
    content = await upload.read(_MAX_SIZE + 1)
    if len(content) > _MAX_SIZE:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large (max {_MAX_SIZE} bytes)",
        )

    # 图片类按魔数校验真实内容——防 polyglot（扩展名 .png、内容是 HTML/JS）入库
    if kind in ("portrait", "image") and not _looks_like_image(content):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"File content does not match kind={kind} (expected a known image format)",
        )

    # 写文件：assets_root/avatars/{avatar_id}/{kind}/{uuid}{ext}
    ext = _safe_upload_ext(kind, upload.filename, mime)
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


def _safe_upload_ext(kind: str, filename: str | None, mime: str) -> str:
    """校验上传文件扩展名并返回可用扩展名（小写、含点）。

    - 媒体 kind（portrait/image/video/...）：扩展名必须在白名单内，否则 400；
      未带扩展名 → 按 kind/mime 给默认扩展名。
    - kind=other：自由扩展名，但禁可执行/Active Content（下载侧已强制
      octet-stream + attachment，这里是第二道闸）。
    """
    raw_ext = Path(filename or "").suffix.lower()
    if raw_ext and (len(raw_ext) > _MAX_EXT_LEN or any(c in raw_ext for c in "/\\")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Invalid extension: {raw_ext!r}")
    if kind in _ALLOWED_EXT:
        if raw_ext and raw_ext not in _ALLOWED_EXT[kind]:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Extension {raw_ext!r} not allowed for kind={kind}",
            )
        return raw_ext or _default_ext(kind, mime)
    # kind=other
    if raw_ext in _BLOCKED_OTHER_EXT:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Extension {raw_ext!r} not allowed for kind=other",
        )
    return raw_ext or _default_ext(kind, mime)


def _default_ext(kind: str, mime: str) -> str:
    """根据 kind/mime 推断默认扩展名。"""
    if kind in ("portrait", "image"):
        return ".png"
    if kind in ("idle_video", "video"):
        return ".mp4"
    if kind in ("voice_ref", "audio"):
        return ".wav"
    return ".bin"

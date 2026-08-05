"""Avatars CRUD + 资产管理路由。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Asset, Avatar
from avatarloom_control_api.routers.assets import save_upload
from avatarloom_control_api.schemas import (
    AssetOut,
    AvatarCreate,
    AvatarOut,
    AvatarUpdate,
    EmptyResponse,
)

router = APIRouter()


@router.get("", response_model=list[AvatarOut])
async def list_avatars(db: AsyncSession = Depends(get_db)) -> list[Avatar]:
    result = await db.execute(select(Avatar).order_by(Avatar.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{avatar_id}", response_model=AvatarOut)
async def get_avatar(avatar_id: str, db: AsyncSession = Depends(get_db)) -> Avatar:
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    return avatar


@router.post("", response_model=AvatarOut, status_code=status.HTTP_201_CREATED)
async def create_avatar(payload: AvatarCreate, db: AsyncSession = Depends(get_db)) -> Avatar:
    if await db.get(Avatar, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Avatar already exists")
    avatar = Avatar(**payload.model_dump())
    db.add(avatar)
    await db.commit()
    await db.refresh(avatar)
    return avatar


@router.patch("/{avatar_id}", response_model=AvatarOut)
async def update_avatar(
    avatar_id: str, payload: AvatarUpdate, db: AsyncSession = Depends(get_db)
) -> Avatar:
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(avatar, k, v)
    await db.commit()
    await db.refresh(avatar)
    return avatar


@router.delete("/{avatar_id}", response_model=EmptyResponse)
async def delete_avatar(avatar_id: str, db: AsyncSession = Depends(get_db)) -> EmptyResponse:
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    await db.delete(avatar)
    await db.commit()
    return EmptyResponse()


# ---------------------------------------------------------------------------
# 资产管理（嵌套在 /avatars/{avatar_id}/assets）
# ---------------------------------------------------------------------------


@router.get("/{avatar_id}/assets", response_model=list[AssetOut])
async def list_avatar_assets(avatar_id: str, db: AsyncSession = Depends(get_db)) -> list[Asset]:
    """列出某 Avatar 的所有资产。"""
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    result = await db.execute(
        select(Asset).where(Asset.avatar_id == avatar_id).order_by(Asset.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/{avatar_id}/assets",
    response_model=AssetOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_avatar_asset(
    avatar_id: str,
    kind: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
) -> Asset:
    """上传资产文件。multipart/form-data。

    kind 取值：portrait | idle_video | voice_ref | image | video | audio | other
    上传后自动更新 Avatar 的当前 portrait_path/idle_video_path/voice_ref_path。
    """
    assets_root = Path(request.app.state.settings.artifacts_root) / "avatar_assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    return await save_upload(file, kind, avatar_id, db, assets_root)


@router.post(
    "/{avatar_id}/voice-text",
    response_model=AvatarOut,
)
async def set_avatar_voice_text(
    avatar_id: str,
    payload: dict[str, str],
    db: AsyncSession = Depends(get_db),
) -> Avatar:
    """设置 voice_ref_text（音色参考文本，TTS 用）。

    body: {"text": "..."}
    """
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    avatar.voice_ref_text = payload.get("text", "")
    await db.commit()
    await db.refresh(avatar)
    return avatar


# ---------------------------------------------------------------------------
# 便捷端点：直接返回当前肖像/视频/音频文件（前端 img/video/audio src 用）
# ---------------------------------------------------------------------------


async def _serve_avatar_asset(
    avatar_id: str,
    field: str,
    db: AsyncSession,
    request: Request,
):
    """通用：按字段名返回 Avatar 当前资产文件。"""
    avatar = await db.get(Avatar, avatar_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    rel_path = getattr(avatar, field)
    if not rel_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"No {field} set")
    assets_root = Path(request.app.state.settings.artifacts_root) / "avatar_assets"
    abs_path = assets_root / rel_path
    if not abs_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File missing on disk")
    import mimetypes

    media = mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
    return FileResponse(path=str(abs_path), media_type=media)


@router.get("/{avatar_id}/portrait")
async def get_avatar_portrait(
    avatar_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
):
    """返回当前肖像图。前端 <img src="/api/avatars/{id}/portrait"> 直接用。"""
    return await _serve_avatar_asset(avatar_id, "portrait_path", db, request)


@router.get("/{avatar_id}/idle-video")
async def get_avatar_idle_video(
    avatar_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
):
    """返回当前 idle 视频。"""
    return await _serve_avatar_asset(avatar_id, "idle_video_path", db, request)


@router.get("/{avatar_id}/voice-ref")
async def get_avatar_voice_ref(
    avatar_id: str,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment]
):
    """返回当前音色参考音频。"""
    return await _serve_avatar_asset(avatar_id, "voice_ref_path", db, request)

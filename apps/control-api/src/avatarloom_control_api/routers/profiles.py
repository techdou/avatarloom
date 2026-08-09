"""Runtime Profiles CRUD 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.catalog import remove_profile_mirror, write_profile_mirror
from avatarloom_control_api.config import Settings
from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import RuntimeProfile
from avatarloom_control_api.schemas import (
    EmptyResponse,
    RuntimeProfileCreate,
    RuntimeProfileOut,
    RuntimeProfileUpdate,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _mirror(request: Request, profile: RuntimeProfile) -> None:
    try:
        write_profile_mirror(request.app.state.settings, profile)
    except OSError:
        logger.exception("profile mirror write failed: %s", profile.id)


@router.get("", response_model=list[RuntimeProfileOut])
async def list_profiles(
    limit: int = Query(200, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
) -> list[RuntimeProfile]:
    result = await db.execute(
        select(RuntimeProfile)
        .order_by(RuntimeProfile.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


@router.get("/{profile_id}", response_model=RuntimeProfileOut)
async def get_profile(profile_id: str, db: AsyncSession = Depends(get_db)) -> RuntimeProfile:
    profile = await db.get(RuntimeProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


@router.post("", response_model=RuntimeProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: RuntimeProfileCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RuntimeProfile:
    if await db.get(RuntimeProfile, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Profile already exists")
    profile = RuntimeProfile(**payload.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    _mirror(request, profile)
    return profile


@router.patch("/{profile_id}", response_model=RuntimeProfileOut)
async def update_profile(
    profile_id: str,
    payload: RuntimeProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RuntimeProfile:
    profile = await db.get(RuntimeProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    updates = payload.model_dump(exclude_unset=True)
    if "sync" in updates:
        # ``session`` 暂存在 sync._session，属于运行时配置而不是 Studio 的
        # 音画同步表单。更新/清空 sync 时必须保留它，否则一次普通编辑就会
        # 悄悄把 YAML 的 session 参数从数据库真相和镜像中删除。
        existing_session = (profile.sync or {}).get("_session")
        sync = dict(updates["sync"] or {})
        if existing_session is not None and "_session" not in sync:
            sync["_session"] = existing_session
        updates["sync"] = sync or None
    for k, v in updates.items():
        setattr(profile, k, v)
    await db.commit()
    await db.refresh(profile)
    _mirror(request, profile)
    return profile


@router.delete("/{profile_id}", response_model=EmptyResponse)
async def delete_profile(
    profile_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> EmptyResponse:
    profile = await db.get(RuntimeProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    await db.delete(profile)
    await db.commit()
    settings: Settings = request.app.state.settings
    try:
        remove_profile_mirror(settings, profile_id)
    except OSError:
        logger.exception("profile mirror delete failed: %s", profile_id)
    return EmptyResponse()

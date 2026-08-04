"""Avatars CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Avatar
from avatarloom_control_api.schemas import (
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

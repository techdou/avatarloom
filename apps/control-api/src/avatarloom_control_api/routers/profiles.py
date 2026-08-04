"""Runtime Profiles CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import RuntimeProfile
from avatarloom_control_api.schemas import (
    EmptyResponse,
    RuntimeProfileCreate,
    RuntimeProfileOut,
    RuntimeProfileUpdate,
)

router = APIRouter()


@router.get("", response_model=list[RuntimeProfileOut])
async def list_profiles(db: AsyncSession = Depends(get_db)) -> list[RuntimeProfile]:
    result = await db.execute(select(RuntimeProfile).order_by(RuntimeProfile.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{profile_id}", response_model=RuntimeProfileOut)
async def get_profile(profile_id: str, db: AsyncSession = Depends(get_db)) -> RuntimeProfile:
    profile = await db.get(RuntimeProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


@router.post("", response_model=RuntimeProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: RuntimeProfileCreate, db: AsyncSession = Depends(get_db)
) -> RuntimeProfile:
    if await db.get(RuntimeProfile, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Profile already exists")
    profile = RuntimeProfile(**payload.model_dump())
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.patch("/{profile_id}", response_model=RuntimeProfileOut)
async def update_profile(
    profile_id: str,
    payload: RuntimeProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> RuntimeProfile:
    profile = await db.get(RuntimeProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(profile, k, v)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/{profile_id}", response_model=EmptyResponse)
async def delete_profile(profile_id: str, db: AsyncSession = Depends(get_db)) -> EmptyResponse:
    profile = await db.get(RuntimeProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Profile not found")
    await db.delete(profile)
    await db.commit()
    return EmptyResponse()

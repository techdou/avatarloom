"""Secret References CRUD 路由。

注意：这里只存环境变量名和"是否已设置"标记，绝不存实际 key 值。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import SecretReference
from avatarloom_control_api.schemas import (
    EmptyResponse,
    SecretReferenceCreate,
    SecretReferenceOut,
)

router = APIRouter()


@router.get("", response_model=list[SecretReferenceOut])
async def list_secrets(db: AsyncSession = Depends(get_db)) -> list[SecretReference]:
    result = await db.execute(select(SecretReference).order_by(SecretReference.name))
    # 更新 is_set（基于当前 env）
    secrets = list(result.scalars().all())
    for s in secrets:
        s.is_set = bool(os.environ.get(s.env_var))
    return secrets


@router.post("", response_model=SecretReferenceOut, status_code=status.HTTP_201_CREATED)
async def create_secret(
    payload: SecretReferenceCreate, db: AsyncSession = Depends(get_db)
) -> SecretReference:
    if await db.get(SecretReference, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Secret already exists")
    secret = SecretReference(
        **payload.model_dump(),
        is_set=bool(os.environ.get(payload.env_var)),
    )
    db.add(secret)
    await db.commit()
    await db.refresh(secret)
    return secret


@router.delete("/{secret_id}", response_model=EmptyResponse)
async def delete_secret(secret_id: str, db: AsyncSession = Depends(get_db)) -> EmptyResponse:
    secret = await db.get(SecretReference, secret_id)
    if secret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Secret not found")
    await db.delete(secret)
    await db.commit()
    return EmptyResponse()

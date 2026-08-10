"""Personas CRUD 路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Persona
from avatarloom_control_api.schemas import (
    EmptyResponse,
    PersonaCreate,
    PersonaOut,
    PersonaUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _warn_conflicting_avatar_refs(persona_id: str, payload_dict: dict[str, object]) -> None:
    """avatar_id 与 avatar_ref 同时设置时记 warning：avatar_id 优先，avatar_ref 被忽略。

    存量数据可能两者都有（历史遗留），不拒绝、不报 422——只记日志提示收敛到 avatar_id。
    """
    if payload_dict.get("avatar_id") is not None and payload_dict.get("avatar_ref") is not None:
        logger.warning(
            "Persona %s 同时设置 avatar_id=%r 与 avatar_ref=%r；以 avatar_id 为准，"
            "avatar_ref 被忽略。请迁移到仅使用 avatar_id。",
            persona_id,
            payload_dict["avatar_id"],
            payload_dict["avatar_ref"],
        )


@router.get("", response_model=list[PersonaOut])
async def list_personas(
    limit: int = Query(200, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
) -> list[Persona]:
    result = await db.execute(
        select(Persona).order_by(Persona.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


@router.get("/{persona_id}", response_model=PersonaOut)
async def get_persona(persona_id: str, db: AsyncSession = Depends(get_db)) -> Persona:
    persona = await db.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Persona not found")
    return persona


@router.post("", response_model=PersonaOut, status_code=status.HTTP_201_CREATED)
async def create_persona(payload: PersonaCreate, db: AsyncSession = Depends(get_db)) -> Persona:
    if await db.get(Persona, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Persona already exists")
    _warn_conflicting_avatar_refs(payload.id, payload.model_dump())
    persona = Persona(**payload.model_dump())
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    return persona


@router.patch("/{persona_id}", response_model=PersonaOut)
async def update_persona(
    persona_id: str, payload: PersonaUpdate, db: AsyncSession = Depends(get_db)
) -> Persona:
    persona = await db.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Persona not found")
    update_dict = payload.model_dump(exclude_unset=True)
    _warn_conflicting_avatar_refs(persona_id, update_dict)
    for k, v in update_dict.items():
        setattr(persona, k, v)
    await db.commit()
    await db.refresh(persona)
    return persona


@router.delete("/{persona_id}", response_model=EmptyResponse)
async def delete_persona(persona_id: str, db: AsyncSession = Depends(get_db)) -> EmptyResponse:
    persona = await db.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Persona not found")
    await db.delete(persona)
    await db.commit()
    return EmptyResponse()

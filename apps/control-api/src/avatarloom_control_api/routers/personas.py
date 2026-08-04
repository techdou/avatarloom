"""Personas CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
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

router = APIRouter()


@router.get("", response_model=list[PersonaOut])
async def list_personas(db: AsyncSession = Depends(get_db)) -> list[Persona]:
    result = await db.execute(select(Persona).order_by(Persona.created_at.desc()))
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
    for k, v in payload.model_dump(exclude_unset=True).items():
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

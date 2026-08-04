"""Block Definitions CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import BlockDefinition
from avatarloom_control_api.schemas import (
    BlockDefinitionCreate,
    BlockDefinitionOut,
    EmptyResponse,
)

router = APIRouter()


@router.get("", response_model=list[BlockDefinitionOut])
async def list_blocks(
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[BlockDefinition]:
    stmt = select(BlockDefinition).order_by(BlockDefinition.category, BlockDefinition.id)
    if category:
        stmt = stmt.where(BlockDefinition.category == category)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{block_id}", response_model=BlockDefinitionOut)
async def get_block(block_id: str, db: AsyncSession = Depends(get_db)) -> BlockDefinition:
    block = await db.get(BlockDefinition, block_id)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Block not found")
    return block


@router.post("", response_model=BlockDefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_block(
    payload: BlockDefinitionCreate, db: AsyncSession = Depends(get_db)
) -> BlockDefinition:
    if await db.get(BlockDefinition, payload.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Block already exists")
    block = BlockDefinition(**payload.model_dump())
    db.add(block)
    await db.commit()
    await db.refresh(block)
    return block


@router.delete("/{block_id}", response_model=EmptyResponse)
async def delete_block(block_id: str, db: AsyncSession = Depends(get_db)) -> EmptyResponse:
    block = await db.get(BlockDefinition, block_id)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Block not found")
    await db.delete(block)
    await db.commit()
    return EmptyResponse()

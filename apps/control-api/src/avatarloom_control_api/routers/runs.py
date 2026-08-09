"""Runs 只读路由。Run 由 Runtime 写入。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Run
from avatarloom_control_api.schemas import RunOut

router = APIRouter()


@router.get("", response_model=list[RunOut])
async def list_runs(
    session_id: str | None = None,
    status_filter: str | None = None,
    limit: int = Query(200, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
) -> list[Run]:
    stmt = select(Run).order_by(Run.started_at.desc())
    if session_id:
        stmt = stmt.where(Run.session_id == session_id)
    if status_filter:
        stmt = stmt.where(Run.status == status_filter)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run

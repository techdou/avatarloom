"""Runs 路由——查询 + Runtime Gateway 生命周期上报。

Run 的权威数据在文件系统（runs_root 的 metrics/transcript/events），
DB 记录是 Studio 列表/详情页的数据源，由 Gateway 在 run 开始/结束时上报。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Run
from avatarloom_control_api.schemas import RunOut, RunReport, RunUpdate

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


@router.post("", response_model=RunOut)
async def report_run_start(
    payload: RunReport, db: AsyncSession = Depends(get_db)
) -> Run:
    """Runtime Gateway 上报 Run 开始（upsert——重试幂等）。"""
    run = await db.get(Run, payload.id)
    if run is None:
        run = Run(**payload.model_dump(), started_at=datetime.now(UTC))
        db.add(run)
    else:
        for k, v in payload.model_dump().items():
            setattr(run, k, v)
    await db.commit()
    await db.refresh(run)
    return run


@router.patch("/{run_id}", response_model=RunOut)
async def update_run(
    run_id: str,
    payload: RunUpdate,
    db: AsyncSession = Depends(get_db),
) -> Run:
    """Runtime Gateway 上报 Run 收尾（status/metrics/transcript）。"""
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    update_dict = payload.model_dump(exclude_unset=True)
    for k, v in update_dict.items():
        setattr(run, k, v)
    if "status" in update_dict and run.ended_at is None:
        run.ended_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(run)
    return run

"""Runs 只读路由：合并 Runtime Recorder 文件索引与兼容 DB 记录。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Run
from avatarloom_control_api.run_catalog import list_run_files, load_run
from avatarloom_control_api.schemas import RESOURCE_ID_PATTERN, RunOut

router = APIRouter()


@router.get("", response_model=list[RunOut])
async def list_runs(
    request: Request,
    session_id: str | None = None,
    status_filter: str | None = None,
    limit: int = Query(200, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
) -> list[Run | dict]:
    stmt = select(Run).order_by(Run.started_at.desc())
    if session_id:
        stmt = stmt.where(Run.session_id == session_id)
    if status_filter:
        stmt = stmt.where(Run.status == status_filter)
    result = await db.execute(stmt)
    database_runs = list(result.scalars().all())
    file_runs = list_run_files(request.app.state.settings.runs_root)
    if session_id:
        file_runs = [run for run in file_runs if run["session_id"] == session_id]
    if status_filter:
        file_runs = [run for run in file_runs if run["status"] == status_filter]
    file_ids = {run["id"] for run in file_runs}
    merged: list[Run | dict] = file_runs + [run for run in database_runs if run.id not in file_ids]
    return merged[offset : offset + limit]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    request: Request,
    run_id: str = Path(min_length=1, max_length=128, pattern=RESOURCE_ID_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> Run | dict:
    file_run = load_run(request.app.state.settings.runs_root, run_id)
    if file_run is not None:
        return file_run
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run

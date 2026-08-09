"""Sessions / Runs / Artifacts 只读路由。

Runtime Gateway 写 Recorder manifest；这里优先索引文件并兼容历史 DB 记录。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Session
from avatarloom_control_api.run_catalog import list_session_files
from avatarloom_control_api.schemas import RESOURCE_ID_PATTERN, SessionOut

router = APIRouter()


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    status_filter: str | None = None,
    limit: int = Query(200, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
) -> list[Session | dict]:
    stmt = select(Session).order_by(Session.started_at.desc())
    if status_filter:
        stmt = stmt.where(Session.status == status_filter)
    result = await db.execute(stmt)
    database_sessions = list(result.scalars().all())
    file_sessions = list_session_files(request.app.state.settings.runs_root)
    if status_filter:
        file_sessions = [item for item in file_sessions if item["status"] == status_filter]
    file_ids = {item["id"] for item in file_sessions}
    merged: list[Session | dict] = file_sessions + [
        item for item in database_sessions if item.id not in file_ids
    ]
    return merged[offset : offset + limit]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(
    request: Request,
    session_id: str = Path(min_length=1, max_length=128, pattern=RESOURCE_ID_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> Session | dict:
    for item in list_session_files(request.app.state.settings.runs_root):
        if item["id"] == session_id:
            return item
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session

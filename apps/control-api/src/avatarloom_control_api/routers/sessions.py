"""Sessions / Runs / Artifacts 路由。

Session 由 Runtime Gateway 创建/收尾（POST/PATCH 上报），这里同时提供查询接口。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Session
from avatarloom_control_api.schemas import SessionOut, SessionReport, SessionUpdate

router = APIRouter()


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    status_filter: str | None = None,
    limit: int = Query(200, ge=1, le=1000, description="返回数量上限"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: AsyncSession = Depends(get_db),
) -> list[Session]:
    stmt = select(Session).order_by(Session.started_at.desc())
    if status_filter:
        stmt = stmt.where(Session.status == status_filter)
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> Session:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("", response_model=SessionOut)
async def report_session_start(
    payload: SessionReport, db: AsyncSession = Depends(get_db)
) -> Session:
    """Runtime Gateway 上报会话开始（upsert——重试幂等）。"""
    session = await db.get(Session, payload.id)
    if session is None:
        session = Session(
            **payload.model_dump(),
            started_at=datetime.now(timezone.utc),
        )
        db.add(session)
    else:
        for k, v in payload.model_dump().items():
            setattr(session, k, v)
    await db.commit()
    await db.refresh(session)
    return session


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(
    session_id: str,
    payload: SessionUpdate,
    db: AsyncSession = Depends(get_db),
) -> Session:
    """Runtime Gateway 上报会话收尾（status/ended_at）。"""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
    update_dict = payload.model_dump(exclude_unset=True)
    for k, v in update_dict.items():
        setattr(session, k, v)
    if "status" in update_dict and session.ended_at is None:
        session.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(session)
    return session

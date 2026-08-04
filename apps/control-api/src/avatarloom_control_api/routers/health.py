"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthOut:
    """健康检查。"""
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return HealthOut(status="ok", version="0.1.0", db_ok=db_ok)

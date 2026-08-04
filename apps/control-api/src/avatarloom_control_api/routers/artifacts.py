"""Artifacts 只读路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from avatarloom_control_api.deps import get_db
from avatarloom_control_api.models import Artifact
from avatarloom_control_api.schemas import ArtifactOut

router = APIRouter()


@router.get("", response_model=list[ArtifactOut])
async def list_artifacts(
    run_id: str | None = None,
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[Artifact]:
    stmt = select(Artifact).order_by(Artifact.created_at.desc())
    if run_id:
        stmt = stmt.where(Artifact.run_id == run_id)
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(artifact_id: str, db: AsyncSession = Depends(get_db)) -> Artifact:
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return artifact

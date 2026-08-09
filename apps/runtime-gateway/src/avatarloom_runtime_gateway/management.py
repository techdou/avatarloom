"""Runtime Gateway 运维 API。

端点只暴露当前单 worker 的运行时快照。服务启动参数必须保持 workers=1；
多实例场景需要外部状态存储，不能把模块级 orchestrator 当成集群真相。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field

from avatarloom_runtime_gateway.auth import verify_http_token
from avatarloom_runtime_gateway.ws_handler import get_active_orchestrator

router = APIRouter(
    prefix="/api",
    tags=["operations"],
    dependencies=[Depends(verify_http_token)],
)

_RESOURCE_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$"
_BLOCK_HEALTH_TIMEOUT_S = 2.0
_ALL_BLOCKS_TIMEOUT_S = 3.0


class BlockHealthItem(BaseModel):
    category: str
    block_id: str | None = None
    deployment: str
    status: Literal["healthy", "degraded", "unhealthy", "absent"]
    detail: str = ""
    latency_ms: float | None = None


class BlocksHealthResponse(BaseModel):
    active: bool
    profile_id: str | None = None
    degraded: dict[str, str] = Field(default_factory=dict)
    blocks: list[BlockHealthItem] = Field(default_factory=list)


class MemoryItem(BaseModel):
    id: str
    memory: str = ""
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"extra": "allow"}


class MemoryListResponse(BaseModel):
    active: bool
    persona_id: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


class MemoryMutationResponse(BaseModel):
    ok: bool = True


class AddMemoryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    persona_id: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN)


async def _block_health(category: str, block_ref: Any, block: Any) -> BlockHealthItem:
    item = BlockHealthItem(
        category=category,
        deployment=str(block_ref.deployment),
        status="absent",
        detail="未装配（optional 跳过或装配失败）",
    )
    if block is None:
        return item
    item.block_id = str(block.manifest().block_id)
    try:
        health = await asyncio.wait_for(block.health(), timeout=_BLOCK_HEALTH_TIMEOUT_S)
        item.status = health.status
        item.latency_ms = health.latency_ms
        item.detail = health.message or ""
    except TimeoutError:
        item.status = "unhealthy"
        item.detail = f"health() 超时（>{_BLOCK_HEALTH_TIMEOUT_S:g}s）"
    except Exception as exc:  # 运维快照必须隔离单个 block 故障
        item.status = "unhealthy"
        item.detail = str(exc)[:200]
    return item


@router.get("/health/blocks", response_model=BlocksHealthResponse)
async def blocks_health() -> BlocksHealthResponse:
    orch = get_active_orchestrator()
    if orch is None:
        return BlocksHealthResponse(active=False)

    tasks = [
        _block_health(category, ref, orch.blocks.get(category))
        for category, ref in orch.config.blocks.items()
    ]
    try:
        items = await asyncio.wait_for(asyncio.gather(*tasks), timeout=_ALL_BLOCKS_TIMEOUT_S)
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="block health snapshot timed out",
        ) from exc
    return BlocksHealthResponse(
        active=True,
        profile_id=orch.config.profile_id,
        degraded=dict(orch.degraded_blocks),
        blocks=items,
    )


def _active_memory() -> tuple[Any, Any]:
    orch = get_active_orchestrator()
    memory = cast(Any, orch.blocks.get("memory")) if orch else None
    if memory is None or not bool(getattr(memory, "active", False)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="memory block 未启用",
        )
    return orch, memory


@router.get("/memory", response_model=MemoryListResponse)
async def list_memory(persona_id: str | None = None) -> MemoryListResponse:
    orch = get_active_orchestrator()
    memory = cast(Any, orch.blocks.get("memory")) if orch else None
    agent = persona_id or (orch.sessions.first_active_persona_id() if orch else None)
    if memory is None or not bool(getattr(memory, "active", False)):
        return MemoryListResponse(active=False, persona_id=agent)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="缺少 persona_id",
        )
    try:
        items = await memory.list_memories(agent)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="记忆存储读取失败",
        ) from exc
    return MemoryListResponse(active=True, persona_id=agent, items=items)


@router.post(
    "/memory",
    response_model=MemoryMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_memory(payload: AddMemoryRequest) -> MemoryMutationResponse:
    orch, memory = _active_memory()
    agent = payload.persona_id or orch.sessions.first_active_persona_id()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="缺少 persona_id",
        )
    try:
        ok = await memory.add_memory(payload.text.strip(), agent)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="记忆写入失败",
        ) from exc
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="记忆写入失败",
        )
    return MemoryMutationResponse()


@router.delete("/memory/{memory_id}", response_model=MemoryMutationResponse)
async def delete_memory(
    memory_id: str = Path(pattern=_RESOURCE_ID_PATTERN),
) -> MemoryMutationResponse:
    _, memory = _active_memory()
    try:
        ok = await memory.delete_memory(memory_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="记忆删除失败",
        ) from exc
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="记忆删除失败",
        )
    return MemoryMutationResponse()

"""Pydantic API schemas（请求/响应模型）。

和 ORM models 分开——API 层用 schemas，DB 层用 models。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    """所有从 ORM 序列化的 schema 基类。"""

    model_config = ConfigDict(from_attributes=True)


# 资源 ID 统一格式：字母/数字开头，后续可含字母数字、`.` `_` `-`。
# 禁止 `/` `\` `..` 空格等——id 会拼进文件路径与 URL，防路径穿越与注入。
# （Block id 含点，如 "vad.mock"，故允许 `.`。）
RESOURCE_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$"


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=RESOURCE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    settings: dict[str, Any] | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None


class ProjectOut(ORMBase):
    id: str
    name: str
    description: str | None
    settings: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Avatar
# ---------------------------------------------------------------------------


class AvatarCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=RESOURCE_ID_PATTERN)
    project_id: str
    name: str = Field(min_length=1, max_length=256)
    persona_id: str | None = None
    profile_id: str | None = None
    avatar_block: str | None = None
    description: str | None = None


class AvatarUpdate(BaseModel):
    name: str | None = None
    persona_id: str | None = None
    profile_id: str | None = None
    status: str | None = None
    avatar_block: str | None = None
    description: str | None = None


class AvatarOut(ORMBase):
    id: str
    project_id: str
    name: str
    persona_id: str | None
    profile_id: str | None
    status: str
    portrait_path: str | None
    idle_video_path: str | None
    voice_ref_path: str | None
    voice_ref_text: str | None
    avatar_block: str | None
    description: str | None
    extra_assets: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Asset（Avatar 资产）
# ---------------------------------------------------------------------------

AssetKind = Literal["portrait", "idle_video", "voice_ref", "image", "video", "audio", "other"]


class AssetOut(ORMBase):
    id: str
    kind: str
    name: str
    path: str
    mime_type: str | None
    size_bytes: int | None
    avatar_id: str | None
    extra_metadata: dict[str, Any] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------


class PersonaCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=RESOURCE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=256)
    label: str | None = None
    prompt: str = ""
    package_path: str | None = None
    voice_ref: dict[str, Any] | None = None
    avatar_ref: dict[str, Any] | None = None
    avatar_id: str | None = None
    behavior: dict[str, Any] | None = None


class PersonaUpdate(BaseModel):
    name: str | None = None
    label: str | None = None
    prompt: str | None = None
    voice_ref: dict[str, Any] | None = None
    avatar_ref: dict[str, Any] | None = None
    avatar_id: str | None = None
    behavior: dict[str, Any] | None = None


class PersonaOut(ORMBase):
    id: str
    name: str
    label: str | None
    version: str
    prompt: str
    package_path: str | None
    voice_ref: dict[str, Any] | None
    avatar_ref: dict[str, Any] | None
    avatar_id: str | None
    behavior: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Block Definition
# ---------------------------------------------------------------------------


class BlockDefinitionCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=RESOURCE_ID_PATTERN)
    name: str
    category: str
    version: str = "0.1.0"
    runtime_type: str = "python_inproc"
    entrypoint: str | None = None
    capabilities: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    config_schema: dict[str, Any] | None = None
    install_extras: list[str] | None = None


class BlockDefinitionOut(ORMBase):
    id: str
    name: str
    category: str
    version: str
    runtime_type: str
    entrypoint: str | None
    capabilities: dict[str, Any] | None
    resources: dict[str, Any] | None
    inputs: list[str] | None
    outputs: list[str] | None
    config_schema: dict[str, Any] | None
    install_extras: list[str] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Runtime Profile
# ---------------------------------------------------------------------------


class RuntimeProfileCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=RESOURCE_ID_PATTERN)
    name: str
    blocks: dict[str, Any] = Field(default_factory=dict)
    sync: dict[str, Any] | None = None
    description: str | None = None


class RuntimeProfileUpdate(BaseModel):
    name: str | None = None
    blocks: dict[str, Any] | None = None
    sync: dict[str, Any] | None = None
    description: str | None = None


class RuntimeProfileOut(ORMBase):
    id: str
    name: str
    blocks: dict[str, Any]
    sync: dict[str, Any] | None
    description: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Session / Run
# ---------------------------------------------------------------------------


class SessionOut(ORMBase):
    id: str
    avatar_id: str | None
    profile_id: str | None
    persona_id: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None


class RunOut(ORMBase):
    id: str
    session_id: str
    profile_id: str | None
    persona_id: str | None
    status: str
    metrics: dict[str, Any] | None
    run_dir: str | None
    user_text: str
    assistant_text: str
    started_at: datetime
    ended_at: datetime | None


class ArtifactOut(ORMBase):
    id: str
    run_id: str
    kind: str
    path: str
    mime_type: str | None
    size_bytes: int | None
    extra_metadata: dict[str, Any] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Secret Reference
# ---------------------------------------------------------------------------


class SecretReferenceCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=RESOURCE_ID_PATTERN)
    name: str
    env_var: str
    description: str | None = None


class SecretReferenceOut(ORMBase):
    id: str
    name: str
    env_var: str
    description: str | None
    is_set: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------


class HealthOut(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    db_ok: bool = True


class ErrorOut(BaseModel):
    detail: str
    code: str | None = None


class ListResponse(BaseModel):
    """通用列表响应。"""

    items: list[Any]
    total: int


class EmptyResponse(BaseModel):
    """通用空响应（DELETE 用）。"""

    ok: bool = True

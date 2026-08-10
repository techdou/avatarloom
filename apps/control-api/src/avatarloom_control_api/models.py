"""SQLAlchemy ORM 模型。

对应 docs/00 Control Plane 管理的对象：
Project / Avatar / Persona / BlockDefinition / RuntimeProfile / SecretReference /
Session / Run / Artifact / Evaluation
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """ORM 基类。"""


class Project(Base):
    """项目——顶层数字人集合。"""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    avatars: Mapped[list[Avatar]] = relationship(back_populates="project")


class Avatar(Base):
    """数字人形象资产实体——独立的形象资源对象。

    与 Persona 解耦：Persona 通过 avatar_id 引用 Avatar。
    Avatar 持有肖像图、idle 视频、voice ref 等资产。
    """

    __tablename__ = "avatars"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(256))
    persona_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    # draft | active | archived
    # 当前资产引用（相对 assets_root 的路径）
    portrait_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idle_video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    voice_ref_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    voice_ref_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 元数据
    avatar_block: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 自定义资产（JSON: {key: path}）
    extra_assets: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    project: Mapped[Project] = relationship(back_populates="avatars")
    sessions: Mapped[list[Session]] = relationship(back_populates="avatar")
    assets: Mapped[list[Asset]] = relationship(
        back_populates="avatar", cascade="all, delete-orphan"
    )


class Asset(Base):
    """独立资产对象——Avatar 的肖像/idle/voice 等文件。

    单独建表便于复用 + 多 Avatar 引用同一资产。
    """

    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_avatar_id", "avatar_id"),
        Index("ix_assets_kind", "kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    # portrait | idle_video | voice_ref | image | video | audio | other
    name: Mapped[str] = mapped_column(String(256))  # 原始文件名
    path: Mapped[str] = mapped_column(String(512))  # 相对 assets_root
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    avatar_id: Mapped[str | None] = mapped_column(
        ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True
    )
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    avatar: Mapped[Avatar | None] = relationship(back_populates="assets")


class Persona(Base):
    """Persona 包——人设 + 音色 + 形象引用。"""

    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    # 人设正文（system prompt）
    prompt: Mapped[str] = mapped_column(Text, default="")
    # 完整 Persona 包路径（相对 workspace）
    package_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # voice 引用（JSON）
    voice_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [DEPRECATED] avatar_ref 保留向后兼容；权威引用是 avatar_id。
    # 存量数据可能含 {id, portrait, ...}；新数据一律用 avatar_id 外键。
    avatar_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 权威 Avatar 引用（显式外键）。avatar_id 与 avatar_ref 同时存在时以本字段为准。
    avatar_id: Mapped[str | None] = mapped_column(
        ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True
    )
    behavior: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class BlockDefinition(Base):
    """Block 类型定义。对应 templates/block.yaml。"""

    __tablename__ = "block_definitions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 如 'tts.qwen3'
    name: Mapped[str] = mapped_column(String(256))
    version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    category: Mapped[str] = mapped_column(String(32), index=True)
    # vad/stt/llm/tts/avatar/vision/persona/memory/skills/transport
    runtime_type: Mapped[str] = mapped_column(String(32), default="python_inproc")
    entrypoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    capabilities: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resources: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    inputs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    outputs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    config_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    install_extras: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RuntimeProfile(Base):
    """Runtime Profile——一组 Block 配置。对应 profiles/*.yaml。"""

    __tablename__ = "runtime_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    # blocks: {category: {id, deployment, config, optional, fallback}}
    blocks: Mapped[dict] = mapped_column(JSON, default=dict)
    sync: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class SecretReference(Base):
    """Secret 引用——不存实际 key，只存环境变量名。"""

    __tablename__ = "secret_references"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    # 环境变量名（不存 value）
    env_var: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 标记是否已设置（检查时只看存在性，不读 value）
    is_set: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Session(Base):
    """会话记录。"""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_avatar_id", "avatar_id"),
        Index("ix_sessions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    avatar_id: Mapped[str | None] = mapped_column(ForeignKey("avatars.id"), nullable=True)
    profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persona_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    # active | closed | error
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    avatar: Mapped[Avatar | None] = relationship(back_populates="sessions")
    runs: Mapped[list[Run]] = relationship(back_populates="session")


class Run(Base):
    """单轮对话记录。"""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_session_id", "session_id"),
        Index("ix_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"))
    profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persona_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    # running | completed | interrupted | error | cancelled
    # 指标（JSON，对应 RunMetrics）
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # run 目录路径（相对 workspace）
    run_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    user_text: Mapped[str] = mapped_column(Text, default="")
    assistant_text: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    session: Mapped[Session] = relationship(back_populates="runs")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="run")


class Artifact(Base):
    """Artifact 记录。"""

    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_run_id", "run_id"),
        Index("ix_artifacts_kind", "kind"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    kind: Mapped[str] = mapped_column(String(32))
    # audio/video/image/text/json/config
    path: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped[Run] = relationship(back_populates="artifacts")

"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("settings", sa.JSON, nullable=True),
    )

    # avatars
    op.create_table(
        "avatars",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("persona_id", sa.String(64), nullable=True),
        sa.Column("profile_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # personas
    op.create_table(
        "personas",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="0.1.0"),
        sa.Column("prompt", sa.Text, nullable=False, server_default=""),
        sa.Column("package_path", sa.String(512), nullable=True),
        sa.Column("voice_ref", sa.JSON, nullable=True),
        sa.Column("avatar_ref", sa.JSON, nullable=True),
        sa.Column("behavior", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # block_definitions
    op.create_table(
        "block_definitions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(32), nullable=False, server_default="0.1.0"),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("runtime_type", sa.String(32), nullable=False, server_default="python_inproc"),
        sa.Column("entrypoint", sa.String(512), nullable=True),
        sa.Column("capabilities", sa.JSON, nullable=True),
        sa.Column("resources", sa.JSON, nullable=True),
        sa.Column("inputs", sa.JSON, nullable=True),
        sa.Column("outputs", sa.JSON, nullable=True),
        sa.Column("config_schema", sa.JSON, nullable=True),
        sa.Column("install_extras", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_block_definitions_category", "block_definitions", ["category"])

    # runtime_profiles
    op.create_table(
        "runtime_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("blocks", sa.JSON, nullable=False),
        sa.Column("sync", sa.JSON, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # secret_references
    op.create_table(
        "secret_references",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("env_var", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_set", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    # sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("avatar_id", sa.String(64), sa.ForeignKey("avatars.id"), nullable=True),
        sa.Column("profile_id", sa.String(64), nullable=True),
        sa.Column("persona_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("ended_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_sessions_avatar_id", "sessions", ["avatar_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])

    # runs
    op.create_table(
        "runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("profile_id", sa.String(64), nullable=True),
        sa.Column("persona_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("metrics", sa.JSON, nullable=True),
        sa.Column("run_dir", sa.String(512), nullable=True),
        sa.Column("user_text", sa.Text, nullable=False, server_default=""),
        sa.Column("assistant_text", sa.Text, nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("ended_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_runs_session_id", "runs", ["session_id"])
    op.create_index("ix_runs_status", "runs", ["status"])

    # artifacts
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("extra_metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_kind", "artifacts", ["kind"])


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("runs")
    op.drop_table("sessions")
    op.drop_table("secret_references")
    op.drop_table("runtime_profiles")
    op.drop_table("block_definitions")
    op.drop_table("personas")
    op.drop_table("avatars")
    op.drop_table("projects")

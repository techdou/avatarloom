"""avatar assets and persona avatar_id

Revision ID: 0002_avatar_assets
Revises: 0001_initial
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_avatar_assets"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Avatar 表加资产字段
    with op.batch_alter_table("avatars") as batch:
        batch.add_column(sa.Column("portrait_path", sa.String(512), nullable=True))
        batch.add_column(sa.Column("idle_video_path", sa.String(512), nullable=True))
        batch.add_column(sa.Column("voice_ref_path", sa.String(512), nullable=True))
        batch.add_column(sa.Column("voice_ref_text", sa.Text, nullable=True))
        batch.add_column(sa.Column("avatar_block", sa.String(128), nullable=True))
        batch.add_column(sa.Column("description", sa.Text, nullable=True))
        batch.add_column(sa.Column("extra_assets", sa.JSON, nullable=True))

    # 新增 assets 表
    op.create_table(
        "assets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column(
            "avatar_id",
            sa.String(64),
            sa.ForeignKey("avatars.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("extra_metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_assets_avatar_id", "assets", ["avatar_id"])
    op.create_index("ix_assets_kind", "assets", ["kind"])

    # Persona 表加 avatar_id（外键到 avatars）
    with op.batch_alter_table("personas") as batch:
        batch.add_column(
            sa.Column(
                "avatar_id",
                sa.String(64),
                sa.ForeignKey("avatars.id", ondelete="SET NULL"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("personas") as batch:
        batch.drop_column("avatar_id")
    op.drop_index("ix_assets_kind", table_name="assets")
    op.drop_index("ix_assets_avatar_id", table_name="assets")
    op.drop_table("assets")
    with op.batch_alter_table("avatars") as batch:
        batch.drop_column("extra_assets")
        batch.drop_column("description")
        batch.drop_column("avatar_block")
        batch.drop_column("voice_ref_text")
        batch.drop_column("voice_ref_path")
        batch.drop_column("idle_video_path")
        batch.drop_column("portrait_path")

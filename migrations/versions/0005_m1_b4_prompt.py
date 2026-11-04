"""B4：提示词版本表

Revision ID: m1_b4_prompt
Revises: m1_b3_employee_model
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1_b4_prompt"
down_revision = "m1_b3_employee_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_revision",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.String(length=32), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employee_id", "version", name="uq_prompt_employee_version"),
    )
    op.create_index("ix_prompt_revision_owner_id", "prompt_revision", ["owner_id"])
    op.create_index("ix_prompt_revision_employee_id", "prompt_revision", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_prompt_revision_employee_id", table_name="prompt_revision")
    op.drop_index("ix_prompt_revision_owner_id", table_name="prompt_revision")
    op.drop_table("prompt_revision")

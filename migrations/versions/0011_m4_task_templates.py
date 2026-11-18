"""M4-SOP：任务模板表——把跑通的任务计划沉淀为可复用模板

Revision ID: m4_task_templates
Revises: m4_auth_users
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m4_task_templates"
down_revision = "m4_auth_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_template",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("source_task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=True),
        sa.Column("source_task_title", sa.String(length=200), nullable=False, server_default=sa.text("''")),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_template_company", "task_template", ["company_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_task_template_company")
    op.drop_table("task_template")

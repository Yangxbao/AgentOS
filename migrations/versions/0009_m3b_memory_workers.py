"""M3-B/C/D：递归计划、长期记忆、多 Worker 的增量 schema

Revision ID: m3b_memory_workers
Revises: m3_a_tools
Create Date: 2026-11-06

只做增量：新列 + 新表 + FTS5 虚拟表；不改历史行。
FTS5 不可用时跳过 memory_fts（应用层降级为 LIKE 检索，见 packages/persistence/db.py）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m3b_memory_workers"
down_revision = "m3_a_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- task：M3-B 递归/重规划列 ----
    with op.batch_alter_table("task") as batch:
        batch.add_column(sa.Column("plan_revision", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.add_column(sa.Column("replan_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("max_depth", sa.Integer(), nullable=False, server_default=sa.text("3")))
        batch.add_column(sa.Column("max_total_steps", sa.Integer(), nullable=False, server_default=sa.text("50")))

    # ---- task_run：M3-D 租约/调度快照 ----
    with op.batch_alter_table("task_run") as batch:
        batch.add_column(sa.Column("lease_owner", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_index("ix_task_run_lease", "task_run", ["lease_owner", "state"])

    # ---- task_plan_revision：M3-B 计划版本 ----
    op.create_table(
        "task_plan_revision",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False, server_default=sa.text("'local'")),
        sa.Column("task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("failed_step_id", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default=sa.text("'local'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_plan_revision_task", "task_plan_revision", ["task_id", "revision"])

    # ---- memory_item：M3-C 长期记忆 ----
    op.create_table(
        "memory_item",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False, server_default=sa.text("'local'")),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default=sa.text("'employee'")),
        sa.Column("employee_id", sa.String(length=32), sa.ForeignKey("employee.id"), nullable=True),
        sa.Column("project_task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default=sa.text("'note'")),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=sa.text("''")),
        sa.Column("content", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source_task_id", sa.String(length=32), nullable=True),
        sa.Column("source_agent_run_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("promoted_by", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default=sa.text("'local'")),
        sa.Column("created_by_type", sa.String(length=16), nullable=False, server_default=sa.text("'user'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_item_owner", "memory_item", ["owner_id"])
    op.create_index("ix_memory_item_scope", "memory_item", ["scope"])
    op.create_index("ix_memory_item_company", "memory_item", ["company_id"])
    op.create_index("ix_memory_item_status", "memory_item", ["status"])
    op.create_index(
        "ix_memory_item_dedup", "memory_item",
        ["owner_id", "scope", "employee_id", "content_hash"],
    )

    # ---- memory_fts：FTS5（不可用则跳过，应用层降级）----
    try:
        op.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(title, content, tags)"
        )
    except Exception:  # noqa: BLE001 - 编译不含 FTS5 时降级
        pass


def downgrade() -> None:
    raise NotImplementedError("本项目只向前迁移（见 HANDOFF §6.3 铁律）")

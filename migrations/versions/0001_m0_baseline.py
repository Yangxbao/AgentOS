"""M0 基线：task / task_run / agent_run / task_event / usage_record

Revision ID: m0_baseline
Revises:
Create Date: 2026-11-05

注意：本 revision 是"已存在 M0 数据库"的基线，DDL 与 M0 的 models.py 完全一致
（不含 agent_run.employee_id，该列由 0002 添加）。已存在的库请先
`alembic stamp m0_baseline`，再 `alembic upgrade head`。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m0_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("rework_count", sa.Integer(), nullable=False),
        sa.Column("max_rework", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_state", "task", ["state"])

    op.create_table(
        "task_run",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("run_no", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_run_task_id", "task_run", ["task_id"])

    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("task_run_id", sa.String(length=32), sa.ForeignKey("task_run.id"), nullable=False),
        sa.Column("employee_key", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("adapter_type", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_run_task_run_id", "agent_run", ["task_run_id"])

    op.create_table(
        "task_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("task_run_id", sa.String(length=32), sa.ForeignKey("task_run.id"), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_task_event_task_id", "task_event", ["task_id"])

    op.create_table(
        "usage_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("agent_run_id", sa.String(length=32), sa.ForeignKey("agent_run.id"), nullable=False),
        sa.Column("employee_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_record_agent_run_id", "usage_record", ["agent_run_id"])
    op.create_index("ix_usage_record_employee_key", "usage_record", ["employee_key"])


def downgrade() -> None:
    op.drop_index("ix_usage_record_employee_key", table_name="usage_record")
    op.drop_index("ix_usage_record_agent_run_id", table_name="usage_record")
    op.drop_table("usage_record")
    op.drop_index("ix_task_event_task_id", table_name="task_event")
    op.drop_table("task_event")
    op.drop_index("ix_agent_run_task_run_id", table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_index("ix_task_run_task_id", table_name="task_run")
    op.drop_table("task_run")
    op.drop_index("ix_task_state", table_name="task")
    op.drop_table("task")

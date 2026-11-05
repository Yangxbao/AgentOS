"""M3-A：工作区、工作区授权、工具调用记录

Revision ID: m3_a_tools
Revises: m2_task_center
Create Date: 2026-11-05

只做增量：新表 + 新列 + 索引；不改历史行。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m3_a_tools"
down_revision = "m2_task_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("root_path", sa.String(length=512), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default=sa.text("'read_write'")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default=sa.text("'local'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "name", name="uq_workspace_company_name"),
        sa.UniqueConstraint("company_id", "slug", name="uq_workspace_company_slug"),
    )
    op.create_index("ix_workspace_owner_id", "workspace", ["owner_id"])
    op.create_index("ix_workspace_company_id", "workspace", ["company_id"])
    op.create_index("ix_workspace_status", "workspace", ["status"])

    op.create_table(
        "employee_workspace_grant",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.String(length=32), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("access", sa.String(length=16), nullable=False, server_default=sa.text("'read'")),
        sa.Column("granted_by", sa.String(length=64), nullable=False, server_default=sa.text("'local'")),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employee_id", "workspace_id", name="uq_grant_employee_workspace"),
    )
    op.create_index("ix_grant_owner_id", "employee_workspace_grant", ["owner_id"])
    op.create_index("ix_grant_employee_id", "employee_workspace_grant", ["employee_id"])
    op.create_index("ix_grant_workspace_id", "employee_workspace_grant", ["workspace_id"])

    op.create_table(
        "tool_call",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), nullable=True),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("task_run_id", sa.String(length=32), nullable=True),
        sa.Column("agent_run_id", sa.String(length=32), nullable=True),
        sa.Column("employee_id", sa.String(length=32), nullable=True),
        sa.Column("step_id", sa.String(length=32), nullable=False, server_default=sa.text("''")),
        sa.Column("call_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False, server_default=sa.text("''")),
        sa.Column("risk_level", sa.String(length=16), nullable=False, server_default=sa.text("'low'")),
        sa.Column("status", sa.String(length=24), nullable=False, server_default=sa.text("'requested'")),
        sa.Column("args_summary", sa.JSON(), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False, server_default=sa.text("''")),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("resolved_path", sa.String(length=512), nullable=False, server_default=sa.text("''")),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("output_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("approval_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tool_call_owner_id", "tool_call", ["owner_id"])
    op.create_index("ix_tool_call_company_id", "tool_call", ["company_id"])
    op.create_index("ix_tool_call_task_id", "tool_call", ["task_id"])
    op.create_index("ix_tool_call_task_run_id", "tool_call", ["task_run_id"])
    op.create_index("ix_tool_call_employee_id", "tool_call", ["employee_id"])
    op.create_index("ix_tool_call_tool_name", "tool_call", ["tool_name"])
    op.create_index("ix_tool_call_status", "tool_call", ["status"])
    op.create_index("ix_tool_call_idempotency_key", "tool_call", ["idempotency_key"])
    op.create_index("ix_tool_call_task_step", "tool_call", ["task_id", "step_id"])

    with op.batch_alter_table("task") as batch:
        batch.add_column(
            sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )

    with op.batch_alter_table("task_run") as batch:
        batch.add_column(
            sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )

    with op.batch_alter_table("task_approval") as batch:
        batch.add_column(sa.Column("tool_call_id", sa.String(length=32), nullable=True))
        batch.create_index("ix_task_approval_tool_call_id", ["tool_call_id"])


def downgrade() -> None:
    with op.batch_alter_table("task_approval") as batch:
        batch.drop_index("ix_task_approval_tool_call_id")
        batch.drop_column("tool_call_id")

    with op.batch_alter_table("task_run") as batch:
        batch.drop_column("tool_calls_count")

    with op.batch_alter_table("task") as batch:
        batch.drop_column("tool_calls_count")

    op.drop_index("ix_tool_call_task_step", table_name="tool_call")
    for name in (
        "ix_tool_call_idempotency_key", "ix_tool_call_status", "ix_tool_call_tool_name",
        "ix_tool_call_employee_id", "ix_tool_call_task_run_id", "ix_tool_call_task_id",
        "ix_tool_call_company_id", "ix_tool_call_owner_id",
    ):
        op.drop_index(name, table_name="tool_call")
    op.drop_table("tool_call")

    for name in ("ix_grant_workspace_id", "ix_grant_employee_id", "ix_grant_owner_id"):
        op.drop_index(name, table_name="employee_workspace_grant")
    op.drop_table("employee_workspace_grant")

    for name in ("ix_workspace_status", "ix_workspace_company_id", "ix_workspace_owner_id"):
        op.drop_index(name, table_name="workspace")
    op.drop_table("workspace")

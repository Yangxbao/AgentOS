"""M2：任务中心、执行检查点、审批与交接

Revision ID: m2_task_center
Revises: m1_b5_assignment_audit
Create Date: 2026-11-05

只做增量：新列 + 新表 + 部分唯一索引；不改历史行、不改历史状态值。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m2_task_center"
down_revision = "m1_b5_assignment_audit"
branch_labels = None
depends_on = None

TASK_COLUMNS = [
    ("company_id", sa.String(length=32), True),
    ("department_id", sa.String(length=32), True),
    ("parent_task_id", sa.String(length=32), True),
    ("root_task_id", sa.String(length=32), True),
    ("assignee_employee_id", sa.String(length=32), True),
    ("reviewer_employee_id", sa.String(length=32), True),
    ("depth", sa.Integer(), False),
    ("priority", sa.String(length=16), False),
    ("due_at", sa.DateTime(timezone=True), True),
    ("deliverable", sa.Text(), False),
    ("instruction", sa.Text(), False),
    ("context", sa.JSON(), False),
    ("plan", sa.JSON(), False),
    ("result", sa.JSON(), False),
    ("approval_required", sa.Boolean(), False),
    ("approval_stage", sa.String(length=16), False),
    ("risk_level", sa.String(length=16), False),
    ("budget_usd", sa.Float(), True),
    ("execution_mode", sa.String(length=16), False),
    ("cancel_requested", sa.Boolean(), False),
    ("pause_requested", sa.Boolean(), False),
    ("created_by", sa.String(length=64), False),
    ("started_at", sa.DateTime(timezone=True), True),
    ("ended_at", sa.DateTime(timezone=True), True),
    ("version", sa.Integer(), False),
]

TASK_DEFAULTS = {
    "depth": sa.text("0"),
    "priority": sa.text("'normal'"),
    "deliverable": sa.text("''"),
    "instruction": sa.text("''"),
    "context": sa.text("'{}'"),
    "plan": sa.text("'{}'"),
    "result": sa.text("'{}'"),
    "approval_required": sa.text("0"),
    "approval_stage": sa.text("'before_run'"),
    "risk_level": sa.text("'low'"),
    "execution_mode": sa.text("'auto'"),
    "cancel_requested": sa.text("0"),
    "pause_requested": sa.text("0"),
    "created_by": sa.text("'local'"),
    "version": sa.text("1"),
}

RUN_COLUMNS = [
    ("checkpoint", sa.JSON(), False),
    ("mode", sa.String(length=16), False),
    ("worker_id", sa.String(length=64), True),
    ("heartbeat_at", sa.DateTime(timezone=True), True),
    ("resumed_from_run_id", sa.String(length=32), True),
    ("approved_by", sa.String(length=64), True),
]

RUN_DEFAULTS = {
    "checkpoint": sa.text("'{}'"),
    "mode": sa.text("'real'"),
}


def upgrade() -> None:
    with op.batch_alter_table("task") as batch:
        for name, column_type, nullable in TASK_COLUMNS:
            batch.add_column(
                sa.Column(name, column_type, nullable=nullable, server_default=TASK_DEFAULTS.get(name))
            )
        batch.create_foreign_key("fk_task_company", "company", ["company_id"], ["id"])
        batch.create_foreign_key("fk_task_department", "department", ["department_id"], ["id"])
        batch.create_foreign_key("fk_task_parent", "task", ["parent_task_id"], ["id"])
        batch.create_foreign_key("fk_task_assignee", "employee", ["assignee_employee_id"], ["id"])
        batch.create_foreign_key("fk_task_reviewer", "employee", ["reviewer_employee_id"], ["id"])
        batch.create_index("ix_task_company_state", ["company_id", "state"])
        batch.create_index("ix_task_assignee_state", ["assignee_employee_id", "state"])
        batch.create_index("ix_task_parent", ["parent_task_id"])

    with op.batch_alter_table("task_run") as batch:
        for name, column_type, nullable in RUN_COLUMNS:
            batch.add_column(
                sa.Column(name, column_type, nullable=nullable, server_default=RUN_DEFAULTS.get(name))
            )

    with op.batch_alter_table("agent_run") as batch:
        batch.add_column(sa.Column("step_id", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("prompt_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("model_connection_id", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_agent_run_step_id", ["step_id"])

    op.create_index(
        "uq_task_run_active",
        "task_run",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued','running')"),
        postgresql_where=sa.text("state IN ('queued','running')"),
    )

    op.create_table(
        "task_approval",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("task_run_id", sa.String(length=32), nullable=True),
        sa.Column("gate", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("reviewer_employee_id", sa.String(length=32), nullable=True),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("rewind_step_id", sa.String(length=32), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_approval_owner_id", "task_approval", ["owner_id"])
    op.create_index("ix_task_approval_task_id", "task_approval", ["task_id"])
    op.create_index("ix_task_approval_status", "task_approval", ["status"])

    op.create_table(
        "agent_handoff",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("task_run_id", sa.String(length=32), sa.ForeignKey("task_run.id"), nullable=False),
        sa.Column("from_agent_run_id", sa.String(length=32), nullable=True),
        sa.Column("to_agent_run_id", sa.String(length=32), nullable=True),
        sa.Column("step_id", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_handoff_owner_id", "agent_handoff", ["owner_id"])
    op.create_index("ix_agent_handoff_task_id", "agent_handoff", ["task_id"])
    op.create_index("ix_agent_handoff_task_run_id", "agent_handoff", ["task_run_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_handoff_task_run_id", table_name="agent_handoff")
    op.drop_index("ix_agent_handoff_task_id", table_name="agent_handoff")
    op.drop_index("ix_agent_handoff_owner_id", table_name="agent_handoff")
    op.drop_table("agent_handoff")

    op.drop_index("ix_task_approval_status", table_name="task_approval")
    op.drop_index("ix_task_approval_task_id", table_name="task_approval")
    op.drop_index("ix_task_approval_owner_id", table_name="task_approval")
    op.drop_table("task_approval")

    op.drop_index("uq_task_run_active", table_name="task_run")

    with op.batch_alter_table("agent_run") as batch:
        batch.drop_index("ix_agent_run_step_id")
        for name in ("step_id", "prompt_version", "model_connection_id", "started_at", "ended_at"):
            batch.drop_column(name)

    with op.batch_alter_table("task_run") as batch:
        for name, _, _ in reversed(RUN_COLUMNS):
            batch.drop_column(name)

    with op.batch_alter_table("task") as batch:
        batch.drop_index("ix_task_parent")
        batch.drop_index("ix_task_assignee_state")
        batch.drop_index("ix_task_company_state")
        for fk in ("fk_task_company", "fk_task_department", "fk_task_parent",
                   "fk_task_assignee", "fk_task_reviewer"):
            batch.drop_constraint(fk, type_="foreignkey")
        for name, _, _ in reversed(TASK_COLUMNS):
            batch.drop_column(name)

"""B1：agent_run 增加 employee_id（可空，双写过渡期）

Revision ID: m1_b1_agent_run_employee_id
Revises: m0_baseline
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1_b1_agent_run_employee_id"
down_revision = "m0_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_run") as batch_op:
        batch_op.add_column(sa.Column("employee_id", sa.String(length=32), nullable=True))
    op.create_index("ix_agent_run_employee_id", "agent_run", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_employee_id", table_name="agent_run")
    with op.batch_alter_table("agent_run") as batch_op:
        batch_op.drop_column("employee_id")

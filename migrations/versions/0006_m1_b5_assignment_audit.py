"""B5：派工决策 + 审计日志

Revision ID: m1_b5_assignment_audit
Revises: m1_b4_prompt
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1_b5_assignment_audit"
down_revision = "m1_b4_prompt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assignment_decision",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("requested_by", sa.String(length=64), nullable=False),
        sa.Column("requirement", sa.JSON(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("selected_employee_id", sa.String(length=32), nullable=True),
        sa.Column("reviewer_employee_id", sa.String(length=32), nullable=True),
        sa.Column("reviewer_meta", sa.JSON(), nullable=False),
        sa.Column("data_quality", sa.JSON(), nullable=False),
        sa.Column("algorithm_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assignment_decision_owner_id", "assignment_decision", ["owner_id"])
    op.create_index("ix_assignment_decision_company_id", "assignment_decision", ["company_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_owner_id", "audit_log", ["owner_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_target_id", "audit_log", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_target_id", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_owner_id", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_assignment_decision_company_id", table_name="assignment_decision")
    op.drop_index("ix_assignment_decision_owner_id", table_name="assignment_decision")
    op.drop_table("assignment_decision")

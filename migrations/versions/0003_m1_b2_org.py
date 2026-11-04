"""B2：组织域 company / department / position

Revision ID: m1_b2_org
Revises: m1_b1_agent_run_employee_id
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1_b2_org"
down_revision = "m1_b1_agent_run_employee_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "name", name="uq_company_owner_name"),
    )
    op.create_index("ix_company_owner_id", "company", ["owner_id"])

    op.create_table(
        "department",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("parent_id", sa.String(length=32), sa.ForeignKey("department.id"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "name", name="uq_department_company_name"),
    )
    op.create_index("ix_department_owner_id", "department", ["owner_id"])
    op.create_index("ix_department_company_id", "department", ["company_id"])

    op.create_table(
        "position",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("department_id", sa.String(length=32), sa.ForeignKey("department.id"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("level", sa.String(length=24), nullable=False),
        sa.Column("is_managerial", sa.Boolean(), nullable=False),
        sa.Column("can_review", sa.Boolean(), nullable=False),
        sa.Column("review_capability_tags", sa.JSON(), nullable=False),
        sa.Column("responsibilities", sa.Text(), nullable=False),
        sa.Column("default_permissions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "name", name="uq_position_company_name"),
    )
    op.create_index("ix_position_owner_id", "position", ["owner_id"])
    op.create_index("ix_position_company_id", "position", ["company_id"])
    op.create_index("ix_position_department_id", "position", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_position_department_id", table_name="position")
    op.drop_index("ix_position_company_id", table_name="position")
    op.drop_index("ix_position_owner_id", table_name="position")
    op.drop_table("position")
    op.drop_index("ix_department_company_id", table_name="department")
    op.drop_index("ix_department_owner_id", table_name="department")
    op.drop_table("department")
    op.drop_index("ix_company_owner_id", table_name="company")
    op.drop_table("company")

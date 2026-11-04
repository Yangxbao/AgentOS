"""B3：员工与模型解耦（employee / employee_position / model_connection / model_switch_log + usage_record.employee_id）

Revision ID: m1_b3_employee_model
Revises: m1_b2_org
Create Date: 2026-11-05
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1_b3_employee_model"
down_revision = "m1_b2_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_connection",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("api_key_ref", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=True),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("model_list_source", sa.String(length=16), nullable=False),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_status", sa.String(length=16), nullable=True),
        sa.Column("last_health_latency_ms", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "company_id", "provider", "model", "base_url", name="uq_model_company_provider_model_url"
        ),
    )
    op.create_index("ix_model_connection_owner_id", "model_connection", ["owner_id"])
    op.create_index("ix_model_connection_company_id", "model_connection", ["company_id"])

    op.create_table(
        "employee",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("company_id", sa.String(length=32), sa.ForeignKey("company.id"), nullable=False),
        sa.Column("department_id", sa.String(length=32), sa.ForeignKey("department.id"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("avatar", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False),
        sa.Column("personality", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reports_to", sa.String(length=32), sa.ForeignKey("employee.id"), nullable=True),
        sa.Column("primary_model_id", sa.String(length=32), sa.ForeignKey("model_connection.id"), nullable=False),
        sa.Column("fallback_model_id", sa.String(length=32), sa.ForeignKey("model_connection.id"), nullable=True),
        sa.Column("adapter_type", sa.String(length=16), nullable=False),
        sa.Column("cli_profile", sa.JSON(), nullable=True),
        sa.Column("tools_allowed", sa.JSON(), nullable=False),
        sa.Column("permission_profile", sa.JSON(), nullable=False),
        sa.Column("capabilities_declared", sa.JSON(), nullable=False),
        sa.Column("prompt_active_version", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_employee_owner_id", "employee", ["owner_id"])
    op.create_index("ix_employee_company_id", "employee", ["company_id"])
    op.create_index("ix_employee_department_id", "employee", ["department_id"])
    op.create_index("ix_employee_reports_to", "employee", ["reports_to"])
    op.create_index("ix_employee_company_department", "employee", ["company_id", "department_id"])
    op.create_index(
        "uq_employee_company_name_active",
        "employee",
        ["company_id", "name"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "employee_position",
        sa.Column("employee_id", sa.String(length=32), sa.ForeignKey("employee.id"), primary_key=True),
        sa.Column("position_id", sa.String(length=32), sa.ForeignKey("position.id"), primary_key=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("department_id", sa.String(length=32), sa.ForeignKey("department.id"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "model_switch_log",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.String(length=32), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("from_model_id", sa.String(length=32), nullable=True),
        sa.Column("to_model_id", sa.String(length=32), nullable=True),
        sa.Column("slot", sa.String(length=16), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_switch_log_owner_id", "model_switch_log", ["owner_id"])
    op.create_index("ix_model_switch_log_employee_id", "model_switch_log", ["employee_id"])

    with op.batch_alter_table("usage_record") as batch_op:
        batch_op.add_column(sa.Column("employee_id", sa.String(length=32), nullable=True))
    op.create_index("ix_usage_record_employee_id", "usage_record", ["employee_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_record_employee_id", table_name="usage_record")
    with op.batch_alter_table("usage_record") as batch_op:
        batch_op.drop_column("employee_id")
    op.drop_index("ix_model_switch_log_employee_id", table_name="model_switch_log")
    op.drop_index("ix_model_switch_log_owner_id", table_name="model_switch_log")
    op.drop_table("model_switch_log")
    op.drop_table("employee_position")
    op.drop_index("uq_employee_company_name_active", table_name="employee")
    op.drop_index("ix_employee_company_department", table_name="employee")
    op.drop_index("ix_employee_reports_to", table_name="employee")
    op.drop_index("ix_employee_department_id", table_name="employee")
    op.drop_index("ix_employee_company_id", table_name="employee")
    op.drop_index("ix_employee_owner_id", table_name="employee")
    op.drop_table("employee")
    op.drop_index("ix_model_connection_company_id", table_name="model_connection")
    op.drop_index("ix_model_connection_owner_id", table_name="model_connection")
    op.drop_table("model_connection")

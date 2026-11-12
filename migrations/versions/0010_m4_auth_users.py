"""M4：账号体系——登录账号与会话表

Revision ID: m4_auth_users
Revises: m3b_memory_workers
Create Date: 2026-11-13

增量：sys_user + sys_session 两张表；种子默认管理员（username=admin，
owner_id='local'，绑定既有业务数据）。密码只存 PBKDF2 哈希（随机盐），
首次登录后应立即修改密码。认证开关 AGENTOS_AUTH 默认 off（行为兼容）。
"""
from __future__ import annotations

import hashlib
import secrets

import sqlalchemy as sa
from alembic import op

revision = "m4_auth_users"
down_revision = "m3b_memory_workers"
branch_labels = None
depends_on = None


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def upgrade() -> None:
    op.create_table(
        "sys_user",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("owner_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sys_session",
        sa.Column("token", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("sys_user.id"), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sys_session_user", "sys_session", ["user_id"])
    op.create_index("ix_sys_session_expires", "sys_session", ["expires_at"])

    # ---- 种子默认管理员（仅当无任何账号时；owner_id='local' 绑定既有业务数据） ----
    conn = op.get_bind()
    existing = conn.execute(sa.text("SELECT COUNT(*) FROM sys_user")).scalar_one()
    if existing == 0:
        from packages.shared.types import new_id

        salt = secrets.token_hex(16)
        conn.execute(
            sa.text(
                "INSERT INTO sys_user (id, username, password_hash, display_name, owner_id, status, created_at, updated_at) "
                "VALUES (:id, 'admin', :pwd, '管理员', 'local', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ).bindparams(pwd=_hash_password("admin123", salt)),
            {"id": new_id()},
        )


def downgrade() -> None:
    op.drop_index("ix_sys_session_expires")
    op.drop_index("ix_sys_session_user")
    op.drop_table("sys_session")
    op.drop_table("sys_user")

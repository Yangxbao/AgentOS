"""账号体系服务（M4）：注册 / 登录 / 会话校验 / 登出。

设计要点：
- 密码只存 PBKDF2-SHA256（20 万轮，随机盐），明文绝不落库、不进日志；
- 会话 token 为 128bit 随机 hex，本身即凭证，有效期 7 天，存 sys_session；
- owner_id 即用户的数据空间 id：admin 种子账号 owner_id='local'（绑定既有数据），
  新注册用户 owner_id 为独立随机值——业务表全部按 owner_id 过滤，天然隔离；
- 认证开关 AGENTOS_AUTH（默认 off）：off 时行为与历史版本完全一致（owner=local）。
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import SysSession, SysUser
from packages.shared.errors import DomainError
from packages.shared.types import new_id

PBKDF2_ROUNDS = 200_000
SESSION_TTL_DAYS = 7
AUTH_ENABLED_ENV = "AGENTOS_AUTH"


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    return secrets.compare_digest(digest.hex(), digest_hex)


def auth_enabled() -> bool:
    """认证开关：AGENTOS_AUTH=on 时强制登录（默认 off，兼容既有行为）。"""
    import os

    return os.environ.get(AUTH_ENABLED_ENV, "").strip().lower() == "on"


def _new_owner_id() -> str:
    return f"u_{new_id()}"


def register(session: Session, *, username: str, password: str, display_name: str = "") -> dict:
    username = (username or "").strip().lower()
    if not (3 <= len(username) <= 64) or not username.replace("_", "").replace("-", "").isalnum():
        raise DomainError("VALIDATION_ERROR", "用户名需 3-64 位字母/数字/_/-", 422)
    if len(password or "") < 8:
        raise DomainError("VALIDATION_ERROR", "密码至少 8 位", 422)
    exists = session.execute(
        select(SysUser).where(SysUser.username == username)
    ).scalars().first()
    if exists is not None:
        raise DomainError("AUTH_USERNAME_TAKEN", f"用户名已存在：{username}", 409)
    owner_id = _new_owner_id()
    user = SysUser(
        id=new_id(), username=username, password_hash=hash_password(password),
        display_name=display_name.strip() or username, owner_id=owner_id,
    )
    session.add(user)
    session.commit()
    return {"user_id": user.id, "username": user.username, "owner_id": owner_id}


def login(session: Session, *, username: str, password: str) -> dict:
    username = (username or "").strip().lower()
    user = session.execute(select(SysUser).where(SysUser.username == username)).scalars().first()
    # 用户名不存在与密码错误返回同一错误（不泄露账号是否存在）
    if user is None or user.status != "active" or not verify_password(password or "", user.password_hash):
        raise DomainError("AUTH_INVALID_CREDENTIALS", "用户名或密码错误", 401)
    token = secrets.token_hex(32)  # 128bit
    now = datetime.now(timezone.utc)
    session.add(SysSession(
        token=token, user_id=user.id, owner_id=user.owner_id,
        created_at=now, expires_at=now + timedelta(days=SESSION_TTL_DAYS),
    ))
    session.commit()
    return {"token": token, "user": {"id": user.id, "username": user.username,
                                     "display_name": user.display_name, "owner_id": user.owner_id}}


def resolve_token(session: Session, token: str) -> dict | None:
    """校验会话 token：有效返回 {"user_id", "owner_id", "username"}；过期/不存在返回 None。"""
    if not token:
        return None
    row = session.execute(
        select(SysSession, SysUser)
        .join(SysUser, SysUser.id == SysSession.user_id)
        .where(SysSession.token == token, SysUser.status == "active")
    ).first()
    if row is None:
        return None
    sess, user = row
    # SQLite 读回 naive datetime：统一按 UTC 补齐 tzinfo 再比较（与 executor 同款惯例）
    expires_at = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        session.delete(sess)
        session.commit()
        return None
    return {"user_id": user.id, "owner_id": sess.owner_id, "username": user.username,
            "display_name": user.display_name}


def logout(session: Session, token: str) -> bool:
    row = session.get(SysSession, token)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True

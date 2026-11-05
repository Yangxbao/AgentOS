"""数据库引擎与会话。默认 SQLite(WAL) 落盘 data/agentos.db。"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
# 绝对路径：避免从其他工作目录启动时悄悄创建一个空库（数据风险）
DEFAULT_DB_URL = f"sqlite:///{(REPO_ROOT / 'data' / 'agentos.db').as_posix()}"


def make_engine(db_url: str | None = None) -> Engine:
    url = db_url or os.environ.get("AGENTOS_DB_URL") or DEFAULT_DB_URL
    if url.startswith("sqlite"):
        # 确保目录存在（sqlite:///data/agentos.db -> data/）
        db_path = url.replace("sqlite:///", "")
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


_session_factory: sessionmaker[Session] | None = None


def init_db(db_url: str | None = None) -> Engine:
    global _session_factory
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine


def ensure_schema(db_url: str | None = None) -> None:
    """启动时确保库可用，但**不**用 create_all 偷偷补齐缺失的表。

    - 空库（无任何表）：create_all 引导建库，便于首次本地启动
    - 已有表的库：必须是迁移过的状态；B2 起新表一律通过 alembic 添加，防止绕过迁移造成结构漂移
    """
    from sqlalchemy import inspect

    engine = make_engine(db_url)
    tables = inspect(engine).get_table_names()
    if not tables:
        Base.metadata.create_all(engine)
    engine.dispose()


def get_session() -> Session:
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory()

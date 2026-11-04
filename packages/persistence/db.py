"""数据库引擎与会话。默认 SQLite(WAL) 落盘 data/agentos.db。"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DB_URL = "sqlite:///data/agentos.db"


def make_engine(db_url: str | None = None) -> Engine:
    url = db_url or os.environ.get("AGENTOS_DB_URL") or DEFAULT_DB_URL
    if url.startswith("sqlite"):
        # 确保目录存在（sqlite:///data/agentos.db -> data/）
        db_path = url.replace("sqlite:///", "")
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True)
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


def get_session() -> Session:
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory()

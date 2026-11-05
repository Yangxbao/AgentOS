"""B1 迁移测试：空库升级、M0 旧库升级、两条路径 schema 一致。

只使用临时数据库；真实 data/agentos.db 仅在存在时作为"旧库样本"被**复制**使用，绝不改写。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]
M0_TABLES = {"task", "task_run", "agent_run", "task_event", "usage_record"}


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _columns(db_url: str, table: str) -> list[str]:
    engine = create_engine(db_url, future=True)
    try:
        return [c["name"] for c in inspect(engine).get_columns(table)]
    finally:
        engine.dispose()


def _table_snapshot(db_url: str) -> dict[str, list[str]]:
    engine = create_engine(db_url, future=True)
    try:
        inspector = inspect(engine)
        return {t: [c["name"] for c in inspector.get_columns(t)] for t in sorted(M0_TABLES)}
    finally:
        engine.dispose()


def test_empty_database_upgrade_to_head(tmp_path, monkeypatch):
    """空库 upgrade head：建出 M0 五表 + alembic_version，且包含 B1 新列。"""
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    monkeypatch.setenv("AGENTOS_DB_URL", url)

    command.upgrade(_alembic_config(url), "head")

    engine = create_engine(url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert M0_TABLES.issubset(tables)
    assert "alembic_version" in tables
    assert "employee_id" in _columns(url, "agent_run")
    assert "employee_id" in _columns(url, "usage_record")  # B3 已加入
    # M3-A：工作区 / 授权 / 工具调用
    assert {"workspace", "employee_workspace_grant", "tool_call"}.issubset(tables)
    assert "tool_calls_count" in _columns(url, "task")
    assert "tool_calls_count" in _columns(url, "task_run")
    assert "tool_call_id" in _columns(url, "task_approval")


def test_m0_legacy_database_upgrade_preserves_data(tmp_path, monkeypatch):
    """M0 旧库：stamp 基线后升级，数据不丢、新列存在、schema 与空库升级一致。"""
    legacy_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("AGENTOS_DB_URL", legacy_url)
    cfg = _alembic_config(legacy_url)

    source = ROOT / "data" / "agentos.db"

    def _is_unmigrated_m0(path: Path) -> bool:
        """真实库只有在"没有 alembic_version 且 agent_run 无 employee_id"时才算 M0 样本。"""
        if not path.exists():
            return False
        with sqlite3.connect(path) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "alembic_version" in tables:
                return False
            cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_run)")}
        return "employee_id" not in cols

    if _is_unmigrated_m0(source):
        # SQLite 在线备份到临时库，避免直接改动真实数据
        dst = tmp_path / "legacy.db"
        with sqlite3.connect(source) as src, sqlite3.connect(dst) as target:
            src.backup(target)
        command.stamp(cfg, "m0_baseline")
    else:
        # 真实库已迁移或不存在：用基线 revision 造一个等价 M0 库（CI 同路径）
        command.upgrade(cfg, "m0_baseline")

    engine = create_engine(legacy_url, future=True)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO task (id, owner_id, title, objective, state, rework_count, max_rework, "
            "created_at, updated_at) VALUES ('t-legacy', 'local', '旧库任务', '', 'running', 0, 3, "
            "'2026-11-05 00:00:00', '2026-11-05 00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO task_run (id, owner_id, task_id, run_no, trigger, state, error, started_at, ended_at) "
            "VALUES ('r-legacy', 'local', 't-legacy', 1, 'manual', 'succeeded', NULL, "
            "'2026-11-05 00:00:00', '2026-11-05 00:01:00')"
        ))
        conn.execute(text(
            "INSERT INTO agent_run (id, owner_id, task_run_id, employee_key, role, adapter_type, model, "
            "input_payload, output_payload, state, error, external_ref, created_at) "
            "VALUES ('a-legacy', 'local', 'r-legacy', 'm0-researcher', '研究员', 'api', 'deepseek/deepseek-chat', "
            "'{}', '{}', 'succeeded', NULL, NULL, '2026-11-05 00:00:00')"
        ))
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(legacy_url, future=True)
    with engine.connect() as conn:
        task_count = conn.execute(text("SELECT COUNT(*) FROM task")).scalar_one()
        agent_model = conn.execute(text("SELECT model FROM agent_run WHERE id='a-legacy'")).scalar_one()
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()

    from alembic.script import ScriptDirectory

    expected_head = ScriptDirectory.from_config(cfg).get_current_head()

    assert task_count >= 1
    assert agent_model == "deepseek/deepseek-chat"  # 历史模型快照不被迁移改写
    assert revision == expected_head
    assert "employee_id" in _columns(legacy_url, "agent_run")
    assert "tool_calls_count" in _columns(legacy_url, "task")
    assert "tool_call_id" in _columns(legacy_url, "task_approval")

    # 与空库升级结果对比：五表列集合必须一致
    fresh_url = f"sqlite:///{tmp_path / 'fresh_compare.db'}"
    monkeypatch.setenv("AGENTOS_DB_URL", fresh_url)
    command.upgrade(_alembic_config(fresh_url), "head")
    assert _table_snapshot(legacy_url) == _table_snapshot(fresh_url)

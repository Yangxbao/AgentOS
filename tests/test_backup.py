"""B1 补充验收：备份脚本真实执行 + 独立副本恢复读取（不触碰真实库）。"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from packages.persistence import Task, get_session, init_db

ROOT = Path(__file__).resolve().parents[1]


def test_backup_script_creates_readable_copy(tmp_path):
    db_path = tmp_path / "source.db"
    url = f"sqlite:///{db_path}"
    init_db(url)
    with get_session() as session:
        session.add(Task(id="t-backup", title="备份验证任务", state="draft"))
        session.commit()

    out_dir = tmp_path / "backups"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backup_db.py"), "--db", str(db_path), "--out", str(out_dir)],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "备份完成" in proc.stdout

    backup_dirs = [p for p in out_dir.iterdir() if p.is_dir()]
    assert len(backup_dirs) == 1
    backup = backup_dirs[0]
    copied_db = backup / "source.db"
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))

    assert copied_db.exists()
    assert manifest["db_file"] == "source.db"
    assert manifest["db_size_bytes"] == copied_db.stat().st_size

    # 恢复读取：从副本独立打开，数据完整
    with sqlite3.connect(copied_db) as conn:
        title = conn.execute("SELECT title FROM task WHERE id='t-backup'").fetchone()[0]
    assert title == "备份验证任务"

    # 源库未被破坏
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM task").fetchone()[0] == 1

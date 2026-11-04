"""数据库备份脚本：SQLite 在线备份 + 提示词目录（如存在）+ manifest。

用法：
    python scripts/backup_db.py
    python scripts/backup_db.py --db data/agentos.db --out data/backups
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def backup(db_path: Path, out_dir: Path, include_prompts: bool = True) -> Path:
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = out_dir / f"agentos_{stamp}"
    target.mkdir(parents=True, exist_ok=True)

    db_copy = target / db_path.name
    # 使用 SQLite 在线备份 API，避免直接复制 WAL 模式下的不一致文件
    with sqlite3.connect(db_path) as src, sqlite3.connect(db_copy) as dst:
        src.backup(dst)

    prompts_src = ROOT / "data" / "prompts"
    prompts_included = False
    if include_prompts and prompts_src.exists():
        shutil.copytree(prompts_src, target / "prompts")
        prompts_included = True

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "db_file": db_path.name,
        "db_size_bytes": db_copy.stat().st_size,
        "prompts_included": prompts_included,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"备份完成：{target}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentOS 数据库备份")
    parser.add_argument("--db", default=str(ROOT / "data" / "agentos.db"))
    parser.add_argument("--out", default=str(ROOT / "data" / "backups"))
    parser.add_argument("--no-prompts", action="store_true")
    args = parser.parse_args(argv)
    backup(Path(args.db), Path(args.out), include_prompts=not args.no_prompts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

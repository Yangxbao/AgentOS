"""提示词对账：报告孤儿文件 / 缺失文件 / 哈希不符。

用法：
    python scripts/reconcile_prompts.py            # 只报告
    python scripts/reconcile_prompts.py --fix --yes  # 删除孤儿文件（需显式确认）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.persistence import init_db  # noqa: E402
from packages.prompts.service import PROMPTS_ROOT, reconcile  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentOS 提示词对账")
    parser.add_argument("--fix", action="store_true", help="删除孤儿文件")
    parser.add_argument("--yes", action="store_true", help="确认执行删除")
    args = parser.parse_args(argv)

    init_db()
    report = reconcile()
    for key, items in report.items():
        print(f"{key}: {len(items)}")
        for item in items:
            print(f"  - {item}")

    if args.fix:
        if not args.yes:
            raise SystemExit("--fix 需要同时传 --yes 确认")
        for rel in report["orphan_files"]:
            path = ROOT / rel
            if path.exists() and PROMPTS_ROOT in path.parents:
                path.unlink()
                print(f"removed {rel}")
    return 0 if not any(report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

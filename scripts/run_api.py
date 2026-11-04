"""以安全默认值启动 API：只监听 127.0.0.1，拒绝 0.0.0.0（除非显式授权）。

用法：
    python scripts/run_api.py                 # 127.0.0.1:8000
    python scripts/run_api.py --port 8010
    AGENTOS_ALLOW_EXTERNAL=1 python scripts/run_api.py --host 0.0.0.0   # 明确风险后允许
"""
from __future__ import annotations

import argparse
import os
import sys

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def resolve_bind_host(host: str, allow_external: bool = False) -> str:
    """校验监听地址；非回环地址必须显式授权，否则拒绝启动。"""
    normalized = host.strip()
    if normalized in LOOPBACK_HOSTS:
        return "127.0.0.1"
    if allow_external:
        return normalized
    raise SystemExit(
        f"拒绝监听 {normalized}：本地管理接口默认只允许 127.0.0.1。\n"
        "如确需对外监听，请设置 AGENTOS_ALLOW_EXTERNAL=1 并自行承担安全风险。"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentOS API 启动器（安全默认监听 127.0.0.1）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发热重载")
    args = parser.parse_args(argv)

    allow_external = os.environ.get("AGENTOS_ALLOW_EXTERNAL") == "1"
    host = resolve_bind_host(args.host, allow_external)
    if host != "127.0.0.1":
        print(f"[安全警告] 正在监听 {host}:{args.port}，本地管理接口可能被同网段访问！", file=sys.stderr)

    import uvicorn

    uvicorn.run("apps.api.main:app", host=host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

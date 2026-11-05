"""本地预览前端构建产物（SPA fallback），默认只监听 127.0.0.1。

用法：
    python scripts/serve_web.py --port 5173
"""
from __future__ import annotations

import argparse
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SPAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):  # noqa: N802 - http.server 约定
        target = self.translate_path(self.path)
        if (not os.path.exists(target) or os.path.isdir(target)) and not self.path.startswith("/assets/"):
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, fmt, *args):  # 静默，避免污染验收输出
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentOS 前端静态预览（仅本机）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--dir", default=str(ROOT / "apps" / "web" / "dist"))
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("拒绝监听非本机地址；如需外部访问请显式修改脚本并自行承担风险", file=sys.stderr)
        return 2
    directory = Path(args.dir)
    if not (directory / "index.html").exists():
        print(f"未找到构建产物：{directory / 'index.html'}，请先 npm run build", file=sys.stderr)
        return 2

    handler = lambda *a, **kw: SPAHandler(*a, directory=str(directory), **kw)  # noqa: E731
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"前端预览：http://{args.host}:{args.port}（目录 {directory}）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

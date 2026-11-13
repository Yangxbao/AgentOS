"""一键生产部署（M4）：构建产物由后端单进程托管（前端静态 + API 同源）。

用法：
    cd apps/web && npm run build     # 先产出 dist
    python scripts/run_prod.py       # 默认 127.0.0.1:8000，浏览器打开 http://127.0.0.1:8000

说明：
- 前端挂载在 "/"（html=True），API 路由（/api/*）优先于静态匹配；
- 认证开关、模型模式等环境变量与开发模式一致（见 HANDOFF.md §3）；
- 仍只监听 127.0.0.1；对外部署请自行置于反向代理与认证之后。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "apps" / "web" / "dist"


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS 生产模式启动（前端静态 + API 同源）")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not (DIST / "index.html").is_file():
        print("[run_prod] 未找到 apps/web/dist/index.html —— 请先执行: cd apps/web && npm run build", file=sys.stderr)
        sys.exit(1)

    # uvicorn 延迟 import：与 scripts/run_api.py 同款启动路径
    import uvicorn
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from apps.api.main import create_app

    app = create_app()

    # 静态资源（带 hash 的 js/css/图片）直接返回
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 回退：dist 里的真实文件按文件返回，其余路径一律回 index.html（前端路由接管）。"""
        candidate = (DIST / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and candidate.is_relative_to(DIST.resolve())
        ):
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")

    print(f"[run_prod] AgentOS 生产模式: http://127.0.0.1:{args.port}（前端 + API 同源）")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()

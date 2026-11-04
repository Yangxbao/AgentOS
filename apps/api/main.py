"""AgentOS API 入口（B1：分层 + 生命周期 + 统一错误 + 本地防护）。

启动（推荐）：python scripts/run_api.py --port 8000
开发热重载：uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
# 兜底：包未安装（pip install -e .）时仍可从仓库根目录运行；已安装后此分支不生效
try:  # pragma: no cover - 取决于运行环境
    import packages  # noqa: F401
except ModuleNotFoundError:  # deprecated fallback, 保留至 M1 结束
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from apps.api.errors import RequestIdMiddleware, register_exception_handlers  # noqa: E402
from apps.api.routers import (  # noqa: E402
    companies,
    config_io,
    departments,
    employees,
    legacy,
    model_connections,
    positions,
    prompts,
)
from apps.api.security.local_guard import LocalGuardMiddleware, config_from_env  # noqa: E402
from packages.persistence import init_db  # noqa: E402
from packages.persistence.db import ensure_schema  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 空库才引导建表；已有库必须已迁移（禁止 create_all 掩盖缺失迁移）
    ensure_schema()
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AgentOS API", version="0.1.0-m1b1", lifespan=lifespan)

    guard_config = config_from_env()

    # 中间件顺序：后添加的在最外层。RequestId 最外 → CORS → LocalGuard → 路由
    app.add_middleware(LocalGuardMiddleware, config=guard_config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=guard_config.trusted_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-AgentOS-Client", "X-AgentOS-Token", "If-Match", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)
    app.include_router(legacy.router, prefix="/api")
    for router in (
        companies.router,
        departments.router,
        positions.router,
        employees.router,
        model_connections.router,
        prompts.router,
        config_io.router,
    ):
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()

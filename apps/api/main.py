"""AgentOS API — M0 最小骨架。

提供：/api/health、/api/tasks（真实读库）、/api/employees/{key}/health（连接测试）。
启动：uvicorn apps.api.main:app --reload --port 8000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

# 允许以仓库根目录运行 uvicorn 时 import packages
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from packages.agent_core import LiteLLMAdapter  # noqa: E402
from packages.persistence import Task, get_session, init_db  # noqa: E402

app = FastAPI(title="AgentOS API", version="0.1.0-m0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": os.environ.get("AGENTOS_MODE", "local"), "version": "0.1.0-m0"}


@app.get("/api/tasks")
def list_tasks() -> list[dict]:
    """真实读库返回任务列表（M0 验证持久化的可视化入口）。"""
    with get_session() as session:
        tasks = session.execute(select(Task).order_by(Task.created_at.desc()).limit(50)).scalars().all()
        return [
            {
                "id": t.id,
                "title": t.title,
                "state": t.state,
                "rework_count": t.rework_count,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ]


@app.get("/api/employees/{model:path}/health")
async def employee_health(model: str) -> dict:
    """连接测试：对指定 litellm 模型做最小真实调用（如 deepseek/deepseek-chat）。"""
    adapter = LiteLLMAdapter(model=model, timeout=15.0)
    status = await adapter.health_check()
    if not status.ok:
        raise HTTPException(status_code=502, detail=status.detail)
    return {"ok": True, "model": model, "detail": status.detail}

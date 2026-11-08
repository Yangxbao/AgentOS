"""M0 兼容接口（行为保持不变，不计入 M1 的 45 个 /api/v1 端点）。

提供：/api/health、/api/tasks、/api/employees/{model}/health
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.deps import get_db
from packages.agent_core import LiteLLMAdapter
from packages.persistence import Task

router = APIRouter(tags=["legacy"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": os.environ.get("AGENTOS_MODE", "local"), "version": "0.3.1"}


@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)) -> list[dict]:
    """真实读库返回任务列表（保持 M0 返回结构，避免破坏既有前端）。"""
    tasks = db.execute(select(Task).order_by(Task.created_at.desc()).limit(50)).scalars().all()
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


@router.get("/employees/{model:path}/health")
async def employee_health(model: str) -> dict:
    """连接测试：对指定 litellm 模型做最小真实调用（如 deepseek/deepseek-chat）。"""
    adapter = LiteLLMAdapter(model=model, timeout=15.0)
    status = await adapter.health_check()
    if not status.ok:
        raise HTTPException(status_code=502, detail=status.detail)
    return {"ok": True, "model": model, "detail": status.detail}

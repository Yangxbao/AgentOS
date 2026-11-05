"""后台执行 worker（M2-B）：单进程、数据库队列、启动恢复。

单进程假设：本地部署只运行一个 API 进程；多进程会重复认领，故不在 M2 支持。
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from packages.persistence import get_session
from packages.persistence.models import Task, TaskEvent, TaskRun

from .executor import execute_run

logger = logging.getLogger("agentos.runner")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRunner:
    def __init__(self, poll_interval: float = 0.4):
        self.worker_id = f"{socket.gethostname()[:12]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.poll_interval = poll_interval
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task | None = None

    # ---------- 生命周期 ----------
    async def start(self) -> None:
        if os.environ.get("AGENTOS_RUNNER_DISABLED") == "1":
            logger.warning("TaskRunner 已禁用（AGENTOS_RUNNER_DISABLED=1）")
            return
        if self._loop_task is None or self._loop_task.done():
            self._stop.clear()
            self._loop_task = asyncio.create_task(self._loop(), name="agentos-runner")
            logger.info("TaskRunner 启动 worker_id=%s", self.worker_id)

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._loop_task = None

    def kick(self) -> None:
        self._wake.set()

    # ---------- 主循环 ----------
    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self.run_pending_once()
            except Exception:  # noqa: BLE001 - worker 不能因单次异常退出
                logger.exception("runner 轮询异常")
                processed = False
            if processed:
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    def claim(self) -> str | None:
        session = get_session()
        try:
            row = session.execute(
                select(TaskRun).where(TaskRun.state == "queued").order_by(TaskRun.started_at)
            ).scalars().first()
            if row is None:
                return None
            result = session.execute(
                update(TaskRun)
                .where(TaskRun.id == row.id, TaskRun.state == "queued")
                .values(state="running", worker_id=self.worker_id, heartbeat_at=_now())
            )
            if result.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            return row.id
        finally:
            session.close()

    async def run_pending_once(self) -> bool:
        run_id = self.claim()
        if run_id is None:
            return False
        await execute_run(run_id)
        return True

    # ---------- 启动恢复 ----------
    def recover(self) -> dict:
        """把上次进程遗留的 running 标记为 interrupted，任务转 paused 等人工恢复。"""
        session = get_session()
        recovered: list[str] = []
        try:
            rows = session.execute(select(TaskRun).where(TaskRun.state == "running")).scalars().all()
            for run in rows:
                run.state = "interrupted"
                run.ended_at = _now()
                run.error = "进程重启，执行中断（可恢复）"
                task = session.get(Task, run.task_id)
                if task is not None and task.state == "running":
                    task.state = "paused"
                    task.version = (task.version or 1) + 1
                    session.add(TaskEvent(
                        task_id=task.id, task_run_id=run.id, type="run.interrupted",
                        payload={"run_id": run.id, "message": "进程重启，执行中断"},
                    ))
                recovered.append(run.id)
            if recovered:
                session.commit()
            return {"interrupted_runs": len(recovered), "run_ids": recovered}
        finally:
            session.close()


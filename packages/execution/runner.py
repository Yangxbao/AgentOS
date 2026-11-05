"""后台执行 worker（M2 单进程 → M3-D 多 Worker 租约模型）。

关键机制（对齐 M3_MASTER_PLAN §9）：
- 原子认领：UPDATE ... WHERE state='queued'，rowcount=1 才算认领成功；认领即写租约
  （lease_owner / lease_expires_at = now+TTL / attempt+1 / priority 快照）；
- 心跳：每 15s 为自己持有的 running run 续租（lease_expires_at 前移）；
- 巡检：每 30s 扫描租约过期的 running：
  attempt < 3 → run=interrupted、任务=paused（事件 run.lease_expired，可恢复）；
  attempt ≥ 3 → run/task=failed（LEASE_EXHAUSTED）；
- 启动恢复：只处理租约过期（或 NULL——M2 遗留行）的 running，**不**误伤其他存活 worker 的 run；
- 并发：AGENTOS_WORKER_CONCURRENCY（默认 2）控制单进程并发；
  公司级 policy.max_concurrent_tasks（默认 2）超出则排队；
- 优先级：urgent > high > normal > low（同优先级按入队时间 FIFO）；
- 边界：SQLite WAL 单写者，2–3 个 worker 可接受；不引入 Redis/消息队列。
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select, update

from packages.persistence import get_session
from packages.persistence.models import Company, Task, TaskEvent, TaskRun

from .executor import execute_run

logger = logging.getLogger("agentos.runner")

LEASE_TTL_S = 60.0          # 租约时长
HEARTBEAT_INTERVAL_S = 15.0  # 心跳续租间隔
SWEEP_INTERVAL_S = 30.0      # 租约巡检间隔
MAX_ATTEMPT = 3              # attempt ≥ 3 → LEASE_EXHAUSTED
DEFAULT_CONCURRENCY = 2
DEFAULT_COMPANY_CONCURRENCY = 2

_PRIORITY_RANK = {"urgent": 3, "high": 2, "normal": 1, "low": 0}
_PRIORITY_CASE = case(
    (Task.priority == "urgent", 3),
    (Task.priority == "high", 2),
    (Task.priority == "normal", 1),
    else_=0,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRunner:
    def __init__(self, poll_interval: float = 0.4, concurrency: int | None = None):
        self.worker_id = f"{socket.gethostname()[:12]}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.poll_interval = poll_interval
        try:
            self.concurrency = int(
                concurrency
                or os.environ.get("AGENTOS_WORKER_CONCURRENCY", DEFAULT_CONCURRENCY)
            )
        except (TypeError, ValueError):
            self.concurrency = DEFAULT_CONCURRENCY
        self.concurrency = max(1, self.concurrency)
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
            self._loop_task = asyncio.create_task(self._loop(), name=f"agentos-runner-{self.worker_id}")
            logger.info(
                "TaskRunner 启动 worker_id=%s concurrency=%s", self.worker_id, self.concurrency,
            )

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
        active: set[asyncio.Task] = set()
        last_heartbeat = 0.0
        last_sweep = 0.0
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                active = {t for t in active if not t.done()}

                if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                    self.heartbeat()
                    last_heartbeat = now
                if now - last_sweep >= SWEEP_INTERVAL_S:
                    self.sweep_expired_leases()
                    last_sweep = now

                # 认领直到并发占满
                while len(active) < self.concurrency and not self._stop.is_set():
                    run_id = self.claim()
                    if run_id is None:
                        break
                    active.add(asyncio.create_task(self._execute(run_id)))

                if active:
                    await asyncio.sleep(self.poll_interval)
                else:
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
                    except asyncio.TimeoutError:
                        pass
                    self._wake.clear()
            except Exception:  # noqa: BLE001 - worker 不能因单次异常退出
                logger.exception("runner 轮询异常")
                await asyncio.sleep(self.poll_interval)

    async def _execute(self, run_id: str) -> None:
        try:
            await execute_run(run_id)
        except Exception:  # noqa: BLE001 - execute_run 内部已兜底，这里防意外
            logger.exception("run %s 执行异常逸出", run_id)

    # ---------- 原子认领（M3-D） ----------
    def _company_concurrency_cap(self, session, company_id: str | None) -> int:
        if not company_id:
            return DEFAULT_COMPANY_CONCURRENCY
        company = session.get(Company, company_id)
        raw = (company.policy or {}).get("max_concurrent_tasks") if company else None
        try:
            return max(1, int(raw)) if raw is not None else DEFAULT_COMPANY_CONCURRENCY
        except (TypeError, ValueError):
            return DEFAULT_COMPANY_CONCURRENCY

    def claim(self) -> str | None:
        """原子认领一条 queued run：带优先级排序、公司并发上限、租约与 attempt 递增。"""
        session = get_session()
        try:
            candidates = session.execute(
                select(TaskRun.id, Task.company_id, _PRIORITY_CASE)
                .join(Task, Task.id == TaskRun.task_id)
                .where(TaskRun.state == "queued")
                .order_by(_PRIORITY_CASE.desc(), TaskRun.started_at.asc())
                .limit(10)
            ).all()
            for run_id, company_id, rank in candidates:
                cap = self._company_concurrency_cap(session, company_id)
                if company_id:
                    running = session.execute(
                        select(func.count())
                        .select_from(TaskRun)
                        .join(Task, Task.id == TaskRun.task_id)
                        .where(TaskRun.state == "running", Task.company_id == company_id)
                    ).scalar_one()
                    if int(running) >= cap:
                        continue
                result = session.execute(
                    update(TaskRun)
                    .where(TaskRun.id == run_id, TaskRun.state == "queued")
                    .values(
                        state="running",
                        worker_id=self.worker_id,
                        lease_owner=self.worker_id,
                        lease_expires_at=_now() + timedelta(seconds=LEASE_TTL_S),
                        heartbeat_at=_now(),
                        attempt=TaskRun.attempt + 1,
                        priority=int(rank),
                    )
                )
                if result.rowcount != 1:
                    session.rollback()
                    continue
                session.commit()
                return run_id
            return None
        finally:
            session.close()

    async def run_pending_once(self) -> bool:
        """认领并等待执行一条（兼容接口/测试用）。"""
        run_id = self.claim()
        if run_id is None:
            return False
        await execute_run(run_id)
        return True

    # ---------- 心跳与巡检（M3-D） ----------
    def heartbeat(self) -> int:
        """为自己持有的 running run 续租；返回续租数量。"""
        session = get_session()
        try:
            result = session.execute(
                update(TaskRun)
                .where(TaskRun.lease_owner == self.worker_id, TaskRun.state == "running")
                .values(
                    lease_expires_at=_now() + timedelta(seconds=LEASE_TTL_S),
                    heartbeat_at=_now(),
                )
            )
            session.commit()
            return int(result.rowcount or 0)
        finally:
            session.close()

    def sweep_expired_leases(self) -> dict:
        """巡检租约过期的 running：attempt<3 → interrupted/paused；attempt≥3 → failed。

        NULL 租约的 running（M2 遗留行 / 早期崩溃）同样视为失联。
        """
        session = get_session()
        interrupted: list[str] = []
        exhausted: list[str] = []
        try:
            rows = session.execute(
                select(TaskRun).where(
                    TaskRun.state == "running",
                    or_(
                        TaskRun.lease_expires_at.is_(None),
                        TaskRun.lease_expires_at < _now(),
                    ),
                )
            ).scalars().all()
            for run in rows:
                task = session.get(Task, run.task_id)
                now = _now()
                if (run.attempt or 0) >= MAX_ATTEMPT:
                    run.state = "failed"
                    run.ended_at = now
                    run.error = f"LEASE_EXHAUSTED: 租约过期且已达最大尝试次数 {MAX_ATTEMPT}"
                    exhausted.append(run.id)
                    if task is not None and task.state in ("running", "queued"):
                        task.state = "failed"
                        task.ended_at = now
                        task.result = {**(task.result or {}), "error": {
                            "code": "LEASE_EXHAUSTED",
                            "message": f"执行租约过期且已达最大尝试次数 {MAX_ATTEMPT}",
                        }}
                        task.version = (task.version or 1) + 1
                    session.add(TaskEvent(
                        task_id=run.task_id, task_run_id=run.id, type="run.lease_exhausted",
                        payload={"run_id": run.id, "attempt": run.attempt},
                    ))
                else:
                    run.state = "interrupted"
                    run.ended_at = now
                    # NULL 租约 = M2 遗留/进程重启场景；有租约但过期 = worker 失联
                    run.error = (
                        "进程重启，执行中断（可恢复）"
                        if run.lease_expires_at is None
                        else "执行租约过期（worker 失联），可恢复"
                    )
                    interrupted.append(run.id)
                    if task is not None and task.state in ("running", "queued"):
                        task.state = "paused"
                        task.version = (task.version or 1) + 1
                    session.add(TaskEvent(
                        task_id=run.task_id, task_run_id=run.id, type="run.lease_expired",
                        payload={"run_id": run.id, "attempt": run.attempt},
                    ))
            if interrupted or exhausted:
                session.commit()
            return {
                "interrupted_runs": len(interrupted), "run_ids": interrupted,
                "exhausted_runs": len(exhausted), "exhausted_run_ids": exhausted,
            }
        finally:
            session.close()

    # ---------- 启动恢复 ----------
    def recover(self) -> dict:
        """启动恢复：只处理租约过期（含 NULL 的 M2 遗留行）的 running，
        不误伤其他存活 worker 正常续租中的 run。"""
        return self.sweep_expired_leases()

    # ---------- 观测（M3-18/19） ----------
    def workers_snapshot(self) -> dict:
        """在线 worker 视图：按 lease_owner 聚合 running run 的心跳与租约。"""
        session = get_session()
        try:
            rows = session.execute(
                select(
                    TaskRun.lease_owner,
                    func.count(),
                    func.max(TaskRun.heartbeat_at),
                    func.min(TaskRun.lease_expires_at),
                )
                .where(TaskRun.state == "running", TaskRun.lease_owner.is_not(None))
                .group_by(TaskRun.lease_owner)
            ).all()
            queued = session.execute(
                select(func.count()).select_from(TaskRun).where(TaskRun.state == "queued")
            ).scalar_one()
            return {
                "workers": [
                    {
                        "worker_id": row[0],
                        "running_runs": int(row[1]),
                        "last_heartbeat_at": row[2].isoformat() if row[2] else None,
                        "lease_expires_at": row[3].isoformat() if row[3] else None,
                        "lease_alive": bool(row[3] and row[3] >= _now()),
                    }
                    for row in rows
                ],
                "queued_runs": int(queued or 0),
                "this_worker_id": self.worker_id,
            }
        finally:
            session.close()

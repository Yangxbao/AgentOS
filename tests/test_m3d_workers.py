"""M3-D 多 Worker：原子领取、并发防重、租约过期恢复、LEASE_EXHAUSTED、公司并发上限、优先级。

验收对齐总任务书 M3-D：
- 2 个 worker 并发跑 10 个任务，无重复执行（agent_run 计数正确）；
- 杀掉 worker 后租约过期，任务转 interrupted/paused，可恢复；attempt=3 后 LEASE_EXHAUSTED；
- 心跳续租成功不误判；同公司并发上限生效；优先级高者先执行；
- 与暂停/取消/预算熔断兼容（预算/审批路径在 M3-E/B 已测，这里回归 run 生命周期）。
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import create_app
from packages.execution.executor import execute_run
from packages.execution.runner import TaskRunner, _now
from packages.persistence import get_session
from packages.persistence.models import Task, TaskRun
from tests.helpers import create_task


@pytest.fixture
def no_runner_client(db_url, monkeypatch):
    """禁用 app 内置 runner：测试自己驱动 worker，避免与被测 worker 争抢。"""
    monkeypatch.setenv("AGENTOS_RUNNER_DISABLED", "1")
    monkeypatch.setenv("AGENTOS_MODEL_MODE", "mock")
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        test_client.headers.update({"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"})
        yield test_client


@pytest.fixture
def team(no_runner_client):
    """最小公司 + 两名员工 + 模型连接。"""
    c = no_runner_client
    company = c.post("/api/v1/companies", json={"name": "Worker 公司"}).json()
    conn = c.post(
        f"/api/v1/companies/{company['id']}/model-connections",
        json={"name": "连接", "provider": "deepseek", "model": "deepseek/deepseek-chat",
              "api_key_ref": "env:TEST_MODEL_KEY"},
    ).json()
    pos = c.post(
        f"/api/v1/companies/{company['id']}/positions", json={"name": "开发"}
    ).json()

    def _employee(name: str) -> dict:
        resp = c.post(
            f"/api/v1/companies/{company['id']}/employees",
            json={"name": name, "title": "开发", "primary_model_id": conn["id"],
                  "positions": [{"position_id": pos["id"], "is_primary": True}]},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    return {"company": company, "employees": [_employee("甲"), _employee("乙")]}


def _queue_tasks(client, team: dict, count: int, **overrides) -> list[str]:
    ids = []
    for i in range(count):
        task = create_task(
            client, team["company"]["id"], team["employees"][i % 2]["id"],
            title=f"任务{i}", objective="多 worker 验证", **overrides,
        )
        resp = client.post(f"/api/v1/tasks/{task['id']}/run")
        assert resp.status_code == 202, resp.text
        ids.append(task["id"])
    return ids


def _wait_terminal(client, task_ids: list[str], timeout: float = 30.0) -> None:
    import time

    deadline = time.time() + timeout
    pending = set(task_ids)
    while pending and time.time() < deadline:
        for tid in list(pending):
            state = client.get(f"/api/v1/tasks/{tid}").json()["state"]
            if state in {"succeeded", "failed", "cancelled"}:
                pending.discard(tid)
        if pending:
            time.sleep(0.05)
    assert not pending, f"任务未到达终态：{pending}"


def test_two_workers_no_duplicate_execution(no_runner_client, team):
    """2 个 worker 并发认领 10 个任务：每个任务恰好 1 条 agent_run，无重复执行。"""
    task_ids = _queue_tasks(no_runner_client, team, 10)
    runner_a, runner_b = TaskRunner(), TaskRunner()
    assert runner_a.worker_id != runner_b.worker_id

    async def _drive(runner: TaskRunner) -> int:
        executed = 0
        while True:
            run_id = runner.claim()
            if run_id is None:
                return executed
            await execute_run(run_id)
            executed += 1

    async def _main():
        return await asyncio.gather(_drive(runner_a), _drive(runner_b))

    executed = asyncio.run(_main())
    assert sum(executed) == 10

    _wait_terminal(no_runner_client, task_ids)
    for tid in task_ids:
        detail = no_runner_client.get(f"/api/v1/tasks/{tid}").json()
        assert detail["state"] == "succeeded"
        agent_runs = [a for run in detail["runs"] for a in run["agent_runs"]]
        assert len(agent_runs) == 1, f"任务 {tid} 被重复执行"
    with get_session() as session:
        workers = {w for (w,) in session.execute(
            select(TaskRun.lease_owner).where(TaskRun.state == "succeeded")
        ).all() if w}
        assert workers == {runner_a.worker_id, runner_b.worker_id}


def test_heartbeat_renews_lease(no_runner_client, team):
    """心跳续租：续租后 lease_expires_at 前移，巡检不误判。"""
    _queue_tasks(no_runner_client, team, 1)
    runner = TaskRunner()
    run_id = runner.claim()
    assert run_id is not None
    with get_session() as session:
        run = session.get(TaskRun, run_id)
        before = run.lease_expires_at
    import time

    time.sleep(0.02)
    assert runner.heartbeat() == 1
    with get_session() as session:
        run = session.get(TaskRun, run_id)
        assert run.lease_expires_at > before

    # 租约未过期：巡检无事发生
    result = runner.sweep_expired_leases()
    assert result["interrupted_runs"] == 0


def test_lease_expiry_interrupts_and_resumes(no_runner_client, team):
    """worker 失联：租约过期 → run=interrupted、任务=paused（事件 run.lease_expired）→ 恢复成功。"""
    task_ids = _queue_tasks(no_runner_client, team, 1)
    runner = TaskRunner()
    run_id = runner.claim()
    assert run_id is not None
    task_id = task_ids[0]
    # 模拟 worker 死亡：把租约改到过去
    with get_session() as session:
        run = session.get(TaskRun, run_id)
        run.lease_expires_at = _now() - timedelta(seconds=5)
        session.commit()

    result = runner.sweep_expired_leases()
    assert result["interrupted_runs"] == 1
    detail = no_runner_client.get(f"/api/v1/tasks/{task_id}").json()
    assert detail["state"] == "paused"

    events = no_runner_client.get(f"/api/v1/tasks/{task_id}/timeline").json()["items"]
    assert any(item["type"] == "run.lease_expired" for item in events)

    # 恢复：新 run 从检查点续跑并完成（app runner 已禁用，由测试 worker 认领执行）
    resp = no_runner_client.post(f"/api/v1/tasks/{task_id}/resume")
    assert resp.status_code == 202, resp.text
    resumed = TaskRunner().claim()
    assert resumed is not None
    asyncio.run(execute_run(resumed))
    detail = no_runner_client.get(f"/api/v1/tasks/{task_id}").json()
    assert detail["state"] == "succeeded"


def test_lease_exhausted_after_max_attempts(no_runner_client, team):
    """attempt ≥ 3：租约过期 → run/task=failed（LEASE_EXHAUSTED），不再自动恢复。"""
    task_ids = _queue_tasks(no_runner_client, team, 1)
    runner = TaskRunner()
    run_id = runner.claim()
    task_id = task_ids[0]
    with get_session() as session:
        run = session.get(TaskRun, run_id)
        run.attempt = 3
        run.lease_expires_at = _now() - timedelta(seconds=5)
        session.commit()

    result = runner.sweep_expired_leases()
    assert result["exhausted_runs"] == 1
    detail = no_runner_client.get(f"/api/v1/tasks/{task_id}").json()
    assert detail["state"] == "failed"
    assert detail["result"]["error"]["code"] == "LEASE_EXHAUSTED"


def test_company_concurrency_cap(no_runner_client, team):
    """公司并发上限：max_concurrent_tasks=1 时第二条认领被拒（排队）。"""
    company_id = team["company"]["id"]
    resp = no_runner_client.patch(
        f"/api/v1/companies/{company_id}", json={"policy": {"max_concurrent_tasks": 1}}
    )
    assert resp.status_code == 200, resp.text
    _queue_tasks(no_runner_client, team, 2)

    runner = TaskRunner()
    first = runner.claim()
    assert first is not None
    second = runner.claim()
    assert second is None, "公司并发上限=1 时不应认领第二条"


def test_priority_ordering(no_runner_client, team):
    """优先级：urgent 先于 low 被认领（同优先级 FIFO）。"""
    ids = _queue_tasks(no_runner_client, team, 1, priority="low")
    _queue_tasks(no_runner_client, team, 1, priority="urgent")

    runner = TaskRunner()
    first = runner.claim()
    assert first is not None
    with get_session() as session:
        run = session.get(TaskRun, first)
        # 认领的是 urgent 任务的 run，且优先级快照=3
        task = session.get(Task, run.task_id)
        assert task.priority == "urgent"
        assert run.priority == 3
        assert run.task_id != ids[0]


def test_recover_ignores_live_leases(no_runner_client, team):
    """启动恢复：存活 worker 的租约（未过期）不会被误中断；NULL 遗留行仍被处理。"""
    task_ids = _queue_tasks(no_runner_client, team, 2)
    runner = TaskRunner()
    live_run = runner.claim()  # 租约有效
    with get_session() as session:
        other = session.execute(
            select(TaskRun).where(
                TaskRun.task_id == task_ids[1], TaskRun.state == "queued"
            )
        ).scalars().first()
        other.state = "running"
        other.lease_owner = None          # M2 遗留行：无租约
        other.lease_expires_at = None
        session.commit()

    result = runner.recover()
    assert result["interrupted_runs"] == 1  # 只处理 NULL 租约那一条
    with get_session() as session:
        assert session.get(TaskRun, live_run).state == "running"  # 存活租约不误伤
        other = session.get(TaskRun, other.id)
        assert other.state == "interrupted"


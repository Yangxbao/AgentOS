"""M2 测试辅助：任务创建与后台执行轮询。"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

TERMINAL = {"succeeded", "failed", "cancelled"}


def create_task(client: TestClient, company_id: str, assignee_id: str, **overrides) -> dict:
    payload = {
        "title": overrides.pop("title", "测试任务"),
        "objective": overrides.pop("objective", "验证任务闭环"),
        "assignee_employee_id": assignee_id,
        **overrides,
    }
    resp = client.post(f"/api/v1/companies/{company_id}/tasks", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def task_detail(client: TestClient, task_id: str) -> dict:
    resp = client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def wait_task(client: TestClient, task_id: str, states, timeout: float = 25.0) -> dict:
    states = set(states)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = task_detail(client, task_id)
        if last["state"] in states:
            return last
        time.sleep(0.05)
    raise AssertionError(
        f"任务 {task_id} 在 {timeout}s 内未进入 {states}，当前 {last and last['state']}，"
        f"result={last and last.get('result')}"
    )


def wait_agent_runs(client: TestClient, task_id: str, count: int, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = task_detail(client, task_id)
        if sum(len(run["agent_runs"]) for run in last["runs"]) >= count:
            return last
        time.sleep(0.05)
    raise AssertionError(f"等待 {count} 个 agent run 超时，当前 {task_detail(client, task_id)}")


def all_agent_runs(detail: dict) -> list[dict]:
    return [agent for run in detail["runs"] for agent in run["agent_runs"]]


def run_task(client: TestClient, task_id: str) -> dict:
    resp = client.post(f"/api/v1/tasks/{task_id}/run")
    assert resp.status_code == 202, resp.text
    return resp.json()

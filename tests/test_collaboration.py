"""M2-C 验收：多 Agent 计划、依赖、并行、交接、自动拆分与防递归。"""
from __future__ import annotations

from datetime import datetime

from packages.execution.adapter_factory import AdapterBundle
from packages.shared.types import AgentEvent, ExecutionHandle, UsageReport
from tests.helpers import all_agent_runs, create_task, task_detail, wait_task


def _set_plan(client, task_id, steps, max_parallel=4):
    return client.put(
        f"/api/v1/tasks/{task_id}/plan",
        json={"steps": steps, "max_parallel": max_parallel},
    )


def test_serial_three_agent_handoff(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"], title="三段协作")
    plan = _set_plan(write_client, task["id"], [
        {"id": "s1", "title": "调研", "employee_id": seeded_team["dev"]["id"],
         "instruction": "调研需求并输出要点"},
        {"id": "s2", "title": "实现", "employee_id": seeded_team["qa"]["id"],
         "instruction": "基于调研实现", "depends_on": ["s1"]},
        {"id": "s3", "title": "验收", "employee_id": seeded_team["manager"]["id"],
         "instruction": "验收实现结果", "depends_on": ["s2"]},
    ])
    assert plan.status_code == 200, plan.text
    assert len(plan.json()["children"]) == 3

    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"succeeded"})

    agents = all_agent_runs(detail)
    assert [agent["step_id"] for agent in agents] == ["s1", "s2", "s3"]
    assert len({agent["employee_id"] for agent in agents}) == 3
    assert detail["result"]["steps"][-1]["step_id"] == "s3"
    assert detail["result"]["summary"].startswith("[mock]")

    assert {child["state"] for child in detail["children"]} == {"succeeded"}
    assert all(child["result"]["agent_run_id"] for child in detail["children"])

    timeline = write_client.get(f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
    handoffs = [item for item in timeline if item["kind"] == "handoff"]
    assert len(handoffs) == 2
    assert {item["step_id"] for item in handoffs} == {"s2", "s3"}
    assert all(item["summary"] for item in handoffs)


def test_parallel_wave_really_runs_concurrently(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"], title="并行波次")
    plan = _set_plan(write_client, task["id"], [
        {"id": "a", "employee_id": seeded_team["dev"]["id"], "instruction": "并行 A"},
        {"id": "b", "employee_id": seeded_team["qa"]["id"], "instruction": "并行 B"},
        {"id": "c", "employee_id": seeded_team["manager"]["id"],
         "instruction": "汇总", "depends_on": ["a", "b"]},
    ])
    assert plan.status_code == 200, plan.text

    monkeypatch.setenv("AGENTOS_MOCK_DELAY_MS", "400")
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"succeeded"}, timeout=30)

    agents = {agent["step_id"]: agent for agent in all_agent_runs(detail)}
    first = datetime.fromisoformat(agents["a"]["started_at"])
    second = datetime.fromisoformat(agents["b"]["started_at"])
    assert abs((first - second).total_seconds()) < 0.3, (first, second)
    # 汇总步骤在两者之后
    assert datetime.fromisoformat(agents["c"]["started_at"]) >= max(first, second)


def test_plan_rejects_duplicate_and_blank_steps(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"])

    duplicate = _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": seeded_team["dev"]["id"], "instruction": "A"},
        {"id": "s1", "employee_id": seeded_team["qa"]["id"], "instruction": "B"},
    ])
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "TASK_PLAN_INVALID"

    blank = _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": seeded_team["dev"]["id"], "instruction": "   "},
    ])
    assert blank.status_code == 422

    bad_parallel = write_client.put(
        f"/api/v1/tasks/{task['id']}/plan",
        json={"steps": [{"id": "s1", "employee_id": seeded_team["dev"]["id"],
                         "instruction": "A"}], "max_parallel": 0},
    )
    assert bad_parallel.status_code == 422


class _JsonAdapter:
    """替身：返回预设 JSON，用于验证自动拆分的解析与校验（不联网）。"""

    adapter_type = "stub"
    model = "stub/planner"

    def __init__(self, content: str):
        self.content = content
        self._usage = UsageReport(model=self.model, prompt_tokens=10, completion_tokens=10,
                                  cost_usd=0.0, latency_ms=1)

    async def execute(self, task, system_prompt=""):
        return ExecutionHandle(adapter_type=self.adapter_type, external_ref="stub")

    async def stream_events(self, handle):
        yield AgentEvent(type="started", payload={"model": self.model})
        yield AgentEvent(type="message", payload={"content": self.content})
        yield AgentEvent(type="usage", usage=self._usage, payload=self._usage.to_dict())
        yield AgentEvent(type="completed", payload={"finish_reason": "stub"})

    async def get_usage(self, handle):
        return self._usage

    async def close(self):
        return None


def _patch_planner(monkeypatch, content: str):
    def fake_build(session, employee, mode):
        return AdapterBundle(
            adapter=_JsonAdapter(content), mode="mock", model="stub/planner",
            connection_id=None, label=employee.name,
        )

    monkeypatch.setattr("packages.execution.adapter_factory.build_adapter", fake_build)


def test_decompose_valid_json_creates_plan(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"], title="自动拆分")
    plan_json = (
        '{"steps":['
        '{"id":"s1","title":"调研","employee_id":"' + seeded_team["dev"]["id"] + '",'
        '"instruction":"调研需求","depends_on":[]},'
        '{"id":"s2","title":"实现","employee_id":"' + seeded_team["dev"]["id"] + '",'
        '"instruction":"实现功能","depends_on":["s1"]},'
        '{"id":"s3","title":"验收","employee_id":"' + seeded_team["qa"]["id"] + '",'
        '"instruction":"验收功能","depends_on":["s2"]}'
        ']}'
    )
    _patch_planner(monkeypatch, plan_json)

    resp = write_client.post(f"/api/v1/tasks/{task['id']}/decompose", json={"max_steps": 4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decompose"]["steps"] == ["s1", "s2", "s3"]
    assert len(body["task"]["children"]) == 3

    runs = body["task"]["runs"]
    assert any(run["trigger"] == "plan" and run["state"] == "succeeded" for run in runs)
    agents = [agent for run in runs for agent in run["agent_runs"]]
    assert agents[0]["step_id"] == "decompose"
    assert body["task"]["usage"]["calls"] == 1


def test_decompose_invalid_json_does_not_fake_plan(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"], title="坏计划")
    _patch_planner(monkeypatch, "抱歉，我无法拆分。")

    resp = write_client.post(f"/api/v1/tasks/{task['id']}/decompose", json={"max_steps": 3})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "DECOMPOSE_PARSE_FAILED"

    detail = task_detail(write_client, task["id"])
    assert detail["plan"]["steps"] == []
    assert detail["children"] == []
    plan_runs = [run for run in detail["runs"] if run["trigger"] == "plan"]
    assert plan_runs and plan_runs[0]["state"] == "failed"


def test_decompose_requires_manager(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"], title="非管理者拆分")
    _patch_planner(monkeypatch, '{"steps":[]}')
    resp = write_client.post(f"/api/v1/tasks/{task['id']}/decompose", json={"max_steps": 3})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "TASK_ASSIGNEE_INVALID"


def test_decompose_cycle_rejected_without_creating_children(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"], title="环计划")
    cycle_json = (
        '{"steps":['
        '{"id":"s1","employee_id":"' + seeded_team["dev"]["id"] + '","instruction":"A",'
        '"depends_on":["s2"]},'
        '{"id":"s2","employee_id":"' + seeded_team["qa"]["id"] + '","instruction":"B",'
        '"depends_on":["s1"]}'
        ']}'
    )
    _patch_planner(monkeypatch, cycle_json)
    resp = write_client.post(f"/api/v1/tasks/{task['id']}/decompose", json={"max_steps": 3})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TASK_PLAN_CYCLE"

    detail = task_detail(write_client, task["id"])
    assert detail["children"] == []
    # 规划调用本身仍然记录（真实发生过）
    assert [run for run in detail["runs"] if run["trigger"] == "plan"]
    assert detail["usage"]["calls"] == 1

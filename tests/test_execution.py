"""M2-B 验收：Mock 执行、权限闸门、失败/超时/重试、暂停/恢复、取消、重启恢复。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from packages.execution.adapter_factory import AdapterBundle
from packages.execution.runner import TaskRunner
from packages.persistence import get_session
from packages.persistence.models import Task, TaskRun
from packages.shared.types import AgentEvent, ExecutionHandle, new_id
from tests.helpers import all_agent_runs, create_task, task_detail, wait_agent_runs, wait_task


def test_mock_single_agent_success(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="单员工任务", objective="输出三条要点",
    )
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"succeeded"})

    assert detail["result"]["mode"] == "mock"
    assert detail["result"]["summary"].startswith("[mock]")
    assert len(detail["runs"]) == 1
    run = detail["runs"][0]
    assert run["state"] == "succeeded" and run["mode"] == "mock"
    agents = run["agent_runs"]
    assert len(agents) == 1
    assert agents[0]["state"] == "succeeded"
    assert agents[0]["model"] == "mock/echo"
    assert agents[0]["step_id"] == "s1"
    assert agents[0]["output"]["content"].startswith("[mock]")

    assert detail["usage"]["calls"] == 1
    assert detail["usage"]["records"][0]["billable"] is False
    assert detail["usage"]["total_cost_usd"] == 0.0

    events = write_client.get(f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
    types = [item["type"] for item in events]
    assert "run.started" in types and "agent.completed" in types and "task.succeeded" in types


def test_permission_denied_before_model_call(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["qa"]["id"],
        title="越权工具任务", context={"required_tools": ["file.write"]},
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"failed"})

    assert detail["result"]["error"]["code"] == "EXECUTION_PERMISSION_DENIED"
    assert all_agent_runs(detail) == []
    assert detail["usage"]["calls"] == 0
    assert detail["runs"][0]["state"] == "failed"
    assert "file.write" in detail["runs"][0]["error"]


def test_risk_level_exceeded(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="高风险任务", risk_level="high",
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["result"]["error"]["code"] == "EXECUTION_PERMISSION_DENIED"
    assert "风险等级" in detail["result"]["error"]["message"]
    assert all_agent_runs(detail) == []


def test_real_mode_without_credential_fails(write_client, seeded_company, monkeypatch):
    monkeypatch.delenv("M2_MISSING_KEY", raising=False)
    company_id = seeded_company["id"]
    connection = write_client.post(
        f"/api/v1/companies/{company_id}/model-connections",
        json={
            "name": "缺凭据连接", "provider": "deepseek",
            "model": "deepseek/deepseek-chat", "api_key_ref": "env:M2_MISSING_KEY",
        },
    ).json()
    employee = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={"name": "缺凭据员工", "primary_model_id": connection["id"]},
    ).json()
    task = create_task(
        write_client, company_id, employee["id"],
        title="真实模式无凭据", execution_mode="real",
    )
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["result"]["error"]["code"] == "EXECUTION_MODEL_UNAVAILABLE"
    assert all_agent_runs(detail) == []
    # 未发生任何外部调用，也没有费用记录
    assert detail["usage"]["calls"] == 0


def test_retry_after_employee_re_enabled(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    qa = seeded_team["qa"]
    task = create_task(write_client, company_id, qa["id"], title="停用后重试")

    assert write_client.post(f"/api/v1/employees/{qa['id']}/disable").status_code == 200
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    failed = wait_task(write_client, task["id"], {"failed"})
    assert failed["result"]["error"]["code"] == "EXECUTION_PERMISSION_DENIED"

    assert write_client.post(f"/api/v1/employees/{qa['id']}/enable").status_code == 200
    retry = write_client.post(f"/api/v1/tasks/{task['id']}/retry")
    assert retry.status_code == 202, retry.text
    assert retry.json()["run_no"] == 2
    detail = wait_task(write_client, task["id"], {"succeeded"})
    assert len(detail["runs"]) == 2
    assert detail["runs"][0]["state"] == "failed"
    assert detail["runs"][1]["state"] == "succeeded"


def test_mock_injected_failure(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="注入失败", instruction="[fail] 做点什么",
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["result"]["error"]["code"] == "EXECUTION_FAILED"
    agents = all_agent_runs(detail)
    assert len(agents) == 1 and agents[0]["state"] == "failed"
    assert "injected failure" in (agents[0]["error"] or "")


class _HangingAdapter:
    """替身：永不返回，用于验证执行器的步骤超时兜底。"""

    adapter_type = "stub"

    async def execute(self, task, system_prompt=""):
        return ExecutionHandle(adapter_type=self.adapter_type)

    async def stream_events(self, handle):
        await asyncio.sleep(5)
        yield AgentEvent(type="failed", payload={"error": "should not reach"})

    async def get_usage(self, handle):
        return None

    async def close(self):
        return None


def test_step_timeout_is_enforced(write_client, seeded_team, monkeypatch):
    def fake_build(session, employee, mode):
        return AdapterBundle(
            adapter=_HangingAdapter(), mode="mock", model="stub/hang",
            connection_id=None, label=employee.name,
        )

    monkeypatch.setattr("packages.execution.executor.build_adapter", fake_build)
    task = create_task(
        write_client, seeded_team["company"]["id"], seeded_team["dev"]["id"],
        title="步骤超时", context={"step_timeout_s": 0.2}, execution_mode="mock",
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"failed"}, timeout=15)
    assert detail["result"]["error"]["code"] == "EXECUTION_TIMEOUT"
    assert "0.2s" in detail["result"]["error"]["message"]
    assert all_agent_runs(detail) == []  # 超时不伪造成功记录

    timeline = write_client.get(f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
    assert any(item["type"] == "agent.timeout" for item in timeline)


def _three_step_plan(client, team, task_id):
    plan = client.put(
        f"/api/v1/tasks/{task_id}/plan",
        json={"steps": [
            {"id": "s1", "employee_id": team["dev"]["id"], "instruction": "步骤一"},
            {"id": "s2", "employee_id": team["qa"]["id"], "instruction": "步骤二", "depends_on": ["s1"]},
            {"id": "s3", "employee_id": team["manager"]["id"], "instruction": "步骤三", "depends_on": ["s2"]},
        ]},
    )
    assert plan.status_code == 200, plan.text


def test_pause_and_resume_skips_completed_steps(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"], title="暂停恢复")
    _three_step_plan(write_client, seeded_team, task["id"])

    monkeypatch.setenv("AGENTOS_MOCK_DELAY_MS", "350")
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    wait_agent_runs(write_client, task["id"], 1)

    pause = write_client.post(f"/api/v1/tasks/{task['id']}/pause")
    assert pause.status_code == 200, pause.text
    paused = wait_task(write_client, task["id"], {"paused"})
    checkpoint = paused["runs"][-1]["checkpoint"]
    assert 1 <= len(checkpoint["completed_steps"]) < 3

    resume = write_client.post(f"/api/v1/tasks/{task['id']}/resume")
    assert resume.status_code == 202, resume.text
    final = wait_task(write_client, task["id"], {"succeeded"})

    agents = all_agent_runs(final)
    step_ids = [agent["step_id"] for agent in agents]
    assert sorted(step_ids) == ["s1", "s2", "s3"]  # 每个步骤只执行一次
    assert len(step_ids) == 3
    assert len(final["runs"]) == 2


def test_cancel_while_running(write_client, seeded_team, monkeypatch):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"], title="运行中取消")
    _three_step_plan(write_client, seeded_team, task["id"])

    monkeypatch.setenv("AGENTOS_MOCK_DELAY_MS", "350")
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    wait_agent_runs(write_client, task["id"], 1)

    cancel = write_client.post(f"/api/v1/tasks/{task['id']}/cancel")
    assert cancel.status_code == 200, cancel.text
    final = wait_task(write_client, task["id"], {"cancelled"})
    assert len(all_agent_runs(final)) < 3
    assert final["runs"][-1]["state"] == "cancelled"


def test_recovery_marks_interrupted_then_resume(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"], title="重启恢复")

    session = get_session()
    try:
        run = TaskRun(
            id=new_id(), owner_id="local", task_id=task["id"], run_no=1,
            trigger="manual", state="running", mode="mock", checkpoint={},
            worker_id="dead-worker", started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        db_task = session.get(Task, task["id"])
        db_task.state = "running"
        session.commit()
    finally:
        session.close()

    result = TaskRunner().recover()
    assert result["interrupted_runs"] == 1

    detail = task_detail(write_client, task["id"])
    assert detail["state"] == "paused"
    assert detail["runs"][0]["state"] == "interrupted"
    assert "进程重启" in (detail["runs"][0]["error"] or "")

    resume = write_client.post(f"/api/v1/tasks/{task['id']}/resume")
    assert resume.status_code == 202, resume.text
    final = wait_task(write_client, task["id"], {"succeeded"})
    assert final["runs"][-1]["run_no"] == 2


def test_agent_run_uses_active_prompt_version(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    employee = seeded_team["dev"]
    prompt = write_client.post(
        f"/api/v1/employees/{employee['id']}/prompts",
        json={"content": "# 角色\n你是严格的代码审查员。", "note": "初版"},
    )
    assert prompt.status_code == 201, prompt.text

    task = create_task(write_client, company_id, employee["id"], title="带提示词执行")
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"succeeded"})
    agent = all_agent_runs(detail)[0]
    assert agent["prompt_version"] == 1
    assert "严格的代码审查员" in agent["input"]["system_prompt"]

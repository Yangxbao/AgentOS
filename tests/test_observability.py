"""M2-E 验收：时间线、Agent 执行详情、成本聚合、监控摘要、脱敏。"""
from __future__ import annotations

from tests.helpers import all_agent_runs, create_task, task_detail, wait_task


def _run_serial_task(client, team, title="监控任务"):
    company_id = team["company"]["id"]
    task = create_task(client, company_id, team["manager"]["id"], title=title)
    plan = client.put(f"/api/v1/tasks/{task['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": team["dev"]["id"], "instruction": "第一步"},
        {"id": "s2", "employee_id": team["qa"]["id"], "instruction": "第二步", "depends_on": ["s1"]},
    ]})
    assert plan.status_code == 200, plan.text
    assert client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    return wait_task(client, task["id"], {"succeeded"})


def test_timeline_covers_events_agents_and_handoffs(write_client, seeded_team):
    detail = _run_serial_task(write_client, seeded_team)
    timeline = write_client.get(f"/api/v1/tasks/{detail['id']}/timeline").json()
    items = timeline["items"]
    assert timeline["total"] == len(items)
    kinds = {item["kind"] for item in items}
    assert {"event", "agent_run", "handoff"} <= kinds
    types = [item["type"] for item in items]
    assert "task.created" in types and "run.started" in types and "task.succeeded" in types
    ats = [item["at"] for item in items]
    assert ats == sorted(ats)

    agents = [item for item in items if item["kind"] == "agent_run"]
    assert [agent["step_id"] for agent in agents] == ["s1", "s2"]
    assert all(agent["employee_name"] for agent in agents)


def test_usage_matches_agent_runs(write_client, seeded_team):
    detail = _run_serial_task(write_client, seeded_team)
    task_id = detail["id"]

    usage = write_client.get(f"/api/v1/tasks/{task_id}/usage").json()
    assert usage["calls"] == 2
    assert usage["total_tokens"] == (
        usage["total_prompt_tokens"] + usage["total_completion_tokens"]
    )
    assert usage["total_cost_usd"] == 0.0
    assert usage["unknown_cost_records"] == 0
    assert len(usage["by_employee"]) == 2
    assert all(record["billable"] is False for record in usage["records"])

    runs = write_client.get(f"/api/v1/tasks/{task_id}/runs").json()["items"]
    agent_ids = {agent["id"] for run in runs for agent in run["agent_runs"]}
    assert {record["agent_run_id"] for record in usage["records"]} == agent_ids

    # 与任务详情里的 usage 完全一致
    assert task_detail(write_client, task_id)["usage"]["total_tokens"] == usage["total_tokens"]


def test_agent_run_detail(write_client, seeded_team):
    detail = _run_serial_task(write_client, seeded_team)
    agent = all_agent_runs(detail)[0]
    data = write_client.get(f"/api/v1/agent-runs/{agent['id']}").json()
    assert data["step_id"] == "s1"
    assert data["input"]["system_prompt"]
    assert data["output"]["content"].startswith("[mock]")
    assert data["usage"][0]["billable"] is False
    assert data["usage"][0]["model"] == "mock/echo"

    missing = write_client.get("/api/v1/agent-runs/not-exist")
    assert missing.status_code == 404


def test_monitor_summary(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    _run_serial_task(write_client, seeded_team, title="成功的任务")
    pending = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="待审批任务", approval_required=True,
    )
    write_client.post(f"/api/v1/tasks/{pending['id']}/run")
    wait_task(write_client, pending["id"], {"awaiting_approval"})

    summary = write_client.get(
        "/api/v1/monitor/summary", params={"company_id": company_id}
    ).json()
    assert summary["task_total"] == 2
    assert summary["states"].get("succeeded") == 1
    assert summary["states"].get("awaiting_approval") == 1
    assert summary["pending_approvals"] == 1
    assert summary["active_runs"] == 0
    assert summary["today_calls"] == 2
    assert len(summary["recent_agent_runs"]) == 2


def test_usage_filters_and_dates(write_client, seeded_team):
    detail = _run_serial_task(write_client, seeded_team)
    employee_id = seeded_team["dev"]["id"]

    by_employee = write_client.get(
        "/api/v1/usage", params={"employee_id": employee_id}
    ).json()
    assert by_employee["calls"] == 1
    assert by_employee["by_employee"][0]["employee_id"] == employee_id

    by_task = write_client.get("/api/v1/usage", params={"task_id": detail["id"]}).json()
    assert by_task["calls"] == 2

    future = write_client.get("/api/v1/usage", params={"date_from": "2099-01-01"}).json()
    assert future["calls"] == 0

    bad_date = write_client.get("/api/v1/usage", params={"date_from": "not-a-date"})
    assert bad_date.status_code == 422


def test_no_secret_leaks_in_monitoring(write_client, seeded_team):
    detail = _run_serial_task(write_client, seeded_team)
    task_id = detail["id"]
    endpoints = [
        f"/api/v1/tasks/{task_id}",
        f"/api/v1/tasks/{task_id}/timeline",
        f"/api/v1/tasks/{task_id}/runs",
        f"/api/v1/tasks/{task_id}/usage",
        f"/api/v1/monitor/summary?company_id={seeded_team['company']['id']}",
    ]
    for path in endpoints:
        resp = write_client.get(path)
        assert resp.status_code == 200, (path, resp.text)
        assert "test-secret" not in resp.text, path
        assert "sk-" not in resp.text, path

    agent = all_agent_runs(detail)[0]
    agent_resp = write_client.get(f"/api/v1/agent-runs/{agent['id']}")
    assert "test-secret" not in agent_resp.text

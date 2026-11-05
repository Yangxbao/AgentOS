"""M2-D 验收：人工审批、暂停/恢复、驳回回退、返工上限。"""
from __future__ import annotations

from tests.helpers import all_agent_runs, create_task, task_detail, wait_task


def _decide(client, approval_id, decision, comment="", rewind_step_id=None):
    return client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": decision, "comment": comment, "rewind_step_id": rewind_step_id},
    )


def _after_run_task(client, team, title="交付审批", max_rework=3, steps=None):
    company_id = team["company"]["id"]
    task = create_task(
        client, company_id, team["dev"]["id"], title=title,
        approval_required=True, approval_stage="after_run", max_rework=max_rework,
    )
    if steps:
        plan = client.put(f"/api/v1/tasks/{task['id']}/plan", json={"steps": steps})
        assert plan.status_code == 200, plan.text
    return task


def test_before_run_approval_blocks_execution(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="执行前审批", approval_required=True,
    )
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    assert len(detail["pending_approvals"]) == 1
    approval = detail["pending_approvals"][0]
    assert approval["gate"] == "before_run"
    assert all_agent_runs(detail) == []  # 未审批前绝不调用模型
    assert detail["usage"]["calls"] == 0

    approved = _decide(write_client, approval["id"], "approve", "同意执行")
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "queued"
    assert approved.json()["run_id"]

    final = wait_task(write_client, task["id"], {"succeeded"})
    assert len(all_agent_runs(final)) == 1
    approvals = write_client.get(f"/api/v1/tasks/{task['id']}/approvals").json()
    assert approvals[0]["status"] == "approved"
    assert approvals[0]["decided_by"] == "local"

    again = _decide(write_client, approval["id"], "approve")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "APPROVAL_NOT_PENDING"


def test_after_run_approval_does_not_reexecute(write_client, seeded_team):
    task = _after_run_task(write_client, seeded_team, title="交付后审批")
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    assert len(all_agent_runs(detail)) == 1

    approval = detail["pending_approvals"][0]
    assert approval["gate"] == "after_run"
    approved = _decide(write_client, approval["id"], "approve", "通过")
    assert approved.status_code == 200, approved.text
    assert approved.json()["run_id"] is None  # 不再新建 run

    final = wait_task(write_client, task["id"], {"succeeded"})
    assert len(all_agent_runs(final)) == 1  # 不重复执行
    assert len(final["runs"]) == 1


def test_reject_rewinds_to_step_and_keeps_upstream(write_client, seeded_team):
    task = _after_run_task(write_client, seeded_team, title="驳回返工", steps=[
        {"id": "s1", "employee_id": seeded_team["dev"]["id"], "instruction": "做第一步"},
        {"id": "s2", "employee_id": seeded_team["qa"]["id"], "instruction": "做第二步", "depends_on": ["s1"]},
    ])
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    approval = detail["pending_approvals"][0]

    rejected = _decide(
        write_client, approval["id"], "request_changes",
        "第二步需要重做", rewind_step_id="s2",
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["state"] == "rework_required"
    assert rejected.json()["rewind"]["reset_steps"] == ["s2"]

    after = task_detail(write_client, task["id"])
    assert after["rework_count"] == 1
    assert after["runs"][-1]["checkpoint"]["completed_steps"] == ["s1"]

    resume = write_client.post(f"/api/v1/tasks/{task['id']}/resume")
    assert resume.status_code == 202, resume.text
    gated = wait_task(write_client, task["id"], {"awaiting_approval"}, timeout=30)
    agents = all_agent_runs(gated)
    assert [agent["step_id"] for agent in agents].count("s1") == 1  # 上游不重复
    assert [agent["step_id"] for agent in agents].count("s2") == 2  # 回退步骤重跑

    second = gated["pending_approvals"][0]
    assert _decide(write_client, second["id"], "approve", "这次通过").status_code == 200
    final = wait_task(write_client, task["id"], {"succeeded"})
    assert len(final["runs"]) == 2
    assert [agent["step_id"] for agent in all_agent_runs(final)].count("s1") == 1


def test_rework_limit_enforced(write_client, seeded_team):
    task = _after_run_task(write_client, seeded_team, title="返工上限", max_rework=1)
    assert write_client.post(f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    first = detail["pending_approvals"][0]
    assert _decide(write_client, first["id"], "reject", "重做").status_code == 200

    assert write_client.post(f"/api/v1/tasks/{task['id']}/resume").status_code == 202
    again = wait_task(write_client, task["id"], {"awaiting_approval"}, timeout=30)
    second = again["pending_approvals"][0]

    blocked = _decide(write_client, second["id"], "reject", "再改一次")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TASK_REWORK_LIMIT"

    # 审批仍待处理，任务没有被误改状态
    still = task_detail(write_client, task["id"])
    assert still["state"] == "awaiting_approval"
    assert still["pending_approvals"][0]["id"] == second["id"]

    assert _decide(write_client, second["id"], "approve", "就这样").status_code == 200
    assert wait_task(write_client, task["id"], {"succeeded"})["state"] == "succeeded"


def test_cancel_while_awaiting_approval_cancels_pending(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="待审批取消", approval_required=True,
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    approval_id = detail["pending_approvals"][0]["id"]

    cancelled = write_client.post(f"/api/v1/tasks/{task['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"

    approvals = write_client.get(f"/api/v1/tasks/{task['id']}/approvals").json()
    assert approvals[0]["status"] == "cancelled"
    decision = _decide(write_client, approval_id, "approve")
    assert decision.status_code == 409


def test_pending_approval_list(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="待办审批", approval_required=True,
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    wait_task(write_client, task["id"], {"awaiting_approval"})

    listing = write_client.get("/api/v1/approvals", params={"status_filter": "pending"}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["task_title"] == "待办审批"

    by_company = write_client.get(
        "/api/v1/approvals", params={"status_filter": "pending", "company_id": company_id}
    ).json()
    assert by_company["total"] == 1

    detail = write_client.get(f"/api/v1/approvals/{listing['items'][0]['id']}").json()
    assert detail["task"]["id"] == task["id"]

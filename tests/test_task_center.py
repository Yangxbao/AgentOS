"""M2-A 验收：任务中心 CRUD、分配校验、状态机、计划、防重复执行。"""
from __future__ import annotations

from tests.helpers import create_task, task_detail, wait_task


def test_create_list_and_detail_persist(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="持久化任务", objective="刷新后仍在", priority="high",
    )
    assert task["state"] == "draft"
    assert task["priority"] == "high"
    assert task["root_task_id"] == task["id"]

    listing = write_client.get(f"/api/v1/companies/{company_id}/tasks").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == task["id"]
    assert listing["items"][0]["assignee_name"] == "开发乙"

    detail = task_detail(write_client, task["id"])
    assert detail["title"] == "持久化任务"
    assert detail["employees"][seeded_team["dev"]["id"]]["name"] == "开发乙"
    assert detail["runs"] == []
    assert detail["usage"]["calls"] == 0


def test_task_list_filters(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    first = create_task(write_client, company_id, seeded_team["dev"]["id"], title="写代码")
    create_task(write_client, company_id, seeded_team["qa"]["id"], title="写测试")

    by_assignee = write_client.get(
        f"/api/v1/companies/{company_id}/tasks",
        params={"assignee_employee_id": seeded_team["dev"]["id"]},
    ).json()
    assert [item["id"] for item in by_assignee["items"]] == [first["id"]]

    by_q = write_client.get(
        f"/api/v1/companies/{company_id}/tasks", params={"q": "测试"}
    ).json()
    assert by_q["total"] == 1

    by_state = write_client.get(
        f"/api/v1/companies/{company_id}/tasks", params={"state": "succeeded"}
    ).json()
    assert by_state["total"] == 0


def test_assignee_and_reviewer_validation(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]

    missing = write_client.post(
        f"/api/v1/companies/{company_id}/tasks",
        json={"title": "无员工", "assignee_employee_id": "not-exist"},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "TASK_ASSIGNEE_INVALID"

    self_review = write_client.post(
        f"/api/v1/companies/{company_id}/tasks",
        json={
            "title": "自审", "assignee_employee_id": seeded_team["dev"]["id"],
            "reviewer_employee_id": seeded_team["dev"]["id"],
        },
    )
    assert self_review.status_code == 422

    no_review_right = write_client.post(
        f"/api/v1/companies/{company_id}/tasks",
        json={
            "title": "无资格审查", "assignee_employee_id": seeded_team["qa"]["id"],
            "reviewer_employee_id": seeded_team["dev"]["id"],
        },
    )
    assert no_review_right.status_code == 422
    assert no_review_right.json()["error"]["code"] == "APPROVAL_REVIEWER_INVALID"

    qa_review = write_client.post(
        f"/api/v1/companies/{company_id}/tasks",
        json={
            "title": "有资格审查", "assignee_employee_id": seeded_team["dev"]["id"],
            "reviewer_employee_id": seeded_team["qa"]["id"],
        },
    )
    assert qa_review.status_code == 201, qa_review.text
    assert qa_review.json()["reviewer_employee_id"] == seeded_team["qa"]["id"]


def test_update_only_draft_and_optimistic_lock(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"], title="原标题")

    updated = write_client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "新标题", "expected_version": task["version"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "新标题"
    assert updated.json()["version"] == task["version"] + 1

    stale = write_client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "旧版本写入", "expected_version": task["version"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT_STALE"


def test_illegal_transitions_rejected(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"])

    pause = write_client.post(f"/api/v1/tasks/{task['id']}/pause")
    assert pause.status_code == 409
    assert pause.json()["error"]["code"] == "TASK_ILLEGAL_TRANSITION"
    assert "queued" in pause.json()["error"]["detail"]["allowed"]

    cancel = write_client.post(f"/api/v1/tasks/{task['id']}/cancel")
    assert cancel.status_code == 200 and cancel.json()["state"] == "cancelled"

    again = write_client.post(f"/api/v1/tasks/{task['id']}/cancel")
    assert again.status_code == 409

    run_cancelled = write_client.post(f"/api/v1/tasks/{task['id']}/run")
    assert run_cancelled.status_code == 409

    update_cancelled = write_client.patch(
        f"/api/v1/tasks/{task['id']}", json={"title": "改不动"}
    )
    assert update_cancelled.status_code == 409
    assert update_cancelled.json()["error"]["code"] == "TASK_NOT_EDITABLE"


def test_duplicate_run_rejected(write_client, seeded_team, monkeypatch):
    monkeypatch.setenv("AGENTOS_MOCK_DELAY_MS", "400")
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["dev"]["id"])

    first = write_client.post(f"/api/v1/tasks/{task['id']}/run")
    assert first.status_code == 202, first.text
    second = write_client.post(f"/api/v1/tasks/{task['id']}/run")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "TASK_ACTIVE_RUN_EXISTS"

    wait_task(write_client, task["id"], {"succeeded"})


def test_plan_creates_subtasks_and_validates(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"])

    cycle = write_client.put(
        f"/api/v1/tasks/{task['id']}/plan",
        json={"steps": [
            {"id": "s1", "employee_id": seeded_team["dev"]["id"],
             "instruction": "做 A", "depends_on": ["s2"]},
            {"id": "s2", "employee_id": seeded_team["qa"]["id"],
             "instruction": "做 B", "depends_on": ["s1"]},
        ]},
    )
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "TASK_PLAN_CYCLE"

    bad_employee = write_client.put(
        f"/api/v1/tasks/{task['id']}/plan",
        json={"steps": [{"id": "s1", "employee_id": "ghost", "instruction": "做 A"}]},
    )
    assert bad_employee.status_code == 422
    assert bad_employee.json()["error"]["code"] == "TASK_ASSIGNEE_INVALID"

    bad_dep = write_client.put(
        f"/api/v1/tasks/{task['id']}/plan",
        json={"steps": [{"id": "s1", "employee_id": seeded_team["dev"]["id"],
                         "instruction": "做 A", "depends_on": ["nope"]}]},
    )
    assert bad_dep.status_code == 422

    plan = write_client.put(
        f"/api/v1/tasks/{task['id']}/plan",
        json={"steps": [
            {"id": "s1", "title": "实现", "employee_id": seeded_team["dev"]["id"],
             "instruction": "实现功能"},
            {"id": "s2", "title": "测试", "employee_id": seeded_team["qa"]["id"],
             "instruction": "验证功能", "depends_on": ["s1"]},
        ]},
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert [step["id"] for step in body["plan"]["steps"]] == ["s1", "s2"]
    assert len(body["children"]) == 2
    assert {child["state"] for child in body["children"]} == {"pending"}

    # 子任务不能单独编辑/运行；M3-B 起 pending 子任务可设计划（形成任务树，见 M3_MASTER_PLAN §7.2）
    child_id = body["children"][0]["id"]
    child_update = write_client.patch(f"/api/v1/tasks/{child_id}", json={"title": "改子任务"})
    assert child_update.status_code == 409
    child_run = write_client.post(f"/api/v1/tasks/{child_id}/run")
    assert child_run.status_code == 409
    child_plan = write_client.put(
        f"/api/v1/tasks/{child_id}/plan",
        json={"steps": [{"id": "x", "employee_id": seeded_team["dev"]["id"], "instruction": "x"}]},
    )
    assert child_plan.status_code == 200, child_plan.text
    detail_child = write_client.get(f"/api/v1/tasks/{child_id}").json()
    assert len(detail_child["children"]) == 1  # 孙任务已创建，父执行器递归调度


def test_task_not_found(write_client):
    assert write_client.get("/api/v1/tasks/not-exist").status_code == 404

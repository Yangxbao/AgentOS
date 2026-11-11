"""任务导出（JSON / Markdown）：聚合完整、Markdown 可读、格式校验与审计留痕。"""
from __future__ import annotations

from tests.helpers import create_task, run_task, wait_task


def _finish_single_step_task(write_client, seeded_team) -> str:
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"],
                       title="导出验收任务", objective="验证导出聚合")
    run_task(write_client, task["id"])
    wait_task(write_client, task["id"], {"succeeded"})
    return task["id"]


def test_export_json_contains_full_lifecycle(write_client, seeded_team):
    task_id = _finish_single_step_task(write_client, seeded_team)
    resp = write_client.get(f"/api/v1/tasks/{task_id}/export")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == task_id
    assert data["state"] == "succeeded"
    # 全生命周期区块齐全
    for key in ("runs", "timeline", "plan_revisions", "usage", "children", "plan"):
        assert key in data, f"导出缺少 {key}"
    assert len(data["runs"]) >= 1
    assert data["usage"]["calls"] >= 1
    # 时间线覆盖执行事件
    kinds = {item["kind"] for item in data["timeline"]}
    assert "event" in kinds
    assert "agent_run" in kinds


def test_export_markdown_renders_report(write_client, seeded_team):
    task_id = _finish_single_step_task(write_client, seeded_team)
    resp = write_client.get(f"/api/v1/tasks/{task_id}/export?format=markdown")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    assert "# 任务报告：导出验收任务" in text
    assert "## 目标" in text and "验证导出聚合" in text
    assert "## 执行记录" in text
    assert "## 成本" in text
    assert "## 审批记录" in text and "（无审批）" in text
    assert "## 时间线" in text


def test_export_markdown_includes_plan_table(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"], title="计划导出")
    plan = {"steps": [
        {"id": "s1", "employee_id": seeded_team["manager"]["id"], "instruction": "写大纲",
         "deliverable": "outline.md", "depends_on": []},
        {"id": "s2", "employee_id": seeded_team["dev"]["id"], "instruction": "按大纲成文",
         "deliverable": "doc.md", "depends_on": ["s1"]},
    ]}
    resp = write_client.put(f"/api/v1/tasks/{task['id']}/plan", json=plan)
    assert resp.status_code == 200, resp.text
    resp = write_client.get(f"/api/v1/tasks/{task['id']}/export?format=markdown")
    assert resp.status_code == 200
    assert "| # | 执行人 | 指令 | 交付物 | 依赖 |" in resp.text
    assert "outline.md" in resp.text and "s1" in resp.text


def test_export_rejects_unknown_format(write_client, seeded_team):
    company_id = seeded_team["company"]["id"]
    task = create_task(write_client, company_id, seeded_team["manager"]["id"])
    resp = write_client.get(f"/api/v1/tasks/{task['id']}/export?format=pdf")
    assert resp.status_code == 422


def test_export_writes_audit(write_client, seeded_team):
    """导出动作必须写审计（task.export），可追溯。"""
    resp = write_client.get("/api/v1/audit?action=task.export")
    assert resp.status_code == 200
    body = resp.json()
    before = body.get("total", len(body.get("items", [])))
    task_id = _finish_single_step_task(write_client, seeded_team)
    assert write_client.get(f"/api/v1/tasks/{task_id}/export").status_code == 200
    resp = write_client.get("/api/v1/audit?action=task.export")
    body = resp.json()
    after = body.get("total", len(body.get("items", [])))
    assert after == before + 1


def test_export_missing_task_404(write_client):
    resp = write_client.get("/api/v1/tasks/nonexistent/export")
    assert resp.status_code == 404

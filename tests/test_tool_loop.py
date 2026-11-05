"""工具循环（M3-A §4.4）：模型请求工具、授权可见性、次数上限、审批挂起与恢复。"""
from __future__ import annotations

import pytest

from tests.helpers import all_agent_runs, create_task, wait_task

WS = "workspace_id"


def _marker(workspace_id: str, path: str = "notes/out.txt", content: str = "generated",
            mode: str = "create") -> str:
    return (
        f'[tool:fs.write_file {{"workspace_id":"{workspace_id}","path":"{path}",'
        f'"content":"{content}","mode":"{mode}"}}]'
    )


def _run(client, task_id: str) -> None:
    resp = client.post(f"/api/v1/tasks/{task_id}/run")
    assert resp.status_code == 202, resp.text


def test_task_without_tools_keeps_m2_behaviour(write_client, seeded_team, tools_on):
    """没有被授权工具的员工：完全走 M2 单次调用，不产生任何 tool_call。"""
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, seeded_team["dev"]["id"],
        title="无工具任务", instruction="[tool:fs.read_file {}] 不应触发",
    )
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 0
    assert len(all_agent_runs(detail)) == 1


def test_single_tool_call(write_client, seeded_team, tool_employee, seeded_workspace,
                          workspace_root, tools_on):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="单次工具",
        instruction=_marker(seeded_workspace["id"]) + " 写一个文件",
    )
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 1
    assert calls["items"][0]["tool_name"] == "fs.write_file"
    assert calls["items"][0]["status"] == "succeeded"
    assert (workspace_root / "notes" / "out.txt").read_text(encoding="utf-8") == "generated"
    agents = all_agent_runs(detail)
    assert len(agents) == 1 and agents[0]["state"] == "succeeded"
    assert agents[0]["input"]["tool_calls"] == 1


def test_multiple_tool_calls_in_sequence(write_client, seeded_team, tool_employee,
                                        seeded_workspace, workspace_root, tools_on):
    company_id = seeded_team["company"]["id"]
    instruction = (
        _marker(seeded_workspace["id"], "notes/one.txt", "one")
        + " "
        + _marker(seeded_workspace["id"], "notes/two.txt", "two")
        + " 写两个文件"
    )
    task = create_task(
        write_client, company_id, tool_employee["id"], title="两次工具", instruction=instruction
    )
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 2
    assert {item["tool_name"] for item in calls["items"]} == {"fs.write_file"}
    assert [item["call_index"] for item in sorted(calls["items"], key=lambda i: i["call_index"])] == [0, 1]
    assert (workspace_root / "notes" / "one.txt").exists()
    assert (workspace_root / "notes" / "two.txt").exists()
    assert all_agent_runs(detail)[0]["input"]["tool_calls"] == 2


def test_unauthorized_tool_is_denied_but_step_continues(write_client, seeded_team, tool_employee,
                                                       seeded_workspace, tools_on):
    company_id = seeded_team["company"]["id"]
    instruction = (
        f'[tool:fs.delete_file {{"workspace_id":"{seeded_workspace["id"]}",'
        f'"path":"notes/a.txt"}}] 删除并按结果继续'
    )
    task = create_task(
        write_client, company_id, tool_employee["id"], title="未授权工具", instruction=instruction
    )
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 1
    item = calls["items"][0]
    assert item["status"] == "denied"
    assert item["error_code"] in {"TOOL_NOT_GRANTED", "CATEGORY_DISABLED"}
    assert all_agent_runs(detail)[0]["state"] == "succeeded"


def test_shell_tool_is_denied(write_client, seeded_team, tool_employee, tools_on):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="Shell 拒绝",
        instruction='[tool:shell.run {"command":"echo hi"}] 尝试执行命令',
    )
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 1
    assert calls["items"][0]["error_code"] == "SHELL_DISABLED"
    assert calls["items"][0]["risk_level"] == "critical"
    assert all_agent_runs(detail)[0]["state"] == "succeeded"


def test_unregistered_tool_is_denied(write_client, seeded_team, tool_employee, tools_on):
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="未注册工具",
        instruction='[tool:fs.chmod {"path":"x"}] 尝试调用不存在的工具',
    )
    _run(write_client, task["id"])
    wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["items"][0]["error_code"] == "TOOL_NOT_REGISTERED"


def test_tool_loop_limit(write_client, seeded_team, tool_employee, seeded_workspace, tools_on):
    company_id = seeded_team["company"]["id"]
    instruction = " ".join(
        f'[tool:fs.read_file {{"workspace_id":"{seeded_workspace["id"]}","path":"notes/a.txt"}}]'
        for _ in range(9)
    )
    task = create_task(
        write_client, company_id, tool_employee["id"], title="循环上限", instruction=instruction
    )
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["result"]["error"]["code"] == "TOOL_LOOP_EXCEEDED"
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 8


def test_tool_approval_suspend_and_resume(write_client, seeded_team, tool_employee,
                                          seeded_workspace, workspace_root, tools_on):
    company_id = seeded_team["company"]["id"]
    target = workspace_root / "notes" / "a.txt"
    instruction = (
        f'[tool:fs.write_file {{"workspace_id":"{seeded_workspace["id"]}",'
        f'"path":"notes/a.txt","content":"REWRITTEN","mode":"overwrite"}}] 覆盖文件'
    )
    task = create_task(
        write_client, company_id, tool_employee["id"], title="工具审批", instruction=instruction
    )
    _run(write_client, task["id"])
    suspended = wait_task(write_client, task["id"], {"awaiting_approval"})

    pending = [a for a in suspended["approvals"] if a["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["gate"] == "tool_call"
    assert pending[0]["tool_call_id"]
    assert target.read_text(encoding="utf-8") == "hello world"  # 审批前不得生效

    calls_before = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls_before["total"] == 1
    assert calls_before["items"][0]["status"] == "awaiting_approval"
    assert calls_before["items"][0]["approval_id"] == pending[0]["id"]

    approve = write_client.post(
        f"/api/v1/approvals/{pending[0]['id']}/decision",
        json={"decision": "approve", "comment": "允许覆盖"},
    )
    assert approve.status_code == 200, approve.text
    final = wait_task(write_client, task["id"], {"succeeded"})
    assert target.read_text(encoding="utf-8") == "REWRITTEN"

    calls_after = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls_after["total"] == 1, "恢复执行不得重复创建同一工具调用"
    assert calls_after["items"][0]["status"] == "succeeded"
    assert calls_after["items"][0]["call_index"] == 0

    agents = all_agent_runs(final)
    assert len(agents) == 1
    assert agents[0]["input"]["tool_calls"] == 1
    timeline = write_client.get(f"/api/v1/tasks/{task['id']}/timeline").json()
    kinds = [item["type"] for item in timeline["items"]]
    assert "tool.awaiting_approval" in kinds and "tool.succeeded" in kinds


def test_tool_approval_rejected(write_client, seeded_team, tool_employee, seeded_workspace,
                                workspace_root, tools_on):
    company_id = seeded_team["company"]["id"]
    target = workspace_root / "notes" / "a.txt"
    instruction = (
        f'[tool:fs.write_file {{"workspace_id":"{seeded_workspace["id"]}",'
        f'"path":"notes/a.txt","content":"NOPE","mode":"overwrite"}}] 覆盖'
    )
    task = create_task(
        write_client, company_id, tool_employee["id"], title="工具驳回", instruction=instruction
    )
    _run(write_client, task["id"])
    suspended = wait_task(write_client, task["id"], {"awaiting_approval"})
    pending = [a for a in suspended["approvals"] if a["status"] == "pending"][0]

    reject = write_client.post(
        f"/api/v1/approvals/{pending['id']}/decision",
        json={"decision": "reject", "comment": "不允许覆盖"},
    )
    assert reject.status_code == 200, reject.text
    final = wait_task(write_client, task["id"], {"failed"})
    assert final["result"]["error"]["code"] == "TOOL_APPROVAL_REJECTED"
    assert target.read_text(encoding="utf-8") == "hello world"
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["items"][0]["status"] == "denied"


def test_global_switch_off_prevents_tool_execution(write_client, seeded_team, tool_employee,
                                                  seeded_workspace, workspace_root, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "off")
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="全局关闭",
        instruction=_marker(seeded_workspace["id"]) + " 尝试写文件",
    )
    _run(write_client, task["id"])
    wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 0
    assert not (workspace_root / "notes" / "out.txt").exists()


def test_employee_tool_permissions_endpoint(write_client, seeded_team, tool_employee, tools_on):
    resp = write_client.get(f"/api/v1/employees/{tool_employee['id']}/tool-permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["global_enabled"] is True
    available = {item["tool"] for item in body["tools"] if item["available"]}
    assert {"fs.read_file", "fs.write_file", "fs.list_dir", "fs.stat"} <= available
    assert "shell.run" not in available
    assert body["shell_enabled"] is False


@pytest.mark.parametrize("tool_name", ["fs.read_file", "fs.stat"])
def test_read_only_tools_do_not_need_approval(write_client, seeded_team, tool_employee,
                                             seeded_workspace, tools_on, tool_name):
    company_id = seeded_team["company"]["id"]
    args = f'{{"workspace_id":"{seeded_workspace["id"]}","path":"notes/a.txt"}}'
    task = create_task(
        write_client, company_id, tool_employee["id"], title=f"只读工具 {tool_name}",
        instruction=f"[tool:{tool_name} {args}] 读取",
    )
    _run(write_client, task["id"])
    wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["items"][0]["status"] == "succeeded"

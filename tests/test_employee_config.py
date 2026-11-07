"""AI 员工配置中心后端测试：工具白名单持久化、校验、工作区授权、诊断端点链路。

覆盖任务书 §七 后端场景（全部 Mock，不产生任何真实模型调用）：
- 新员工默认白名单为空（安全默认值）；
- tools_allowed 增/删/持久化/去重/非法名拒绝（create + PATCH 两路径）；
- 工作区授权：授权/回显/撤销/撤销后不可访问/跨公司拒绝/不存在资源报错；
- tool-permissions 五层诊断随配置实时变化（授权链路正确性的直接证据）。
"""
from __future__ import annotations

from sqlalchemy import select

from packages.persistence import get_session
from packages.persistence.models import EmployeeWorkspaceGrant
from tests.helpers import create_task, wait_task


def _create_employee(write_client, company_id: str, **overrides) -> dict:
    payload = {
        "name": overrides.pop("name", "配置员工"),
        "title": "执行工程师",
        "primary_model_id": overrides.pop("primary_model_id", None),
        **overrides,
    }
    resp = write_client.post(f"/api/v1/companies/{company_id}/employees", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _need_connection(write_client, seeded_team) -> str:
    return seeded_team["connection"]["id"]


# ---------------------------------------------------------------- 工具白名单


def test_new_employee_default_tools_empty(write_client, seeded_team):
    """新员工默认工具白名单为空（最小权限默认值）。"""
    company_id = seeded_team["company"]["id"]
    employee = _create_employee(write_client, company_id,
                                primary_model_id=_need_connection(write_client, seeded_team))
    assert employee["tools_allowed"] == []


def test_tools_allowlist_add_remove_persist(write_client, seeded_team):
    """增加/取消工具授权，回读一致（持久化验证）。"""
    company_id = seeded_team["company"]["id"]
    employee = _create_employee(write_client, company_id,
                                primary_model_id=_need_connection(write_client, seeded_team))

    resp = write_client.patch(
        f"/api/v1/employees/{employee['id']}",
        json={"tools_allowed": ["fs.list_dir"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tools_allowed"] == ["fs.list_dir"]

    resp = write_client.patch(
        f"/api/v1/employees/{employee['id']}",
        json={"tools_allowed": ["fs.list_dir", "fs.read_file"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tools_allowed"] == ["fs.list_dir", "fs.read_file"]

    # 取消一项
    resp = write_client.patch(
        f"/api/v1/employees/{employee['id']}",
        json={"tools_allowed": ["fs.read_file"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["tools_allowed"] == ["fs.read_file"]

    # 重新查询（另一请求路径）数据一致
    detail = write_client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["tools_allowed"] == ["fs.read_file"]


def test_invalid_tool_name_rejected_on_create_and_patch(write_client, seeded_team):
    """非法工具名称不能写入授权列表（create 与 PATCH 两路径都拒绝）。"""
    company_id = seeded_team["company"]["id"]
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={"name": "坏名字", "primary_model_id": seeded_team["connection"]["id"],
              "tools_allowed": ["fs.hack", "shell.run"]},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "fs.hack" in ",".join(body["detail"]["unknown"])

    employee = _create_employee(write_client, company_id,
                                primary_model_id=seeded_team["connection"]["id"])
    resp = write_client.patch(
        f"/api/v1/employees/{employee['id']}",
        json={"tools_allowed": ["not_a_tool"]},
    )
    assert resp.status_code == 422, resp.text
    # 原白名单不被破坏
    detail = write_client.get(f"/api/v1/employees/{employee['id']}").json()
    assert detail["tools_allowed"] == []


def test_duplicate_tools_normalized(write_client, seeded_team):
    """重复工具名去重（存储规范化）。"""
    company_id = seeded_team["company"]["id"]
    employee = _create_employee(write_client, company_id,
                                primary_model_id=seeded_team["connection"]["id"],
                                tools_allowed=["fs.read_file", "fs.read_file", "fs.list_dir"])
    assert sorted(employee["tools_allowed"]) == ["fs.list_dir", "fs.read_file"]


# ---------------------------------------------------------------- 工作区授权


def test_workspace_grant_revoke_and_isolation(write_client, seeded_team, seeded_workspace,
                                              workspace_root):
    """授权 → 回显 → 撤销 → 撤销后不可访问；工作区列表 grants 回显。"""
    company_id = seeded_team["company"]["id"]
    employee = _create_employee(write_client, company_id,
                                primary_model_id=seeded_team["connection"]["id"],
                                tools_allowed=["fs.read_file", "fs.list_dir"])
    ws_id = seeded_workspace["id"]

    # 授权（read）
    resp = write_client.post(
        f"/api/v1/workspaces/{ws_id}/grants",
        json={"employee_id": employee["id"], "access": "read"},
    )
    assert resp.status_code == 201, resp.text

    # 工作区列表回显本员工的授权
    workspaces = write_client.get(f"/api/v1/companies/{company_id}/workspaces").json()
    target = next(w for w in workspaces if w["id"] == ws_id)
    assert any(g["employee_id"] == employee["id"] for g in target["grants"])

    # 诊断端点：全局 on + 公司策略 + 白名单 + 授权 → available=true
    write_client.patch(f"/api/v1/companies/{company_id}/tool-policy", json={
        "categories": {"file_read": True},
        "allowed_tools": ["fs.list_dir", "fs.read_file"],
    })
    import pytest

    monkey = pytest.MonkeyPatch()
    monkey.setenv("AGENTOS_TOOL_EXECUTION", "on")
    try:
        report = write_client.get(f"/api/v1/employees/{employee['id']}/tool-permissions").json()
        by_tool = {item["tool"]: item for item in report["tools"]}
        assert by_tool["fs.list_dir"]["available"] is True
        assert by_tool["fs.read_file"]["available"] is True
    finally:
        monkey.undo()

    # 撤销 → 诊断 available=false（reason=workspace_not_granted）
    resp = write_client.delete(f"/api/v1/workspaces/{ws_id}/grants/{employee['id']}")
    assert resp.status_code in (200, 204), resp.text
    report = write_client.get(f"/api/v1/employees/{employee['id']}/tool-permissions").json()
    by_tool = {item["tool"]: item for item in report["tools"]}
    assert by_tool["fs.read_file"]["available"] is False
    assert by_tool["fs.read_file"]["reason"] == "workspace_not_granted"

    # 撤销后 DB 中授权关系消失
    with get_session() as session:
        rows = session.execute(
            select(EmployeeWorkspaceGrant).where(
                EmployeeWorkspaceGrant.employee_id == employee["id"],
                EmployeeWorkspaceGrant.workspace_id == ws_id,
            )
        ).scalars().all()
        assert rows == []


def test_grant_rejects_cross_company_employee(write_client, seeded_team, seeded_workspace):
    """不能把其他公司的工作区授权给本司员工之外的对象（跨公司隔离）。"""
    other = write_client.post("/api/v1/companies", json={"name": "另一家公司"}).json()
    conn = write_client.post(
        f"/api/v1/companies/{other['id']}/model-connections",
        json={"name": "外司连接", "provider": "deepseek",
              "model": "deepseek/deepseek-chat", "api_key_ref": "env:NOPE"},
    ).json()
    pos = write_client.post(
        f"/api/v1/companies/{other['id']}/positions", json={"name": "外司岗位"}
    ).json()
    outsider = write_client.post(
        f"/api/v1/companies/{other['id']}/employees",
        json={"name": "外司员工", "primary_model_id": conn["id"],
              "positions": [{"position_id": pos["id"], "is_primary": True}]},
    ).json()

    resp = write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": outsider["id"], "access": "read"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "WORKSPACE_COMPANY_MISMATCH"


def test_grant_unknown_employee_or_workspace(write_client, seeded_team, seeded_workspace):
    """不存在的员工/工作区返回 404。"""
    resp = write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": "nonexistent0000000000000000", "access": "read"},
    )
    assert resp.status_code == 404
    resp = write_client.post(
        "/api/v1/workspaces/nonexistent0000000000000000/grants",
        json={"employee_id": seeded_team["dev"]["id"], "access": "read"},
    )
    assert resp.status_code == 404


def test_end_to_end_mock_task_with_configured_employee(write_client, seeded_team,
                                                       seeded_workspace, tools_on):
    """端到端（Mock）：通过 API 配置好的员工（白名单+授权）能真实执行文件读取任务。"""
    company_id = seeded_team["company"]["id"]
    employee = _create_employee(write_client, company_id,
                                primary_model_id=seeded_team["connection"]["id"],
                                tools_allowed=["fs.list_dir", "fs.read_file"])
    write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": employee["id"], "access": "read"},
    )
    write_client.patch(f"/api/v1/companies/{company_id}/tool-policy", json={
        "categories": {"file_read": True},
        "allowed_tools": ["fs.list_dir", "fs.read_file"],
    })

    task = create_task(
        write_client, company_id, employee["id"], title="配置后执行",
        instruction=(
            f'[tool:fs.list_dir {{"workspace_id":"{seeded_workspace["id"]}"}}]'
            f' [tool:fs.read_file {{"workspace_id":"{seeded_workspace["id"]}","path":"notes/a.txt"}}]'
            " 读取并汇报"
        ),
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"succeeded"})
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()["items"]
    assert {c["tool_name"] for c in calls} == {"fs.list_dir", "fs.read_file"}
    assert all(c["status"] == "succeeded" for c in calls)
    assert detail["state"] == "succeeded"


# ---------------------------------------------------------------- 场景 B：协作与按身份隔离的工具权限


def test_scenario_b_two_employees_collaboration_with_per_identity_tools(
    write_client, seeded_team, seeded_workspace, workspace_root, tools_on
):
    """场景 B：员工 A（有 fs 授权）读取文件，员工 B（无 fs 授权）分析其结果。

    验证：A 的工具调用成功且归属 A；B 调用文件工具被拒但不影响其分析步骤；
    B 的输入包含 A 的上游产出（结果传递正确）；两人工具权限按身份分别校验。
    """
    company_id = seeded_team["company"]["id"]
    employee_a = _create_employee(
        write_client, company_id, name="读取员甲",
        primary_model_id=seeded_team["connection"]["id"],
        tools_allowed=["fs.list_dir", "fs.read_file"],
    )
    employee_b = _create_employee(
        write_client, company_id, name="分析员乙",
        primary_model_id=seeded_team["connection"]["id"],
        # 乙有白名单（才会进入工具循环），但不含 fs.read_file——按身份分别校验的关键
        tools_allowed=["fs.stat"],
    )
    write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": employee_b["id"], "access": "read"},
    )
    write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": employee_a["id"], "access": "read"},
    )
    # 乙有工作区授权（文件工具"可见"），但白名单不含 fs.read_file —— 按身份分别校验的关键

    plan = {
        "steps": [
            {"id": "s1", "title": "读取", "employee_id": employee_a["id"],
             "instruction": (
                 f'[tool:fs.list_dir {{"workspace_id":"{seeded_workspace["id"]}"}}]'
                 f' [tool:fs.read_file {{"workspace_id":"{seeded_workspace["id"]}","path":"notes/a.txt"}}]'
                 " 读取文件"
             ),
             "tools": ["fs.list_dir", "fs.read_file"]},
            {"id": "s2", "title": "分析", "employee_id": employee_b["id"],
             "instruction": (
                 f'[tool:fs.read_file {{"workspace_id":"{seeded_workspace["id"]}","path":"notes/a.txt"}}]'
                 " 基于上游产出完成分析"
             ),
             "depends_on": ["s1"]},
        ],
    }
    task = create_task(write_client, company_id, employee_a["id"], title="协作场景")
    resp = write_client.put(f"/api/v1/tasks/{task['id']}/plan", json=plan)
    assert resp.status_code == 200, resp.text
    task_id = task["id"]
    write_client.post(f"/api/v1/tasks/{task_id}/run")
    detail = wait_task(write_client, task_id, {"succeeded"})

    # 两人身份与职责：s1 归甲、s2 归乙
    steps = {s["step_id"]: s for s in detail["result"]["steps"]}
    assert steps["s1"]["employee_id"] == employee_a["id"]
    assert steps["s2"]["employee_id"] == employee_b["id"]

    # 工具调用按身份分别归属与校验：甲成功、乙被拒（TOOL_NOT_GRANTED）
    calls = write_client.get(f"/api/v1/tasks/{task_id}/tool-calls").json()["items"]
    a_calls = [c for c in calls if c["employee_id"] == employee_a["id"]]
    b_calls = [c for c in calls if c["employee_id"] == employee_b["id"]]
    assert all(c["status"] == "succeeded" for c in a_calls) and a_calls
    assert b_calls and all(
        c["status"] == "denied" and c["error_code"] in {"TOOL_NOT_GRANTED", "CATEGORY_DISABLED"}
        for c in b_calls
    )

    # 乙的输入包含甲的上游产出（结果传递正确；mock 产出为甲的汇报文本）
    agents = {a["step_id"]: a for a in [x for run in detail["runs"] for x in run["agent_runs"]]}
    assert "上游步骤 s1 产出" in agents["s2"]["input"]["instruction"]
    assert "读取员甲" in agents["s2"]["input"]["instruction"]

    # 乙被拒后任务仍然成功（拒绝结果作为数据回灌，分析步骤继续）
    assert detail["state"] == "succeeded"

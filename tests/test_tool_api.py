"""工作区 / 工具策略 / 工具调用 API（M3-01..M3-10）。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from packages.persistence import get_session
from packages.persistence.db import REPO_ROOT
from packages.persistence.models import AuditLog


def _create_workspace(client, company_id, root: Path, name="文档区", mode="read_write"):
    resp = client.post(
        f"/api/v1/companies/{company_id}/workspaces",
        json={"name": name, "root_path": str(root) if root else None, "mode": mode},
    )
    return resp


def test_create_and_get_workspace(write_client, seeded_company, tmp_path):
    root = tmp_path / "ws1"
    root.mkdir()
    resp = _create_workspace(write_client, seeded_company["id"], root)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["root_path"] == str(root.resolve())
    assert body["mode"] == "read_write" and body["status"] == "active"
    assert body["grants"] == []

    detail = write_client.get(f"/api/v1/workspaces/{body['id']}")
    assert detail.status_code == 200 and detail.json()["id"] == body["id"]


def test_create_workspace_default_root(write_client, seeded_company):
    import shutil

    resp = _create_workspace(write_client, seeded_company["id"], None, name="默认根")
    assert resp.status_code == 201, resp.text
    root = Path(resp.json()["root_path"])
    assert root.is_dir() and str(root).startswith(str(REPO_ROOT / "data" / "workspaces"))
    shutil.rmtree(root, ignore_errors=True)  # 默认根落在仓库内，测试后清理


def test_forbidden_roots_rejected(write_client, seeded_company, tmp_path):
    cases = [Path("C:/"), Path.home(), REPO_ROOT]
    for root in cases:
        resp = _create_workspace(write_client, seeded_company["id"], root, name=f"bad-{root.name}")
        assert resp.status_code == 422, (root, resp.text)
        assert resp.json()["error"]["code"] == "WORKSPACE_INVALID_ROOT"

    missing = tmp_path / "not-exists"
    resp = _create_workspace(write_client, seeded_company["id"], missing, name="missing")
    assert resp.status_code == 422


def test_duplicate_workspace_name(write_client, seeded_company, tmp_path):
    root = tmp_path / "dup"
    root.mkdir()
    assert _create_workspace(write_client, seeded_company["id"], root, name="同名").status_code == 201
    second = _create_workspace(write_client, seeded_company["id"], root, name="同名")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "WORKSPACE_NAME_TAKEN"


def test_rename_and_archive_keep_files(write_client, seeded_company, tmp_path):
    root = tmp_path / "keep"
    root.mkdir()
    (root / "note.txt").write_text("keep me", encoding="utf-8")
    workspace = _create_workspace(write_client, seeded_company["id"], root).json()

    renamed = write_client.patch(
        f"/api/v1/workspaces/{workspace['id']}", json={"name": "改名后的区"}
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "改名后的区"

    archived = write_client.delete(f"/api/v1/workspaces/{workspace['id']}")
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert (root / "note.txt").read_text(encoding="utf-8") == "keep me"

    # 归档后不能再授权/修改
    assert write_client.patch(
        f"/api/v1/workspaces/{workspace['id']}", json={"name": "x"}
    ).status_code == 409


def test_grants_lifecycle(write_client, seeded_company, seeded_employee, tmp_path):
    root = tmp_path / "grants"
    root.mkdir()
    workspace = _create_workspace(write_client, seeded_company["id"], root).json()

    created = write_client.post(
        f"/api/v1/workspaces/{workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "read"},
    )
    assert created.status_code == 201 and created.json()["access"] == "read"

    upgraded = write_client.post(
        f"/api/v1/workspaces/{workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "write"},
    )
    assert upgraded.status_code == 201 and upgraded.json()["access"] == "write"

    listed = write_client.get(f"/api/v1/workspaces/{workspace['id']}/grants").json()
    assert len(listed) == 1 and listed[0]["employee_id"] == seeded_employee["id"]
    assert listed[0]["employee_name"] == seeded_employee["name"]

    revoked = write_client.delete(
        f"/api/v1/workspaces/{workspace['id']}/grants/{seeded_employee['id']}"
    )
    assert revoked.status_code == 204
    assert write_client.get(f"/api/v1/workspaces/{workspace['id']}/grants").json() == []
    # 重复撤销 → 404
    again = write_client.delete(
        f"/api/v1/workspaces/{workspace['id']}/grants/{seeded_employee['id']}"
    )
    assert again.status_code == 404


def test_grant_requires_same_company(write_client, seeded_company, seeded_employee, tmp_path):
    other = write_client.post("/api/v1/companies", json={"name": "另一家公司"}).json()
    root = tmp_path / "cross"
    root.mkdir()
    workspace = _create_workspace(write_client, other["id"], root).json()
    resp = write_client.post(
        f"/api/v1/workspaces/{workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "read"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "WORKSPACE_COMPANY_MISMATCH"


def test_unknown_workspace_404(write_client):
    assert write_client.get("/api/v1/workspaces/does-not-exist").status_code == 404
    assert write_client.delete("/api/v1/workspaces/does-not-exist").status_code == 404


def test_tool_catalogue(write_client):
    body = write_client.get("/api/v1/tools").json()
    names = {item["name"] for item in body["items"]}
    assert {
        "fs.list_dir", "fs.read_file", "fs.stat",
        "fs.write_file", "fs.delete_file", "http.request", "shell.run",
    } <= names
    for item in body["items"]:
        assert item["risk"] in {"low", "medium", "high", "critical"}
        assert item["side_effects"] in {"none", "write", "network", "destructive"}
        assert isinstance(item["params"], dict)
        assert item["params"].get("type") == "object"
    assert body["global_enabled"] is False  # 默认关闭


def test_tool_policy_get_and_patch(write_client, seeded_company):
    initial = write_client.get(f"/api/v1/companies/{seeded_company['id']}/tool-policy").json()
    assert initial["policy"]["enabled"] is True
    assert initial["policy"]["categories"]["network"] is False
    assert initial["shell_enabled"] is False

    patched = write_client.patch(
        f"/api/v1/companies/{seeded_company['id']}/tool-policy",
        json={
            "categories": {"network": True},
            "network_domains": ["API.Example.com", "127.0.0.1:9000"],
            "max_tool_calls_per_step": 5,
        },
    )
    assert patched.status_code == 200, patched.text
    policy = patched.json()["policy"]
    assert policy["categories"]["network"] is True
    assert policy["network_domains"] == ["api.example.com", "127.0.0.1:9000"]
    assert policy["max_tool_calls_per_step"] == 5
    assert policy["categories"]["file_read"] is True  # 未提交的类别保持不变


def test_tool_policy_validation(write_client, seeded_company):
    cases = [
        ({"unknown_key": 1}, 422),
        ({"network_domains": ["https://api.example.com/x"]}, 422),
        ({"max_tool_calls_per_step": 0}, 422),
        ({"max_tool_calls_per_step": 99}, 422),
        ({"auto_execute_max_risk": "critical", "max_risk_level": "low"}, 422),
        ({"allowed_tools": ["fs.chmod"]}, 422),
    ]
    for payload, status in cases:
        resp = write_client.patch(
            f"/api/v1/companies/{seeded_company['id']}/tool-policy", json=payload
        )
        assert resp.status_code == status, (payload, resp.text)


def test_tool_calls_listing_and_detail(write_client, seeded_team, tool_employee,
                                       seeded_workspace, tools_on):
    from tests.helpers import create_task, wait_task

    company_id = seeded_team["company"]["id"]
    instruction = (
        f'[tool:fs.list_dir {{"workspace_id":"{seeded_workspace["id"]}","path":"notes"}}] 列目录'
    )
    task = create_task(
        write_client, company_id, tool_employee["id"], title="工具列表", instruction=instruction
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    wait_task(write_client, task["id"], {"succeeded"})

    listing = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert listing["total"] == 1 and listing["page"] == 1
    item = listing["items"][0]
    assert item["tool_name"] == "fs.list_dir" and item["status"] == "succeeded"
    assert item["employee_name"] == tool_employee["name"]
    assert item["output_summary"]["count"] == 1

    detail = write_client.get(f"/api/v1/tool-calls/{item['id']}")
    assert detail.status_code == 200 and detail.json()["id"] == item["id"]
    assert write_client.get("/api/v1/tool-calls/nope").status_code == 404

    page = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls?page=2&page_size=1").json()
    assert page["total"] == 1 and page["items"] == []


def test_workspace_actions_are_audited(write_client, seeded_company, seeded_employee, tmp_path):
    root = tmp_path / "audit"
    root.mkdir()
    workspace = _create_workspace(write_client, seeded_company["id"], root).json()
    write_client.post(
        f"/api/v1/workspaces/{workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "read"},
    )
    write_client.delete(f"/api/v1/workspaces/{workspace['id']}/grants/{seeded_employee['id']}")

    session = get_session()
    try:
        actions = {
            row.action for row in session.execute(
                select(AuditLog).where(AuditLog.target_id == workspace["id"])
            ).scalars().all()
        }
    finally:
        session.close()
    assert {"workspace.create", "workspace.grant", "workspace.revoke"} <= actions

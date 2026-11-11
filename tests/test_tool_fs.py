"""文件工具（M3-A §6）：读写删的真实行为与错误码。"""
from __future__ import annotations

import hashlib
import uuid

import pytest

from packages.permissions.effective import compute_effective_permissions
from packages.persistence import get_session
from packages.persistence.models import Company, Employee, Task
from packages.tools.context import ToolContext
from packages.tools.invoke import invoke_tool
from packages.tools.policy import DEFAULT_TOOL_POLICY, effective_tool_policy


@pytest.fixture
def session(db_url):
    db = get_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def task_row(session, seeded_team, tool_employee):
    row = Task(
        id=uuid.uuid4().hex[:24], title="工具单测", company_id=seeded_team["company"]["id"],
        assignee_employee_id=tool_employee["id"], state="draft", instruction="测试",
    )
    session.add(row)
    session.commit()
    return row


def _ctx(session, company_id, employee_id, *, task=None, allow_delete=False, approved=False):
    company = session.get(Company, company_id)
    employee = session.get(Employee, employee_id)
    policy = effective_tool_policy(company)
    if allow_delete:
        policy = {
            **policy,
            "allowed_tools": list(policy["allowed_tools"]) + ["fs.delete_file"],
        }
    return ToolContext(
        session=session, owner_id="local", company=company, employee=employee,
        task=task, run=None, step_id="s1",
        tool_policy=policy,
        permissions=compute_effective_permissions(session, "local", employee_id)["permissions"],
        approved=approved,
    )


async def test_list_dir_returns_entries(tools_on, session, seeded_team, tool_employee,
                                        seeded_workspace):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.list_dir", {"workspace_id": seeded_workspace["id"], "path": "notes"}
    )
    assert outcome.ok, outcome.error_message
    data = outcome.output["data"]
    assert data["count"] == 1
    assert data["entries"][0]["name"] == "a.txt"
    assert data["entries"][0]["type"] == "file"


async def test_list_dir_depth_and_limit(tools_on, session, seeded_team, tool_employee,
                                        seeded_workspace, workspace_root):
    (workspace_root / "notes" / "nested").mkdir()
    (workspace_root / "notes" / "nested" / "b.txt").write_text("b", encoding="utf-8")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    shallow = await invoke_tool(
        ctx, "fs.list_dir", {"workspace_id": seeded_workspace["id"], "path": "notes", "depth": 1}
    )
    deep = await invoke_tool(
        ctx, "fs.list_dir", {"workspace_id": seeded_workspace["id"], "path": "notes", "depth": 2}
    )
    assert not any(item["name"] == "b.txt" for item in shallow.output["data"]["entries"])
    assert any(item["name"] == "b.txt" for item in deep.output["data"]["entries"])
    limited = await invoke_tool(
        ctx, "fs.list_dir",
        {"workspace_id": seeded_workspace["id"], "path": "notes", "depth": 2, "limit": 1},
    )
    assert limited.output["data"]["truncated"] is True


async def test_read_file_ok(tools_on, session, seeded_team, tool_employee, seeded_workspace):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.ok, outcome.error_message
    data = outcome.output["data"]
    assert data["content"] == "hello world"
    assert data["sha256"] == hashlib.sha256(b"hello world").hexdigest()
    # 落库摘要不包含正文
    assert "content" not in (outcome.output or {})


async def test_read_binary_rejected(tools_on, session, seeded_team, tool_employee,
                                    seeded_workspace, workspace_root):
    (workspace_root / "notes" / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/blob.bin"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_BINARY_UNSUPPORTED"


async def test_read_large_file_rejected(tools_on, session, seeded_team, tool_employee,
                                        seeded_workspace, workspace_root):
    (workspace_root / "notes" / "big.txt").write_text("x" * (300 * 1024), encoding="utf-8")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/big.txt"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_OUTPUT_TOO_LARGE"


async def test_read_sensitive_file_rejected(tools_on, session, seeded_team, tool_employee,
                                            seeded_workspace, workspace_root):
    (workspace_root / ".env").write_text("DEEPSEEK_API_KEY=sk-realsecret1234567890", encoding="utf-8")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": ".env"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_SENSITIVE_FILE"


async def test_read_file_with_secret_content_rejected(tools_on, session, seeded_team, tool_employee,
                                                     seeded_workspace, workspace_root):
    (workspace_root / "notes" / "config.txt").write_text(
        "token = sk-abcdefghijklmnop1234567890", encoding="utf-8"
    )
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/config.txt"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_SENSITIVE_FILE"


async def test_stat_returns_metadata_only(tools_on, session, seeded_team, tool_employee,
                                          seeded_workspace):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.stat", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.ok
    data = outcome.output["data"]
    assert data["size"] == 11 and data["type"] == "file"
    assert "content" not in data


async def test_write_create_ok(tools_on, session, seeded_team, tool_employee, seeded_workspace,
                               workspace_root):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "notes/new.txt",
            "content": "你好", "mode": "create",
        },
    )
    assert outcome.ok, outcome.error_message
    assert (workspace_root / "notes" / "new.txt").read_text(encoding="utf-8") == "你好"
    assert outcome.output["data"]["bytes"] == len("你好".encode())
    assert outcome.output["data"]["sha256"] == hashlib.sha256("你好".encode()).hexdigest()


async def test_write_create_refuses_overwrite(tools_on, session, seeded_team, tool_employee,
                                              seeded_workspace, workspace_root):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt", "content": "x"},
    )
    assert not outcome.ok and outcome.error_code == "TOOL_PATH_EXISTS"
    assert (workspace_root / "notes" / "a.txt").read_text(encoding="utf-8") == "hello world"


async def test_write_append(tools_on, session, seeded_team, tool_employee, seeded_workspace,
                            workspace_root):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "notes/a.txt",
            "content": "!!!", "mode": "append",
        },
    )
    assert outcome.ok, outcome.error_message
    assert (workspace_root / "notes" / "a.txt").read_text(encoding="utf-8") == "hello world!!!"


async def test_write_overwrite_requires_approval(tools_on, session, seeded_team, tool_employee,
                                                seeded_workspace, workspace_root, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "notes/a.txt",
            "content": "NEW", "mode": "overwrite",
        },
    )
    assert outcome.suspended and outcome.requires_approval
    assert (workspace_root / "notes" / "a.txt").read_text(encoding="utf-8") == "hello world"


async def test_write_overwrite_after_approval(tools_on, session, seeded_team, tool_employee,
                                              seeded_workspace, workspace_root, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    pending = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "notes/a.txt",
            "content": "NEW", "mode": "overwrite",
        },
    )
    resume = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row,
                  approved=True)
    resume.tool_call_id = pending.tool_call_id
    outcome = await invoke_tool(
        resume, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "notes/a.txt",
            "content": "NEW", "mode": "overwrite",
        },
    )
    assert outcome.ok, outcome.error_message
    assert (workspace_root / "notes" / "a.txt").read_text(encoding="utf-8") == "NEW"


async def test_write_too_large(tools_on, session, seeded_team, tool_employee, seeded_workspace):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "notes/huge.txt",
            "content": "x" * (1024 * 1024 + 10),
        },
    )
    assert not outcome.ok
    assert outcome.error_code in {"TOOL_OUTPUT_TOO_LARGE", "TOOL_ARGS_INVALID"}


async def test_write_missing_parent_dir(tools_on, session, seeded_team, tool_employee,
                                        seeded_workspace, workspace_root):
    """父目录不存在 → 自动创建（2026-11-12 行为变更：模型写嵌套路径不再被卡死）。"""
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {"workspace_id": seeded_workspace["id"], "path": "no/such/dir/a.txt", "content": "x"},
    )
    assert outcome.ok, outcome.error_message
    assert (workspace_root / "no" / "such" / "dir" / "a.txt").read_text(encoding="utf-8") == "x"


async def test_write_in_read_only_workspace(tools_on, session, seeded_team, tool_employee,
                                            seeded_workspace):
    from packages.persistence.models import Workspace

    workspace = session.get(Workspace, seeded_workspace["id"])
    workspace.mode = "read_only"
    session.commit()
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {"workspace_id": seeded_workspace["id"], "path": "notes/ro.txt", "content": "x"},
    )
    assert not outcome.ok and outcome.error_code == "WORKSPACE_READ_ONLY"


async def test_delete_file_requires_approval(tools_on, session, seeded_team, tool_employee,
                                             seeded_workspace, workspace_root, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row,
               allow_delete=True)
    outcome = await invoke_tool(
        ctx, "fs.delete_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.suspended
    assert (workspace_root / "notes" / "a.txt").exists()


async def test_delete_file_after_approval_records_digest(tools_on, session, seeded_team,
                                                         tool_employee, seeded_workspace,
                                                         workspace_root, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row,
               allow_delete=True)
    pending = await invoke_tool(
        ctx, "fs.delete_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    resume = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row,
                  allow_delete=True, approved=True)
    resume.tool_call_id = pending.tool_call_id
    outcome = await invoke_tool(
        resume, "fs.delete_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.ok, outcome.error_message
    assert not (workspace_root / "notes" / "a.txt").exists()
    assert outcome.output["data"]["bytes"] == 11
    assert len(outcome.output["data"]["sha256"]) == 64


async def test_delete_directory_rejected(tools_on, session, seeded_team, tool_employee,
                                        seeded_workspace, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row,
               allow_delete=True)
    outcome = await invoke_tool(
        ctx, "fs.delete_file", {"workspace_id": seeded_workspace["id"], "path": "notes"}
    )
    assert not outcome.ok and outcome.error_code in {"TOOL_PATH_DENIED", "TOOL_PATH_NOT_FOUND"}


async def test_file_tool_without_grant_denied(tools_on, session, seeded_team, tool_employee,
                                              seeded_workspace):
    from packages.persistence.models import EmployeeWorkspaceGrant

    grant = session.query(EmployeeWorkspaceGrant).filter_by(
        employee_id=tool_employee["id"], workspace_id=seeded_workspace["id"]
    ).first()
    session.delete(grant)
    session.commit()
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert not outcome.ok and outcome.error_code == "WORKSPACE_NOT_GRANTED"


async def test_list_dir_marks_symlink_without_following(tools_on, session, seeded_team,
                                                       tool_employee, seeded_workspace,
                                                       workspace_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    try:
        (workspace_root / "notes" / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境不允许创建符号链接")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.list_dir", {"workspace_id": seeded_workspace["id"], "path": "notes"}
    )
    entry = [item for item in outcome.output["data"]["entries"] if item["name"] == "link"][0]
    assert entry["type"] == "symlink"
    inside = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/link/secret.txt"}
    )
    assert not inside.ok and inside.error_code == "TOOL_PATH_DENIED"


def test_default_policy_does_not_allow_delete_or_shell():
    assert "fs.delete_file" not in DEFAULT_TOOL_POLICY["allowed_tools"]
    assert "shell.run" not in DEFAULT_TOOL_POLICY["allowed_tools"]




async def test_write_file_auto_creates_parent_dirs(tools_on, session, seeded_team,
                                                   tool_employee, seeded_workspace,
                                                   workspace_root):
    """写嵌套路径自动创建父目录（真实实验暴露：模型写 game/spec.md 曾被目录卡死）。"""
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "game/sub/spec.md",
            "content": "# spec", "mode": "create",
        },
    )
    assert outcome.ok, outcome.error_message
    assert (workspace_root / "game" / "sub" / "spec.md").read_text(encoding="utf-8") == "# spec"
    # 目录自动创建不会越出工作区：逃逸路径仍被 safe_resolve 拒绝
    outcome2 = await invoke_tool(
        ctx, "fs.write_file",
        {
            "workspace_id": seeded_workspace["id"], "path": "../evil/x.txt",
            "content": "no", "mode": "create",
        },
    )
    assert not outcome2.ok
    assert not (workspace_root.parent / "evil").exists()

"""统一调用入口（M3-A §4.2）：落库、审计、脱敏、幂等、超时、截断、Shell 禁用。"""
from __future__ import annotations

import dataclasses
import uuid

import pytest
from sqlalchemy import select

from packages.permissions.audit import REDACTED
from packages.permissions.effective import compute_effective_permissions
from packages.persistence import get_session
from packages.persistence.models import AuditLog, Company, Employee, Task, TaskEvent, ToolCall
from packages.tools.context import ToolContext
from packages.tools.invoke import invoke_tool
from packages.tools.policy import effective_tool_policy
from packages.tools.registry import REGISTRY


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
        id=uuid.uuid4().hex[:24], title="调用入口单测",
        company_id=seeded_team["company"]["id"],
        assignee_employee_id=tool_employee["id"], state="draft", instruction="测试",
    )
    session.add(row)
    session.commit()
    return row


def _ctx(session, company_id, employee_id, *, task=None, policy_extra=None):
    company = session.get(Company, company_id)
    employee = session.get(Employee, employee_id)
    policy = effective_tool_policy(company)
    if policy_extra:
        policy = {**policy, **policy_extra}
    return ToolContext(
        session=session, owner_id="local", company=company, employee=employee,
        task=task, run=None, step_id="s1", request_id="req-test",
        tool_policy=policy,
        permissions=compute_effective_permissions(session, "local", employee_id)["permissions"],
    )


async def test_success_writes_tool_call_audit_and_event(tools_on, session, seeded_team,
                                                        tool_employee, seeded_workspace,
                                                        task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"},
        call_index=0,
    )
    assert outcome.ok
    row = session.get(ToolCall, outcome.tool_call_id)
    assert row.status == "succeeded"
    assert row.tool_name == "fs.read_file" and row.risk_level == "low"
    assert row.task_id == task_row.id and row.step_id == "s1" and row.call_index == 0
    assert row.output_summary["size"] == 11
    assert row.duration_ms >= 0

    audit = session.execute(
        select(AuditLog).where(
            AuditLog.action == "tool.call", AuditLog.target_id == outcome.tool_call_id
        )
    ).scalars().first()
    assert audit is not None and audit.request_id == "req-test"
    assert audit.detail["status"] == "succeeded"

    event = session.execute(
        select(TaskEvent).where(
            TaskEvent.task_id == task_row.id, TaskEvent.type == "tool.succeeded"
        )
    ).scalars().first()
    assert event is not None and event.payload["tool_call_id"] == outcome.tool_call_id


async def test_denied_writes_record_and_audit(tools_on, session, seeded_team, tool_employee,
                                              task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": "ws-does-not-exist", "path": "a.txt"}
    )
    assert not outcome.ok and outcome.status == "denied"
    assert outcome.error_code == "WORKSPACE_NOT_GRANTED"
    row = session.get(ToolCall, outcome.tool_call_id)
    assert row.status == "denied" and row.error_code == "WORKSPACE_NOT_GRANTED"
    audit = session.execute(
        select(AuditLog).where(AuditLog.target_id == outcome.tool_call_id)
    ).scalars().first()
    assert audit is not None and audit.detail["error_code"] == "WORKSPACE_NOT_GRANTED"


async def test_unknown_tool_rejected(tools_on, session, seeded_team, tool_employee):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "fs.chmod", {"path": "x"})
    assert not outcome.ok and outcome.error_code == "TOOL_NOT_REGISTERED"


async def test_unknown_argument_rejected(tools_on, session, seeded_team, tool_employee,
                                         seeded_workspace):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.read_file",
        {"workspace_id": seeded_workspace["id"], "path": "a.txt", "sudo": True},
    )
    assert not outcome.ok and outcome.error_code == "TOOL_ARGS_INVALID"


async def test_missing_required_argument_rejected(tools_on, session, seeded_team, tool_employee):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "fs.read_file", {"workspace_id": "w"})
    assert not outcome.ok and outcome.error_code == "TOOL_ARGS_INVALID"


async def test_idempotent_replay_does_not_duplicate_side_effect(tools_on, session, seeded_team,
                                                               tool_employee, seeded_workspace,
                                                               workspace_root, task_row):
    args = {
        "workspace_id": seeded_workspace["id"], "path": "notes/once.txt",
        "content": "only once", "mode": "create",
    }
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    first = await invoke_tool(ctx, "fs.write_file", args, call_index=3)
    assert first.ok, first.error_message
    second_ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    second = await invoke_tool(second_ctx, "fs.write_file", args, call_index=3)
    assert second.ok and second.output.get("reused") is True
    assert (workspace_root / "notes" / "once.txt").read_text(encoding="utf-8") == "only once"
    rows = session.execute(
        select(ToolCall).where(ToolCall.task_id == task_row.id, ToolCall.tool_name == "fs.write_file")
    ).scalars().all()
    assert len(rows) == 1


async def test_different_call_index_is_not_reused(tools_on, session, seeded_team, tool_employee,
                                                 seeded_workspace, workspace_root, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    args = {"workspace_id": seeded_workspace["id"], "path": "notes/x.txt", "content": "a"}
    first = await invoke_tool(ctx, "fs.write_file", args, call_index=0)
    second_ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    second = await invoke_tool(second_ctx, "fs.write_file", args, call_index=1)
    assert first.ok
    assert second.error_code == "TOOL_PATH_EXISTS"
    assert first.tool_call_id != second.tool_call_id


async def test_args_summary_redacts_secrets(tools_on, session, seeded_team, tool_employee):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request",
        {"url": "https://api.example.com/x", "headers": {"Authorization": "Bearer abcdefghijklmnop"}},
    )
    row = session.get(ToolCall, outcome.tool_call_id)
    assert "Bearer abcdefghijklmnop" not in str(row.args_summary)
    assert REDACTED in str(row.args_summary)


async def test_output_summary_redacts_secret_like_names(tools_on, session, seeded_team,
                                                       tool_employee, seeded_workspace,
                                                       workspace_root):
    (workspace_root / "notes" / "sk-abcdefghijklmnop1234.txt").write_text("x", encoding="utf-8")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "fs.list_dir", {"workspace_id": seeded_workspace["id"], "path": "notes"}
    )
    assert outcome.ok
    row = session.get(ToolCall, outcome.tool_call_id)
    assert "sk-abcdefghijklmnop1234" not in str(row.output_summary)
    assert REDACTED in str(row.output_summary)


async def test_timeout_is_recorded(tools_on, session, seeded_team, tool_employee, seeded_workspace,
                                   task_row, monkeypatch):
    import asyncio

    async def slow(ctx, args):  # noqa: ARG001
        await asyncio.sleep(0.5)
        return {"ok": True}

    original = REGISTRY["fs.stat"]
    monkeypatch.setitem(
        REGISTRY, "fs.stat", dataclasses.replace(original, handler=slow, timeout_s=0.05)
    )
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.stat", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.status == "timeout" and outcome.error_code == "TOOL_TIMEOUT"
    assert session.get(ToolCall, outcome.tool_call_id).status == "timeout"


async def test_output_truncation(tools_on, session, seeded_team, tool_employee, seeded_workspace,
                                 task_row, monkeypatch):
    async def huge(ctx, args):  # noqa: ARG001
        return {"content": "y" * 5000}

    original = REGISTRY["fs.stat"]
    monkeypatch.setitem(
        REGISTRY, "fs.stat", dataclasses.replace(original, handler=huge, max_output_bytes=200)
    )
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.stat", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.ok and outcome.truncated is True
    assert session.get(ToolCall, outcome.tool_call_id).truncated is True


async def test_shell_always_denied(tools_on, session, seeded_team, tool_employee, task_row):
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(ctx, "shell.run", {"command": "echo hi"})
    assert outcome.status == "denied" and outcome.error_code == "SHELL_DISABLED"
    row = session.get(ToolCall, outcome.tool_call_id)
    assert row.status == "denied" and row.risk_level == "critical"


async def test_global_switch_off_denies_with_audit(session, seeded_team, tool_employee,
                                                   seeded_workspace, task_row, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "off")
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.read_file", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.status == "denied" and outcome.error_code == "TOOLS_DISABLED"
    audit = session.execute(
        select(AuditLog).where(AuditLog.target_id == outcome.tool_call_id)
    ).scalars().first()
    assert audit is not None


async def test_handler_exception_is_contained(tools_on, session, seeded_team, tool_employee,
                                              seeded_workspace, task_row, monkeypatch):
    async def boom(ctx, args):  # noqa: ARG001
        raise RuntimeError("unexpected")

    original = REGISTRY["fs.stat"]
    monkeypatch.setitem(REGISTRY, "fs.stat", dataclasses.replace(original, handler=boom))
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"], task=task_row)
    outcome = await invoke_tool(
        ctx, "fs.stat", {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"}
    )
    assert outcome.status == "failed" and outcome.error_code == "TOOL_EXEC_FAILED"

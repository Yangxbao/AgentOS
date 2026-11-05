"""五层工具权限（M3-A §5）：每个拒绝原因都必须稳定可判定。"""
from __future__ import annotations

import pytest

from packages.persistence import get_session
from packages.persistence.models import Company, Employee, EmployeeWorkspaceGrant, Workspace
from packages.tools.context import ToolContext
from packages.tools.policy import DEFAULT_TOOL_POLICY, decide
from packages.tools.registry import get_spec

PERMS = {"tools": [], "max_risk_level": "medium"}


@pytest.fixture
def session(db_url):
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _ctx(session, company_id, employee_id, *, policy=None, permissions=None):
    company = session.get(Company, company_id)
    employee = session.get(Employee, employee_id)
    return ToolContext(
        session=session, owner_id="local", company=company, employee=employee,
        tool_policy={**DEFAULT_TOOL_POLICY, **(policy or {})},
        permissions=dict(permissions or PERMS),
    )


def _decide(ctx, tool, **args):
    return decide(ctx, get_spec(tool), args)


def test_global_switch_off_denies_everything(tool_employee, seeded_company, session, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "off")
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    decision = _decide(ctx, "fs.read_file", workspace_id="w", path="a.txt")
    assert decision.allowed is False and decision.code == "TOOLS_DISABLED"


def test_company_switch_off(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"], policy={"enabled": False})
    assert _decide(ctx, "fs.read_file", workspace_id="w", path="a.txt").code == "TOOLS_DISABLED"


def test_category_disabled(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={"categories": {"file_read": False}},
    )
    assert _decide(ctx, "fs.read_file", workspace_id="w", path="a.txt").code == "CATEGORY_DISABLED"


def test_tool_not_in_company_allowlist(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={"allowed_tools": ["fs.stat"]},
    )
    assert _decide(ctx, "fs.read_file", workspace_id="w", path="a.txt").code == "TOOL_NOT_GRANTED"


def test_tool_not_in_employee_allowlist(tools_on, tool_employee, seeded_company, session):
    employee = session.get(Employee, tool_employee["id"])
    employee.tools_allowed = ["fs.stat"]
    session.commit()
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    assert _decide(ctx, "fs.read_file", workspace_id="w", path="a.txt").code == "TOOL_NOT_GRANTED"


def test_empty_employee_allowlist_means_no_tools(tools_on, tool_employee, seeded_company, session):
    employee = session.get(Employee, tool_employee["id"])
    employee.tools_allowed = []
    session.commit()
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    assert _decide(ctx, "fs.stat", workspace_id="w", path="a.txt").code == "TOOL_NOT_GRANTED"


def test_position_layer_narrows(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        permissions={"tools": ["fs.stat"], "max_risk_level": "medium"},
    )
    assert _decide(ctx, "fs.read_file", workspace_id="w", path="a.txt").code == "TOOL_NOT_GRANTED"


def test_risk_above_company_ceiling(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={"max_risk_level": "low"},
    )
    assert _decide(
        ctx, "fs.write_file", workspace_id="w", path="a.txt", content="x"
    ).code == "RISK_EXCEEDED"


def test_workspace_not_granted(tools_on, tool_employee, seeded_company, session, seeded_workspace):
    employee = session.get(Employee, tool_employee["id"])
    grant = session.query(EmployeeWorkspaceGrant).filter_by(
        employee_id=employee.id, workspace_id=seeded_workspace["id"]
    ).first()
    session.delete(grant)
    session.commit()
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    decision = _decide(
        ctx, "fs.read_file", workspace_id=seeded_workspace["id"], path="notes/a.txt"
    )
    assert decision.code == "WORKSPACE_NOT_GRANTED"


def test_read_only_grant_blocks_write(tools_on, tool_employee, seeded_company, session,
                                      seeded_workspace):
    grant = session.query(EmployeeWorkspaceGrant).filter_by(
        employee_id=tool_employee["id"], workspace_id=seeded_workspace["id"]
    ).first()
    grant.access = "read"
    session.commit()
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    assert _decide(
        ctx, "fs.write_file", workspace_id=seeded_workspace["id"], path="notes/new.txt", content="x"
    ).code == "WORKSPACE_READ_ONLY"
    # 只读授权下读仍然可用
    assert _decide(
        ctx, "fs.read_file", workspace_id=seeded_workspace["id"], path="notes/a.txt"
    ).allowed


def test_read_only_workspace_mode_blocks_write(tools_on, tool_employee, seeded_company, session,
                                               seeded_workspace):
    workspace = session.get(Workspace, seeded_workspace["id"])
    workspace.mode = "read_only"
    session.commit()
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    assert _decide(
        ctx, "fs.write_file", workspace_id=seeded_workspace["id"], path="notes/new.txt", content="x"
    ).code == "WORKSPACE_READ_ONLY"


def test_archived_workspace_denied(tools_on, tool_employee, seeded_company, session,
                                   seeded_workspace):
    workspace = session.get(Workspace, seeded_workspace["id"])
    workspace.status = "archived"
    session.commit()
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    assert _decide(
        ctx, "fs.read_file", workspace_id=seeded_workspace["id"], path="notes/a.txt"
    ).code == "WORKSPACE_ARCHIVED"


def test_create_is_auto_but_overwrite_needs_approval(tools_on, tool_employee, seeded_company,
                                                     session, seeded_workspace):
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    create = _decide(
        ctx, "fs.write_file", workspace_id=seeded_workspace["id"], path="notes/b.txt", content="x"
    )
    assert create.allowed and not create.requires_approval
    overwrite = _decide(
        ctx, "fs.write_file", workspace_id=seeded_workspace["id"], path="notes/a.txt",
        content="x", mode="overwrite",
    )
    assert overwrite.allowed and overwrite.requires_approval
    assert overwrite.risk == "high"


def test_employee_low_risk_forces_approval(tools_on, tool_employee, seeded_company, session,
                                           seeded_workspace):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        permissions={"tools": [], "max_risk_level": "low"},
    )
    decision = _decide(
        ctx, "fs.write_file", workspace_id=seeded_workspace["id"], path="notes/c.txt", content="x"
    )
    assert decision.allowed and decision.requires_approval


def test_path_escape_denied_before_approval(tools_on, tool_employee, seeded_company, session,
                                            seeded_workspace):
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    decision = _decide(
        ctx, "fs.write_file", workspace_id=seeded_workspace["id"],
        path="../../escape.txt", content="x", mode="overwrite",
    )
    assert decision.allowed is False and decision.code == "TOOL_PATH_DENIED"


def test_delete_tool_disabled_by_default(tools_on, tool_employee, seeded_company, session,
                                         seeded_workspace):
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"])
    decision = _decide(
        ctx, "fs.delete_file", workspace_id=seeded_workspace["id"], path="notes/a.txt"
    )
    assert decision.allowed is False
    assert decision.code in {"TOOL_NOT_GRANTED", "CATEGORY_DISABLED"}


def test_delete_requires_approval_when_enabled(tools_on, tool_employee, seeded_company, session,
                                               seeded_workspace):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={"allowed_tools": DEFAULT_TOOL_POLICY["allowed_tools"] + ["fs.delete_file"]},
    )
    decision = _decide(
        ctx, "fs.delete_file", workspace_id=seeded_workspace["id"], path="notes/a.txt"
    )
    assert decision.allowed and decision.requires_approval and decision.risk == "high"


def test_http_domain_not_whitelisted(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={
            "categories": {"network": True},
            "network_domains": ["api.example.com"],
            "allowed_tools": DEFAULT_TOOL_POLICY["allowed_tools"] + ["http.request"],
        },
    )
    decision = _decide(ctx, "http.request", url="https://evil.example/x")
    assert decision.code == "TOOL_NETWORK_DENIED"


def test_http_get_allowed_on_whitelist(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={
            "categories": {"network": True},
            "network_domains": ["api.example.com"],
            "allowed_tools": DEFAULT_TOOL_POLICY["allowed_tools"] + ["http.request"],
        },
    )
    decision = _decide(ctx, "http.request", url="https://api.example.com/status")
    assert decision.allowed and not decision.requires_approval


def test_http_write_denied_without_policy(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={
            "categories": {"network": True},
            "network_domains": ["api.example.com"],
            "allowed_tools": DEFAULT_TOOL_POLICY["allowed_tools"] + ["http.request"],
        },
    )
    decision = _decide(ctx, "http.request", url="https://api.example.com/hook", method="POST")
    assert decision.code == "TOOL_DISABLED"


def test_http_write_requires_approval_when_enabled(tools_on, tool_employee, seeded_company,
                                                   session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={
            "categories": {"network": True},
            "network_domains": ["api.example.com"],
            "allowed_tools": DEFAULT_TOOL_POLICY["allowed_tools"] + ["http.request"],
            "allow_http_write": True,
        },
    )
    decision = _decide(ctx, "http.request", url="https://api.example.com/hook", method="POST")
    assert decision.allowed and decision.requires_approval and decision.risk == "high"


def test_shell_always_denied_even_if_fully_allowed(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(
        session, seeded_company["id"], tool_employee["id"],
        policy={
            "categories": {"shell": True},
            "allowed_tools": ["shell.run"],
            "max_risk_level": "critical",
        },
        permissions={"tools": [], "max_risk_level": "critical"},
    )
    employee = session.get(Employee, tool_employee["id"])
    employee.tools_allowed = ["shell.run"]
    session.commit()
    decision = _decide(ctx, "shell.run", command="echo hi")
    assert decision.allowed is False and decision.code == "SHELL_DISABLED"


def test_deny_decision_maps_to_domain_error(tools_on, tool_employee, seeded_company, session):
    ctx = _ctx(session, seeded_company["id"], tool_employee["id"], policy={"enabled": False})
    error = _decide(ctx, "fs.stat", workspace_id="w", path="a").as_error()
    assert error.code == "TOOLS_DISABLED" and error.status_code == 403

"""Shell 禁用的多重证明（M3-A §6.7）：注册但禁用、调用被拒、无执行代码路径。"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from packages.persistence import get_session
from packages.persistence.models import Company, Employee
from packages.shared.errors import DomainError
from packages.tools import registry, shell
from packages.tools.context import ToolContext
from packages.tools.invoke import invoke_tool
from packages.tools.policy import DEFAULT_TOOL_POLICY, decide, effective_tool_policy, validate_policy_patch


def test_shell_spec_registered_but_disabled():
    spec = registry.REGISTRY["shell.run"]
    assert spec.enabled is False
    assert spec.enabled_by_default is False
    assert spec.risk == "critical"
    assert spec.category == "shell"


FORBIDDEN_IMPORTS = {"subprocess"}
FORBIDDEN_CALLS = {
    "os.system", "os.popen", "os.execv", "os.execl", "os.spawnv", "os.spawnl",
    "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output",
}


def _scan_tree(path: Path) -> list[str]:
    """用 AST 扫描真实的 import / 调用，而不是匹配注释文本。"""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    hits.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in FORBIDDEN_IMPORTS:
                hits.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            target = node.func
            name = ""
            if isinstance(target, ast.Attribute):
                base = target.value
                if isinstance(base, ast.Name):
                    name = f"{base.id}.{target.attr}"
            elif isinstance(target, ast.Name):
                name = target.id
            if name in FORBIDDEN_CALLS:
                hits.append(f"call {name}")
    return hits


def test_shell_handler_has_no_execution_primitive():
    module = Path(inspect.getsourcefile(shell))
    assert _scan_tree(module) == []


def test_tools_package_has_no_shell_execution_path():
    root = Path(__file__).resolve().parents[1] / "packages" / "tools"
    for path in root.glob("*.py"):
        assert _scan_tree(path) == [], f"{path.name} 存在命令执行路径"


def test_policy_cannot_enable_shell_category():
    with pytest.raises(DomainError) as exc:
        validate_policy_patch({"categories": {"shell": True}})
    assert exc.value.code == "SHELL_DISABLED"


def test_policy_cannot_allow_shell_tool():
    with pytest.raises(DomainError) as exc:
        validate_policy_patch({"allowed_tools": ["shell.run"]})
    assert exc.value.code == "SHELL_DISABLED"


def test_decide_shell_denied_even_with_everything_on(tools_on, seeded_company, seeded_employee):
    session = get_session()
    try:
        company = session.get(Company, seeded_company["id"])
        employee = session.get(Employee, seeded_employee["id"])
        ctx = ToolContext(
            session=session, owner_id="local", company=company, employee=employee,
            tool_policy={
                **DEFAULT_TOOL_POLICY,
                "categories": {"file_read": True, "file_write": True, "network": True, "shell": True},
                "allowed_tools": list(registry.REGISTRY),
                "max_risk_level": "critical",
            },
            permissions={"tools": [], "max_risk_level": "critical"},
        )
        employee.tools_allowed = ["shell.run"]
        session.commit()
        decision = decide(ctx, registry.REGISTRY["shell.run"], {"command": "echo hi"})
        assert decision.allowed is False
        assert decision.code == "SHELL_DISABLED"
    finally:
        session.close()


async def test_invoke_shell_returns_shell_disabled(tools_on, write_client, seeded_company,
                                                   seeded_employee):
    session = get_session()
    try:
        company = session.get(Company, seeded_company["id"])
        employee = session.get(Employee, seeded_employee["id"])
        employee.tools_allowed = ["shell.run"]
        session.commit()
        ctx = ToolContext(
            session=session, owner_id="local", company=company, employee=employee,
            tool_policy={**effective_tool_policy(company), "allowed_tools": ["shell.run"]},
            permissions={"tools": [], "max_risk_level": "critical"},
        )
        outcome = await invoke_tool(ctx, "shell.run", {"command": "echo pwned"})
        assert outcome.status == "denied"
        assert outcome.error_code == "SHELL_DISABLED"
    finally:
        session.close()


def test_api_rejects_enabling_shell(write_client, seeded_company):
    resp = write_client.patch(
        f"/api/v1/companies/{seeded_company['id']}/tool-policy",
        json={"categories": {"shell": True}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "SHELL_DISABLED"

    resp2 = write_client.patch(
        f"/api/v1/companies/{seeded_company['id']}/tool-policy",
        json={"allowed_tools": ["shell.run"]},
    )
    assert resp2.status_code == 403
    assert resp2.json()["error"]["code"] == "SHELL_DISABLED"


def test_tools_catalogue_marks_shell_disabled(write_client):
    body = write_client.get("/api/v1/tools").json()
    shell_item = [item for item in body["items"] if item["name"] == "shell.run"][0]
    assert shell_item["enabled"] is False
    assert shell_item["risk"] == "critical"
    assert body["shell_enabled"] is False
    assert all(item["name"] != "shell.run" or not item["enabled"] for item in body["items"])

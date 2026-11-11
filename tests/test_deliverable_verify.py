"""交付物存在性核验：声明了路径交付物但没落盘 → 任务失败（防假成功）。"""
from __future__ import annotations

import pytest

from packages.execution.executor import _verify_deliverable
from packages.shared.errors import DomainError


def _task_of(employee):
    from packages.persistence.models import Task
    return Task(id="t1", title="t", company_id=employee.company_id, owner_id=employee.owner_id)


def test_deliverable_missing_raises(db_url, seeded_team, tool_employee, seeded_workspace):
    """步骤声明 game/index.html 但工作区没有 → DELIVERABLE_MISSING。"""
    from packages.persistence import get_session
    from packages.persistence.models import Employee

    with get_session() as session:
        employee = session.get(Employee, tool_employee["id"])
        task = _task_of(employee)
        with pytest.raises(DomainError) as exc_info:
            _verify_deliverable(session, task, employee,
                                {"id": "s2", "deliverable": "game/index.html"})
    assert exc_info.value.code == "DELIVERABLE_MISSING"


def test_deliverable_present_passes(db_url, seeded_team, tool_employee, seeded_workspace,
                                    workspace_root):
    """交付物真实落盘 → 通过。"""
    from packages.persistence import get_session
    from packages.persistence.models import Employee

    (workspace_root / "game").mkdir(exist_ok=True)
    (workspace_root / "game" / "index.html").write_text("<html></html>", encoding="utf-8")

    with get_session() as session:
        employee = session.get(Employee, tool_employee["id"])
        task = _task_of(employee)
        # 不抛错即通过
        _verify_deliverable(session, task, employee,
                            {"id": "s2", "deliverable": "game/index.html"})


def test_descriptive_deliverable_skipped(db_url, seeded_team, tool_employee):
    """描述性 deliverable（非路径形态）不检查。"""
    from packages.persistence import get_session
    from packages.persistence.models import Employee

    with get_session() as session:
        employee = session.get(Employee, tool_employee["id"])
        task = _task_of(employee)
        _verify_deliverable(session, task, employee,
                            {"id": "s4", "deliverable": "game/index.html（修订版）"})
        _verify_deliverable(session, task, employee, {"id": "s5", "deliverable": ""})
        _verify_deliverable(session, task, employee, {"id": "s6"})


def test_unauthorized_workspace_does_not_satisfy(db_url, seeded_team, seeded_workspace,
                                                 workspace_root):
    """文件在别的员工授权的工作区存在、但本员工未授权 → 仍判缺失。"""
    from packages.persistence import get_session
    from packages.persistence.models import Employee

    (workspace_root / "game").mkdir(exist_ok=True)
    (workspace_root / "game" / "index.html").write_text("<html></html>", encoding="utf-8")

    with get_session() as session:
        # 经理未授权该工作区
        employee = session.get(Employee, seeded_team["manager"]["id"])
        task = _task_of(employee)
        with pytest.raises(DomainError):
            _verify_deliverable(session, task, employee,
                                {"id": "s2", "deliverable": "game/index.html"})

"""M3-E 监管闸门：预算熔断、连续拒绝熔断、全局 kill switch、监控统计。

验收对齐 M3_MASTER_PLAN §13 / HANDOFF §12：
- 成本/Token 超预算 → 任务 paused + task.budget_exceeded 事件 + 可读 error；
- 连续 3 次 TOOL_DENIED → 任务 paused + task.tool_denied_limit 事件，提示检查授权；
- 全局关闭（env off / kill switch）→ 步骤必需工具时任务可读地失败；
- 监控摘要包含工具统计、拒绝 Top N、预算使用率。
（单步骤 8 次上限 / AGENTOS_TOOL_EXECUTION=off 的调用拒绝已由 test_tool_loop / test_tool_policy 覆盖。）
"""
from __future__ import annotations

import asyncio

import pytest

from packages.shared.types import UsageReport
from tests.helpers import create_task, wait_task


def _marker(workspace_id: str, name: str, path: str = "notes/out.txt") -> str:
    return f'[tool:{name} {{"workspace_id":"{workspace_id}","path":"{path}","content":"x"}}]'


def _shell_marker() -> str:
    """shell.run 必带 command 参数，让它走到 SHELL_DISABLED 拒绝（而非参数校验拒绝）。"""
    return '[tool:shell.run {"command":"echo hi"}]'


def _event_types(client, task_id: str) -> list[str]:
    items = client.get(f"/api/v1/tasks/{task_id}/timeline").json()["items"]
    return [item.get("type") for item in items]


# ---------------------------------------------------------------- 预算熔断


class _CostlyAdapter:
    """假 adapter：每次模型调用报 $0.05 成本（测试预算熔断，不产生真实费用）。"""

    adapter_type = "mock"
    model = "mock/costly"

    def __init__(self):
        self.calls = 0

    def prepare(self, instruction: str) -> None:
        self._instruction = instruction

    async def chat(self, messages, tools=None, tool_choice=None):
        self.calls += 1
        content = "[mock] costly done"
        return {
            "content": content, "tool_calls": [],
            "usage": UsageReport(
                model=self.model, prompt_tokens=100, completion_tokens=20,
                cost_usd=0.05, latency_ms=1,
            ),
            "model": self.model,
            "message": {"role": "assistant", "content": content},
        }

    async def close(self) -> None:
        return None


@pytest.fixture
def costly_adapter(monkeypatch):
    adapter = _CostlyAdapter()
    from packages.execution.adapter_factory import AdapterBundle

    def _fake_build(session, employee, mode):
        return AdapterBundle(
            adapter=adapter, mode=mode, model=_CostlyAdapter.model,
            connection_id=None, label="costly",
        )

    # executor 是 `from .adapter_factory import build_adapter`，必须打 executor 里的名字
    monkeypatch.setattr("packages.execution.executor.build_adapter", _fake_build)
    return adapter


def test_cost_budget_exceeded_pauses_task(write_client, seeded_team, tool_employee,
                                          seeded_workspace, tools_on, costly_adapter):
    """成本超预算：任务 paused + task.budget_exceeded + 可读 error，第一次调用后即停。"""
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="成本超预算",
        instruction=_marker(seeded_workspace["id"], "fs.read_file", "notes/a.txt") + " 读取文件",
        budget_usd=0.01,
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"paused"})
    assert detail["result"]["error"]["code"] == "BUDGET_EXCEEDED"
    assert "task.budget_exceeded" in _event_types(write_client, task["id"])
    assert costly_adapter.calls == 1


def test_token_budget_exceeded_pauses_task(write_client, seeded_team, tool_employee,
                                           seeded_workspace, tools_on):
    """Token 超上限（公司策略默认值）：任务 paused，不再继续调用。"""
    company_id = seeded_team["company"]["id"]
    resp = write_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"policy": {"default_task_budget_tokens": 5}},
    )
    assert resp.status_code == 200, resp.text
    task = create_task(
        write_client, company_id, tool_employee["id"], title="Token 超限",
        instruction=_marker(seeded_workspace["id"], "fs.read_file", "notes/a.txt") + " 读取文件",
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"paused"})
    assert detail["result"]["error"]["code"] == "BUDGET_EXCEEDED"
    assert "上限" in detail["result"]["error"]["message"]
    assert "task.budget_exceeded" in _event_types(write_client, task["id"])


def test_budget_ok_when_no_limit(write_client, seeded_team, tool_employee,
                                 seeded_workspace, tools_on):
    """没有任何预算限制时不熔断：任务正常完成。"""
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="无预算限制",
        instruction=_marker(seeded_workspace["id"], "fs.write_file", "notes/ok.txt") + " 写文件",
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    wait_task(write_client, task["id"], {"succeeded"})
    assert "task.budget_exceeded" not in _event_types(write_client, task["id"])


# ---------------------------------------------------------------- 连续拒绝


def test_consecutive_denials_pause_task(write_client, seeded_team, tool_employee,
                                        seeded_workspace, tools_on):
    """连续 3 次工具拒绝：任务 paused + task.tool_denied_limit，提示检查授权。"""
    company_id = seeded_team["company"]["id"]
    instruction = " ".join([
        _shell_marker(),
        _shell_marker(),
        _shell_marker(),
        "尝试三次被禁用的命令",
    ])
    task = create_task(
        write_client, company_id, tool_employee["id"], title="连续拒绝", instruction=instruction
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"paused"})
    assert detail["result"]["error"]["code"] == "TOOL_DENIED_LIMIT"
    assert "授权" in detail["result"]["error"]["message"]
    assert "task.tool_denied_limit" in _event_types(write_client, task["id"])
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    assert calls["total"] == 3
    assert all(item["status"] == "denied" for item in calls["items"])


def test_denial_counter_resets_after_success(write_client, seeded_team, tool_employee,
                                             seeded_workspace, tools_on):
    """拒绝→成功→拒绝：成功打断"连续"，不触发熔断。"""
    company_id = seeded_team["company"]["id"]
    instruction = " ".join([
        _shell_marker(),                                            # denied 1
        _marker(seeded_workspace["id"], "fs.write_file", "notes/reset_a.txt"),  # succeeded → 归零
        _shell_marker(),                                            # denied 1（重新计数）
        _marker(seeded_workspace["id"], "fs.write_file", "notes/reset_b.txt"),  # succeeded
        "间隔成功的混合调用",
    ])
    task = create_task(
        write_client, company_id, tool_employee["id"], title="拒绝被成功打断",
        instruction=instruction,
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"succeeded"})
    assert detail["state"] == "succeeded"
    calls = write_client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()
    statuses = [item["status"] for item in calls["items"]]
    assert statuses.count("denied") == 2 and statuses.count("succeeded") == 2


# ---------------------------------------------------------------- 全局关闭 / kill switch


def test_required_tools_with_global_off_fails_readably(write_client, seeded_team,
                                                       tool_employee, seeded_workspace):
    """全局 off + 步骤必需工具：任务可读地失败（TOOLS_DISABLED），而不是假成功。"""
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="必需工具但全局关闭",
        objective="验证全局关闭",
        context={"required_tools": ["fs.read_file"]},
        instruction="尝试工作",
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["result"]["error"]["code"] == "TOOLS_DISABLED"
    assert "全局工具执行已关闭" in detail["result"]["error"]["message"]


def test_kill_switch_via_api(write_client, seeded_team, tool_employee, tools_on):
    """kill switch：POST 后立即生效；必需工具的任务可读失败；恢复后开关状态正确。"""
    company_id = seeded_team["company"]["id"]
    try:
        state = write_client.get("/api/v1/system/tool-execution").json()
        assert state["enabled"] is True and state["kill_switch"] is False

        stopped = write_client.post(
            "/api/v1/system/tool-execution", json={"enabled": False},
        ).json()
        assert stopped["enabled"] is False and stopped["kill_switch"] is True

        task = create_task(
            write_client, company_id, tool_employee["id"], title="kill switch 停止",
            objective="验证紧急停止",
            context={"required_tools": ["fs.read_file"]},
            instruction="尝试工作",
        )
        write_client.post(f"/api/v1/tasks/{task['id']}/run")
        detail = wait_task(write_client, task["id"], {"failed"})
        assert detail["result"]["error"]["code"] == "TOOLS_DISABLED"
    finally:
        resumed = write_client.post(
            "/api/v1/system/tool-execution", json={"enabled": True},
        ).json()
        assert resumed["enabled"] is True and resumed["kill_switch"] is False


def test_kill_switch_denies_direct_invoke(write_client, seeded_team, tool_employee,
                                          seeded_workspace, tools_on):
    """kill switch 下工具调用一律拒绝（decide → TOOLS_DISABLED，消息可读）。"""
    from packages.execution.tool_loop import build_tool_context
    from packages.persistence import get_session
    from packages.persistence.models import Employee, Task
    from packages.tools.invoke import invoke_tool

    company_id = seeded_team["company"]["id"]
    write_client.post("/api/v1/system/tool-execution", json={"enabled": False})
    try:
        task = create_task(
            write_client, company_id, tool_employee["id"], title="直接调用",
            instruction="直接调用测试",
        )
        with get_session() as session:
            employee = session.get(Employee, tool_employee["id"])
            task_row = session.get(Task, task["id"])
            ctx = build_tool_context(
                session, owner_id="local", task=task_row, run=None,
                employee=employee, step_id="s1",
            )
            outcome = asyncio.run(invoke_tool(
                ctx, "fs.read_file",
                {"workspace_id": seeded_workspace["id"], "path": "notes/a.txt"},
            ))
        assert outcome.status == "denied"
        assert outcome.error_code == "TOOLS_DISABLED"
        assert "紧急停止" in (outcome.error_message or "")
    finally:
        write_client.post("/api/v1/system/tool-execution", json={"enabled": True})


# ---------------------------------------------------------------- 监控统计


def test_monitor_summary_has_m3e_fields(write_client, seeded_team, tool_employee,
                                        seeded_workspace, tools_on):
    """监控摘要包含：tool_execution 状态、工具统计、拒绝 Top N、预算使用率。"""
    company_id = seeded_team["company"]["id"]
    task = create_task(
        write_client, company_id, tool_employee["id"], title="被监控的任务",
        instruction=(
            _shell_marker() + " "
            + _marker(seeded_workspace["id"], "fs.write_file", "notes/monitor.txt") + " 混合调用"
        ),
    )
    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    wait_task(write_client, task["id"], {"succeeded"})
    # 进行中（草稿）且有预算的任务 → 进入预算监控列表
    budget_task = create_task(
        write_client, company_id, tool_employee["id"], title="预算观察",
        instruction="还没运行", budget_usd=1.0,
    )

    summary = write_client.get(f"/api/v1/monitor/summary?company_id={company_id}").json()
    assert summary["tool_execution"] == {"enabled": True}
    assert summary["tools"]["total"] >= 2
    assert summary["tools"]["by_status"].get("succeeded", 0) >= 1
    assert summary["tools"]["by_status"].get("denied", 0) >= 1
    codes = [item["code"] for item in summary["tools"]["denials_top"]]
    assert "SHELL_DISABLED" in codes
    watching = {item["task_id"]: item for item in summary["budgets"]["watching"]}
    assert budget_task["id"] in watching
    assert watching[budget_task["id"]]["budget_usd"] == 1.0

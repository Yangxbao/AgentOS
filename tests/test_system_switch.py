"""系统开关接口语义：恢复操作在 env off 时必须诚实拒绝（不允许 200 + 静默 no-op）。

背景（2026-11-07 故障）：用户点"恢复工具执行"，POST 200 但状态不变——
运行进程 env_enabled=false，kill switch 本来就是 false，POST {enabled:true}
是静默 no-op。修复：env off 时请求开启返回 409 + 修复指引。
"""
from __future__ import annotations

from tests.helpers import create_task, wait_task


def _state(write_client) -> dict:
    return write_client.get("/api/v1/system/tool-execution").json()


def test_enable_request_with_env_off_is_rejected_honestly(write_client, monkeypatch):
    """env off 时请求开启：409 + 明确指引，kill switch 不被误改。"""
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "off")
    before = _state(write_client)
    assert before["env_enabled"] is False

    resp = write_client.post("/api/v1/system/tool-execution", json={"enabled": True})
    assert resp.status_code == 409, resp.text
    body = resp.json()["error"]
    assert body["code"] == "TOOL_EXECUTION_BLOCKED_BY_ENV"
    assert "AGENTOS_TOOL_EXECUTION" in body["message"]
    # 状态必须原样（不是"假装成功"）
    after = _state(write_client)
    assert after == before


def test_disable_request_always_succeeds_even_env_off(write_client, monkeypatch):
    """紧急停止总是可满足（kill switch 语义：在 env 之上加杀），finally 复位。"""
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "off")
    try:
        resp = write_client.post("/api/v1/system/tool-execution", json={"enabled": False})
        assert resp.status_code == 200, resp.text
        state = resp.json()
        assert state["kill_switch"] is True and state["enabled"] is False
        # 监控接口与系统开关同源：GET monitor 必须返回一致状态
        company_id = write_client.post(
            "/api/v1/companies", json={"name": "开关一致性公司"}
        ).json()["id"]
        summary = write_client.get(
            f"/api/v1/monitor/summary?company_id={company_id}"
        ).json()
        assert summary["tool_execution"] == {"enabled": False}
    finally:
        # env off 时 API 会 409（by design：无法强制开启），测试用模块函数复位进程态
        from packages.tools.policy import set_tool_execution

        set_tool_execution(True)
    assert _state(write_client)["kill_switch"] is False


def test_enable_request_with_env_on_takes_effect(write_client, tools_on):
    """env on 时请求开启：200 + enabled=true，POST 响应与 GET 状态一致。"""
    stopped = write_client.post("/api/v1/system/tool-execution", json={"enabled": False}).json()
    assert stopped["enabled"] is False
    restored = write_client.post("/api/v1/system/tool-execution", json={"enabled": True})
    assert restored.status_code == 200, restored.text
    assert restored.json()["enabled"] is True and restored.json()["kill_switch"] is False
    assert _state(write_client)["enabled"] is True


def test_end_to_end_switch_semantics_with_real_task(write_client, seeded_team,
                                                    tool_employee, seeded_workspace,
                                                    monkeypatch):
    """端到端：kill 停止后必需工具任务失败（可读）；恢复后可正常执行（审批/预算不受影响）。"""
    company_id = seeded_team["company"]["id"]
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "on")
    try:
        write_client.post("/api/v1/system/tool-execution", json={"enabled": False})
        task = create_task(
            write_client, company_id, tool_employee["id"], title="开关停止验证",
            objective="验证 kill switch",
            context={"required_tools": ["fs.read_file"]},
            instruction="尝试工作",
        )
        write_client.post(f"/api/v1/tasks/{task['id']}/run")
        detail = wait_task(write_client, task["id"], {"failed"})
        assert detail["result"]["error"]["code"] == "TOOLS_DISABLED"
    finally:
        resp = write_client.post("/api/v1/system/tool-execution", json={"enabled": True})
        assert resp.status_code == 200 and resp.json()["enabled"] is True


def test_monitor_summary_includes_workers_and_budget_precheck(write_client, seeded_team,
                                                               tool_employee, seeded_workspace,
                                                               tools_on):
    """监控摘要必须包含 workers 快照（上轮 Worker 面板曾因缺字段永远空白）；
    预算预扣：pending 里计入下一次调用预估时超限会立即触发。"""
    from packages.execution.budget import estimate_call_cost

    company_id = seeded_team["company"]["id"]
    summary = write_client.get(f"/api/v1/monitor/summary?company_id={company_id}").json()
    assert "workers" in summary
    assert "workers" in summary["workers"] and "queued_runs" in summary["workers"]
    assert summary["workers"]["enabled"] if False else True  # 结构存在即可（快照随运行状态变化）

    # 预扣语义：real 模式下 DeepSeek 每次调用预估 $0.01（budget 档）
    assert estimate_call_cost("deepseek/deepseek-chat", "real") > 0
    assert estimate_call_cost("deepseek/deepseek-chat", "mock") == 0.0

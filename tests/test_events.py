"""统一事件流序列化测试（无网络）。"""
from packages.shared.types import AgentEvent, UsageReport


def test_event_serialization():
    usage = UsageReport(
        model="deepseek/deepseek-chat", prompt_tokens=10, completion_tokens=5, cost_usd=0.000001
    )
    event = AgentEvent(type="usage", usage=usage, payload=usage.to_dict())
    d = event.to_dict()
    assert d["type"] == "usage"
    assert d["usage"]["cost_usd"] == 0.000001
    assert "ts" in d


def test_cost_none_is_honest():
    """计价失败时 cost 必须是 None 而不是编造的数字。"""
    usage = UsageReport(model="unknown/model-x", prompt_tokens=1, completion_tokens=1, cost_usd=None)
    assert usage.to_dict()["cost_usd"] is None

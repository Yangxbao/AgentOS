"""供应商输出上限自愈：max_tokens 超限 BadRequest → 降到 1024 重试一次。"""
from __future__ import annotations

import pytest

from packages.model_gateway.gateway import chat as gateway_chat


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content, "tool_calls": None})()
        self.finish_reason = "stop"


class _FakeUsage:
    prompt_tokens = 1
    completion_tokens = 1
    total_tokens = 2
    cost = None


class _FakeResponse:
    choices = [_FakeChoice("ok")]
    usage = _FakeUsage()
    model = "fake"


@pytest.mark.asyncio
async def test_max_tokens_overlimit_downgrades_and_retries(monkeypatch):
    """第一次调用 max_tokens=4000 被供应商拒绝 → 自动降 1024 重试成功。"""
    calls: list[int] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs["max_tokens"])
        if kwargs["max_tokens"] > 1024:
            raise RuntimeError(
                "litellm.BadRequestError: OpenAIException - max_tokens参数非法：限制数值范围[1,1024]"
            )
        return _FakeResponse()

    monkeypatch.setattr("packages.model_gateway.gateway.litellm.acompletion", fake_acompletion)
    resp = await gateway_chat("fake/model", [{"role": "user", "content": "hi"}], max_tokens=4000)
    assert resp.content == "ok"
    assert calls == [4000, 1024]


@pytest.mark.asyncio
async def test_unrelated_error_not_masked(monkeypatch):
    """非 max_tokens 错误照常包装上抛（不吞错）。"""
    from packages.model_gateway import GatewayError

    async def fake_acompletion(**kwargs):
        raise RuntimeError("litellm.AuthenticationError: invalid api key")

    monkeypatch.setattr("packages.model_gateway.gateway.litellm.acompletion", fake_acompletion)
    with pytest.raises(GatewayError):
        await gateway_chat("fake/model", [{"role": "user", "content": "hi"}], max_tokens=100)


@pytest.mark.asyncio
async def test_downgrade_retry_failure_surfaces(monkeypatch):
    """降级后仍失败：错误正常上抛（不能无限重试）。"""
    from packages.model_gateway import GatewayError

    async def fake_acompletion(**kwargs):
        raise RuntimeError(f"max_tokens参数非法：限制数值范围[1,{kwargs['max_tokens']}]")

    monkeypatch.setattr("packages.model_gateway.gateway.litellm.acompletion", fake_acompletion)
    with pytest.raises(GatewayError):
        await gateway_chat("fake/model", [{"role": "user", "content": "hi"}], max_tokens=4000)

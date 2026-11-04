"""能力声明诚实性测试（无网络依赖）。"""
import pytest

from packages.agent_core import LiteLLMAdapter
from packages.agent_core.adapter import CapabilityNotSupported
from packages.shared.types import ExecutionHandle


def test_litellm_adapter_capabilities_honest():
    caps = LiteLLMAdapter(model="deepseek/deepseek-chat").get_capabilities()
    # API 型执行体不具备的能力必须明确为 False，不允许伪装
    assert caps.file_ops is False
    assert caps.approval_hook is False
    assert caps.session_resume is False
    assert caps.usage_report is True
    assert caps.streaming is True


@pytest.mark.asyncio
async def test_interrupt_raises_capability_not_supported():
    adapter = LiteLLMAdapter(model="deepseek/deepseek-chat")
    with pytest.raises(CapabilityNotSupported):
        await adapter.interrupt(ExecutionHandle(), "should raise")


def test_capability_set_serializable():
    caps = LiteLLMAdapter(model="m").get_capabilities().to_dict()
    assert len(caps) == 8
    assert all(isinstance(v, bool) for v in caps.values())

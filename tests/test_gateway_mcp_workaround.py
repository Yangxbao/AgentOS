"""网关 MCP 逃生门回归：带 tools 的调用必须携带 `_skip_mcp_handler=True`。

背景（2026-11-07 真实调用实验发现）：litellm 1.108.0 只要传 tools 就无条件 import 其
MCP 网关模块链，可选包 `mcp` 未安装时 ModuleNotFoundError，导致所有真实模型的工具调用
失败。网关用 litellm 官方 kwargs `_skip_mcp_handler` 跳过该路径（我们只用 OpenAI
function calling）。litellm 升级修复后本测试保证补丁仍被显式保留或有意移除。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from packages.model_gateway import gateway


def _fake_response(content: str = "ok"):
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(
        prompt_tokens=1, completion_tokens=1,
        get=lambda key, default=None: 0,
    )
    return SimpleNamespace(choices=[choice], usage=usage, model="mock/x")


@pytest.fixture
def capture(monkeypatch):
    captured: dict = {}

    async def _fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _fake_response()

    monkeypatch.setattr(gateway.litellm, "acompletion", _fake_acompletion)
    return captured


def test_tools_call_skips_mcp_handler(capture):
    """带 tools 时必须携带 _skip_mcp_handler=True（绕过 litellm 1.108.0 的 mcp 导入缺陷）。"""
    asyncio.run(gateway.chat(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {
            "name": "fs.read_file",
            "description": "read",
            "parameters": {"type": "object", "properties": {}},
        }}],
    ))
    assert capture["tools"], "tools 应被透传"
    assert capture["_skip_mcp_handler"] is True


def test_model_name_mapping_roundtrip():
    """模型侧名称映射：点号工具名双向转换（DeepSeek 拒绝带点的 function name）。"""
    from packages.tools.registry import from_model_name, model_name, model_schemas

    assert model_name("fs.list_dir") == "fs__list_dir"
    assert from_model_name("fs__list_dir") == "fs.list_dir"
    # mock 路径：模型直接返回真实名（指令 marker），仍可解析
    assert from_model_name("fs.list_dir") == "fs.list_dir"
    # schema 发给模型的名字必须匹配 OpenAI 兼容字符集
    schemas = model_schemas(["fs.list_dir", "fs.read_file"])
    for schema in schemas:
        name = schema["function"]["name"]
        assert "." not in name and len(name) <= 64, name


def test_plain_call_has_no_mcp_kwarg(capture):
    """无 tools 的普通调用不应携带该 kwarg（保持 M2 语义零变化）。"""
    asyncio.run(gateway.chat(
        "deepseek/deepseek-chat",
        [{"role": "user", "content": "hi"}],
    ))
    assert "_skip_mcp_handler" not in capture
    assert "tools" not in capture

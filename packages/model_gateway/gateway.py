"""LiteLLM 统一调用封装。

- 模型寻址使用 LiteLLM 的 <prefix>/<model> 约定（如 deepseek/deepseek-chat）
- 费用经 litellm.completion_cost 计算；计价失败降级为 cost=None，绝不伪造
- 密钥只从环境变量读取（litellm 原生机制），本模块不接触密钥内容
"""
from __future__ import annotations

import os

# 必须在 import litellm 之前设置：禁用远程价格表拉取（避免无外网/受限网络时启动重试等待），
# 使用包内本地备份价格表（litellm 官方机制 LITELLM_LOCAL_MODEL_COST_MAP）。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import time  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any, Optional  # noqa: E402

import litellm  # noqa: E402

from packages.shared.types import UsageReport


class GatewayError(Exception):
    """模型网关统一异常。message 中不含任何密钥信息。"""


@dataclass
class GatewayResponse:
    content: str
    model: str
    usage: UsageReport
    raw_finish_reason: str
    tool_calls: list[dict] | None = None
    raw_message: dict | None = None


def _extract_usage(response: Any, model: str, latency_ms: int) -> UsageReport:
    usage = getattr(response, "usage", None) or {}
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    cost: Optional[float]
    try:
        cost = litellm.completion_cost(completion_response=response)
        cost = round(float(cost), 8) if cost is not None else None
    except Exception:
        cost = None  # 降级：价格表未覆盖该模型时只记 token
    return UsageReport(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
    )


def _extract_tool_calls(message: Any) -> list[dict]:
    """把 LiteLLM 的 tool_calls 归一成纯 dict（OpenAI 兼容格式）。"""
    raw = getattr(message, "tool_calls", None) or []
    calls: list[dict] = []
    for item in raw:
        function = getattr(item, "function", None)
        name = getattr(function, "name", None) if function else None
        arguments = getattr(function, "arguments", "") if function else ""
        if not name:
            continue
        calls.append({
            "id": getattr(item, "id", "") or "",
            "type": "function",
            "function": {"name": name, "arguments": arguments or "{}"},
        })
    return calls


async def chat(
    model: str,
    messages: list[dict[str, Any]],
    *,
    fallbacks: Optional[list[str]] = None,
    timeout: float = 60.0,
    num_retries: int = 2,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[str] = None,
) -> GatewayResponse:
    """统一聊天调用。fallbacks 为备用模型列表（员工级主备模型机制的基础）。

    tools 走 OpenAI 兼容的 function calling；不传时行为与 M2 完全一致。
    """
    started = time.perf_counter()
    extra: dict[str, Any] = {}
    if tools:
        extra["tools"] = tools
        extra["tool_choice"] = tool_choice or "auto"
        # litellm 1.108.0 缺陷：只要传 tools 就会无条件 import 其 MCP 网关模块链，
        # 而可选包 `mcp` 未安装时直接 ModuleNotFoundError（连非 MCP 工具也被拦）。
        # `_skip_mcp_handler` 是 litellm 官方 kwargs 逃生门（main.py: kwargs.pop("_skip_mcp_handler")）；
        # 我们不使用 MCP 网关，全部工具走 OpenAI function calling。litellm 升级修复后可移除本参数。
        extra["_skip_mcp_handler"] = True
    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            fallbacks=fallbacks or [],
            timeout=timeout,
            num_retries=num_retries,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            **extra,
        )
    except Exception as exc:  # litellm 异常类型众多，统一包装；不记录请求体
        raise GatewayError(f"{type(exc).__name__}: {str(exc)[:300]}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    choice = response.choices[0]
    content = choice.message.content or ""
    return GatewayResponse(
        content=content,
        model=model,
        usage=_extract_usage(response, model, latency_ms),
        raw_finish_reason=str(getattr(choice, "finish_reason", "")),
        tool_calls=_extract_tool_calls(choice.message),
        raw_message={
            "role": "assistant",
            "content": content,
            "tool_calls": _extract_tool_calls(choice.message),
        },
    )

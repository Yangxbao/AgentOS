"""AgentAdapter 统一接口 + LiteLLM API 型参考实现。

设计文档：docs/architecture/AGENT_ADAPTER.md
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional, Protocol

from packages.model_gateway import GatewayError, chat
from packages.shared.types import (
    AgentEvent,
    AgentTask,
    CapabilitySet,
    ExecutionHandle,
    UsageReport,
)


class CapabilityNotSupported(Exception):
    """调用了执行体明确声明不支持的能力。"""


@dataclass
class HealthStatus:
    ok: bool
    detail: str = ""


class AgentAdapter(Protocol):
    """执行体统一接口。任务引擎对 API/CLI 差异透明。"""

    adapter_type: str

    async def connect(self) -> None: ...
    async def health_check(self) -> HealthStatus: ...
    def get_capabilities(self) -> CapabilitySet: ...
    async def execute(self, task: AgentTask, system_prompt: str = "") -> ExecutionHandle: ...
    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]: ...
    async def interrupt(self, handle: ExecutionHandle, reason: str) -> None: ...
    async def cancel(self, handle: ExecutionHandle) -> None: ...
    async def get_usage(self, handle: ExecutionHandle) -> Optional[UsageReport]: ...
    async def close(self) -> None: ...


class LiteLLMAdapter:
    """API 型 Adapter：经 LiteLLM 调用任意供应商。

    能力声明（与 AGENT_ADAPTER.md 矩阵一致，均为实测/文档支撑）：
    file_ops=False、approval_hook=False、session_resume=False —— 不伪装。
    """

    adapter_type = "api"

    def __init__(
        self,
        model: str,
        fallback_model: Optional[str] = None,
        timeout: float = 60.0,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_retries: int = 2,
        max_tokens: int = 2048,
    ):
        self.model = model
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self._handles: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        return None

    async def health_check(self) -> HealthStatus:
        try:
            await chat(
                self.model,
                [{"role": "user", "content": "ping，回复 ok 即可"}],
                timeout=min(15.0, self.timeout),
                max_tokens=8,
                api_key=self.api_key,
                base_url=self.base_url,
                num_retries=self.max_retries,
            )
            return HealthStatus(ok=True, detail=f"{self.model} 可达")
        except GatewayError as exc:
            return HealthStatus(ok=False, detail=str(exc)[:200])

    def get_capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            streaming=True,
            interruptible=False,
            structured_output=True,
            tool_calling=True,
            file_ops=False,
            approval_hook=False,
            session_resume=False,
            usage_report=True,
        )

    async def execute(self, task: AgentTask, system_prompt: str = "") -> ExecutionHandle:
        handle = ExecutionHandle(adapter_type=self.adapter_type)
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        user_content = task.instruction if not task.input else f"{task.instruction}\n\n{task.input}"
        messages.append({"role": "user", "content": user_content})
        self._handles[handle.id] = {"messages": messages, "task_id": task.task_id}
        return handle

    async def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        state = self._handles.get(handle.id)
        if state is None:
            yield AgentEvent(type="failed", payload={"error": "unknown handle"})
            return
        yield AgentEvent(type="started", payload={"model": self.model})
        try:
            resp = await chat(
                self.model,
                state["messages"],
                fallbacks=[self.fallback_model] if self.fallback_model else None,
                timeout=self.timeout,
                max_tokens=self.max_tokens,
                api_key=self.api_key,
                base_url=self.base_url,
                num_retries=self.max_retries,
            )
        except GatewayError as exc:
            yield AgentEvent(type="failed", payload={"error": str(exc)})
            return
        usage = resp.usage
        handle.external_ref = resp.model
        state["usage"] = usage
        yield AgentEvent(type="message", payload={"content": resp.content, "model": resp.model})
        yield AgentEvent(type="usage", usage=usage, payload=usage.to_dict())
        yield AgentEvent(type="completed", payload={"finish_reason": resp.raw_finish_reason})

    async def interrupt(self, handle: ExecutionHandle, reason: str) -> None:
        raise CapabilityNotSupported("LiteLLM API 调用不可中断，仅可取消（见能力声明）")

    async def cancel(self, handle: ExecutionHandle) -> None:
        self._handles.pop(handle.id, None)

    async def get_usage(self, handle: ExecutionHandle) -> Optional[UsageReport]:
        state = self._handles.get(handle.id)
        return state.get("usage") if state else None

    async def close(self) -> None:
        self._handles.clear()


async def collect_final(adapter: AgentAdapter, handle: ExecutionHandle) -> dict[str, Any]:
    """消费事件流直到 completed/failed，返回最终内容（便捷工具）。"""
    result: dict[str, Any] = {"content": "", "usage": None, "ok": False, "error": None}
    async for event in adapter.stream_events(handle):
        if event.type == "message":
            result["content"] += event.payload.get("content", "")
        elif event.type == "failed":
            result["error"] = event.payload.get("error")
        elif event.type == "completed":
            result["ok"] = True
    result["usage"] = await adapter.get_usage(handle)
    return result


# 让 asyncio 可被静态检查器识别为已用（预留给后续取消逻辑的 task 引用）
_ = asyncio

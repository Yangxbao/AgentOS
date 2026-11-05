"""确定性 Mock 执行体（M2）：用于无密钥/离线环境的完整链路验证。

诚实性：
- 不调用任何外部服务；
- 输出显式带 `[mock]` 前缀；
- usage 的 model 为 `mock/echo`、cost=0，落库时 `billable=False`；
- 支持故障注入标记（仅测试用，不会出现在真实模式）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional

from packages.agent_core.adapter import CapabilityNotSupported, HealthStatus
from packages.shared.types import (
    AgentEvent,
    AgentTask,
    CapabilitySet,
    ExecutionHandle,
    UsageReport,
)

MARK_FAIL = "[fail]"
MARK_SLOW = "[slow:"


class MockAdapter:
    adapter_type = "mock"
    model = "mock/echo"

    def __init__(self, label: str = "mock", delay_ms: int = 0):
        self.label = label
        self.delay_ms = delay_ms
        self._handles: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        return None

    async def health_check(self) -> HealthStatus:
        return HealthStatus(ok=True, detail="mock adapter（未调用外部服务）")

    def get_capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            streaming=True, interruptible=False, structured_output=True,
            tool_calling=True, file_ops=False, approval_hook=False,
            session_resume=False, usage_report=True,
        )

    async def execute(self, task: AgentTask, system_prompt: str = "") -> ExecutionHandle:
        handle = ExecutionHandle(adapter_type=self.adapter_type, external_ref="mock")
        self._handles[handle.id] = {
            "instruction": task.instruction,
            "input": task.input,
            "system_prompt": system_prompt,
            "started": time.perf_counter(),
        }
        return handle

    async def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        state = self._handles.get(handle.id)
        if state is None:
            yield AgentEvent(type="failed", payload={"error": "unknown handle"})
            return

        yield AgentEvent(type="started", payload={"model": self.model, "mode": "mock"})
        delay_ms = self.delay_ms
        marker = state["instruction"].find(MARK_SLOW)
        if marker >= 0:
            try:
                tail = state["instruction"][marker + len(MARK_SLOW):]
                delay_ms = max(delay_ms, int(tail.split("]", 1)[0]))
            except (ValueError, IndexError):
                delay_ms = max(delay_ms, 50)
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000.0)

        if MARK_FAIL in state["instruction"]:
            await asyncio.sleep(0)
            yield AgentEvent(type="failed", payload={"error": "mock: injected failure"})
            return

        text = (
            f"[mock] {self.label} 完成："
            f"{state['instruction'].strip().splitlines()[0][:80]}"
        )
        if state["input"]:
            text += f"\n（已接收上游上下文 {len(state['input'])} 字）"
        elapsed = int((time.perf_counter() - state["started"]) * 1000)
        usage = UsageReport(
            model=self.model,
            prompt_tokens=max(1, (len(state["system_prompt"]) + len(state["instruction"])) // 4),
            completion_tokens=max(1, len(text) // 4),
            cost_usd=0.0,
            latency_ms=elapsed,
        )
        state["usage"] = usage
        yield AgentEvent(type="message", payload={"content": text, "model": self.model})
        yield AgentEvent(type="usage", usage=usage, payload=usage.to_dict())
        yield AgentEvent(type="completed", payload={"finish_reason": "mock"})

    async def interrupt(self, handle: ExecutionHandle, reason: str) -> None:
        raise CapabilityNotSupported("Mock 执行体不支持中断")

    async def cancel(self, handle: ExecutionHandle) -> None:
        self._handles.pop(handle.id, None)

    async def get_usage(self, handle: ExecutionHandle) -> Optional[UsageReport]:
        state = self._handles.get(handle.id)
        return state.get("usage") if state else None

    async def close(self) -> None:
        self._handles.clear()

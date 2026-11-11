"""AgentOS 跨域共享类型。

设计来源：docs/architecture/AGENT_ADAPTER.md（能力声明矩阵、统一事件流）。
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class CapabilitySet:
    """执行体能力声明。不支持的能力必须为 False，不允许伪装。"""

    streaming: bool = False
    interruptible: bool = False
    structured_output: bool = False
    tool_calling: bool = False
    file_ops: bool = False
    approval_hook: bool = False
    session_resume: bool = False
    usage_report: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass
class UsageReport:
    """单次执行的计量。cost 计算失败时 cost_usd=None（降级策略）。"""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Optional[float] = None
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentEvent:
    """统一事件流事件（借鉴 codex exec --json 的 JSONL 范式）。"""

    type: str  # started|message|reasoning|tool_call|approval_required|usage|completed|failed|cancelled
    payload: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=utcnow)
    usage: Optional[UsageReport] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        if self.usage:
            d["usage"] = self.usage.to_dict()
        return d


@dataclass
class AgentTask:
    """派发给执行体的任务单元。"""

    instruction: str
    input: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=new_id)
    # 视觉链路：随首条 user 消息发给模型的图片 data URI（仅视觉模型可用；空=纯文本）
    images: list[str] = field(default_factory=list)


@dataclass
class ExecutionHandle:
    """一次执行的句柄，供流式/中断/取消/计量引用。"""

    id: str = field(default_factory=new_id)
    adapter_type: str = "api"
    external_ref: Optional[str] = None  # CLI session id / 请求 id

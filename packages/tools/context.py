"""工具调用上下文与结果对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from packages.persistence.models import Company, Employee, Task, TaskRun


@dataclass
class ToolContext:
    """一次工具调用需要的全部上下文（由执行器/API 构造，handler 只读）。"""

    session: Session
    owner_id: str
    company: Company
    employee: Employee
    task: Task | None = None
    run: TaskRun | None = None
    step_id: str = ""
    call_index: int = 0
    request_id: str = "-"
    # 五层权限输入：公司工具策略 + 员工有效权限（由调用方一次算好，避免每层重查）
    tool_policy: dict = field(default_factory=dict)
    permissions: dict = field(default_factory=dict)
    # 人工审批通过后置 True，且指向同一条 tool_call
    approved: bool = False
    tool_call_id: str | None = None
    # 已存在的幂等记录（恢复/重试时复用）
    reuse_output: dict | None = None


@dataclass
class ToolOutcome:
    status: str  # succeeded|denied|failed|timeout|awaiting_approval
    tool_call_id: str
    output: dict = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    requires_approval: bool = False
    approval_id: str | None = None
    truncated: bool = False
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"

    @property
    def suspended(self) -> bool:
        return self.status == "awaiting_approval"

    def to_message(self) -> str:
        """回灌模型的内容：始终标记为不可信数据。"""
        import json

        payload: dict[str, Any] = {
            "tool": self.output.get("tool") or "",
            "status": self.status,
        }
        if self.ok:
            payload["data"] = self.output.get("data")
            if self.truncated:
                payload["truncated"] = True
        else:
            payload["error"] = {"code": self.error_code, "message": self.error_message}
        return (
            "<untrusted_tool_result>\n"
            + json.dumps(payload, ensure_ascii=False)[:20000]
            + "\n</untrusted_tool_result>"
        )

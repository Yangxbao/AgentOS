"""任务状态机（M2）：唯一权威迁移表。

原则：
- 状态由后端裁决，AI 输出不直接改状态；
- 非法迁移统一 409 TASK_ILLEGAL_TRANSITION，并回传允许的目标状态；
- M0 遗留状态只读映射，不迁移历史数据。
"""
from __future__ import annotations

from packages.shared.errors import DomainError

TASK_STATES = {
    "draft", "pending", "queued", "running", "paused", "awaiting_approval",
    "rework_required", "succeeded", "failed", "cancelled", "skipped",
    # M0 遗留
    "review_passed", "in_review",
}

TRANSITIONS: dict[str, set[str]] = {
    "draft": {"queued", "cancelled"},
    "pending": {"running", "cancelled", "skipped"},  # 子任务等待父任务调度
    "queued": {"running", "paused", "cancelled"},
    "running": {"succeeded", "failed", "cancelled", "paused", "awaiting_approval"},
    "paused": {"queued", "cancelled", "rework_required"},
    "awaiting_approval": {"queued", "rework_required", "cancelled"},
    "rework_required": {"queued", "cancelled"},
    "failed": {"queued", "cancelled"},
    "succeeded": set(),
    "cancelled": set(),
    "skipped": set(),
    # 遗留状态：只允许取消/归档，不参与新流程
    "review_passed": set(),
    "in_review": {"cancelled"},
}

TERMINAL_STATES = {"succeeded", "cancelled", "skipped", "review_passed"}
EDITABLE_STATES = {"draft"}
RESUMABLE_STATES = {"paused", "rework_required"}
RETRYABLE_STATES = {"failed", "cancelled"}
RUNNABLE_STATES = {"draft", "paused", "rework_required", "failed"}

# 遗留状态在 UI/聚合里的等价语义
LEGACY_EQUIVALENT = {"review_passed": "succeeded", "in_review": "awaiting_approval"}


def allowed_targets(state: str) -> list[str]:
    return sorted(TRANSITIONS.get(state, set()))


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def ensure_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise DomainError(
            "TASK_ILLEGAL_TRANSITION",
            f"任务状态不允许从 {current} 变为 {target}",
            409,
            {"from": current, "to": target, "allowed": allowed_targets(current)},
        )


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES

"""领域异常：与 Web 框架解耦，由 apps/api/errors.py 统一翻译为错误包络。

code 命名遵循 M1_PLAN_HANDOFF.md §7.1：
BR_*（业务规则）、VALIDATION_ERROR、CONFLICT_STALE 等。
"""
from __future__ import annotations


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        detail: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}

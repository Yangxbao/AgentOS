"""B5 权限/派工请求模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PermissionOverrideRequest(BaseModel):
    overrides: dict[str, Any]


class AssignmentRequest(BaseModel):
    required_capabilities: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    budget_usd: float | None = None
    prefer_department_id: str | None = None
    exclude_employee_ids: list[str] = Field(default_factory=list)
    selected_employee_id: str | None = None
    notes: str = ""

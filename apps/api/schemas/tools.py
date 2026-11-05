"""工作区 / 工具策略 / 工具调用的请求与响应模型（M3-A）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    root_path: str | None = Field(default=None, max_length=512)
    mode: str = Field(default="read_write", pattern="^(read_only|read_write)$")
    description: str = Field(default="", max_length=2000)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    mode: str | None = Field(default=None, pattern="^(read_only|read_write)$")


class GrantRequest(BaseModel):
    employee_id: str = Field(min_length=1, max_length=32)
    access: str = Field(default="read", pattern="^(read|write)$")


class GrantOut(BaseModel):
    employee_id: str
    employee_name: str
    access: str
    granted_by: str
    granted_at: str | None = None


class WorkspaceOut(BaseModel):
    id: str
    company_id: str
    name: str
    slug: str
    root_path: str
    mode: str
    status: str
    description: str
    created_by: str
    created_at: str | None = None
    updated_at: str | None = None
    grants: list[GrantOut] = Field(default_factory=list)


class ToolPolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    categories: dict[str, bool] | None = None
    allowed_tools: list[str] | None = None
    network_domains: list[str] | None = None
    allow_http_write: bool | None = None
    auto_execute_max_risk: str | None = None
    max_risk_level: str | None = None
    max_tool_calls_per_step: int | None = None
    approval_required_tools: list[str] | None = None


class ToolPolicyOut(BaseModel):
    global_enabled: bool
    policy: dict[str, Any]
    shell_enabled: bool = False


class ToolCallOut(BaseModel):
    id: str
    task_id: str | None = None
    task_run_id: str | None = None
    employee_id: str | None = None
    employee_name: str | None = None
    step_id: str
    call_index: int
    tool_name: str
    category: str
    risk_level: str
    status: str
    args_summary: dict
    resolved_path: str
    output_summary: dict
    output_bytes: int
    truncated: bool
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int
    approval_id: str | None = None
    approval_status: str | None = None
    created_at: str | None = None
    ended_at: str | None = None

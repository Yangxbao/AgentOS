"""M2 任务/审批请求模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = ""
    instruction: str = ""
    deliverable: str = ""
    assignee_employee_id: str
    reviewer_employee_id: str | None = None
    department_id: str | None = None
    priority: str = "normal"
    risk_level: str = "low"
    due_at: str | None = None
    approval_required: bool = False
    approval_stage: str = "before_run"
    budget_usd: float | None = Field(default=None, ge=0)
    execution_mode: str = "auto"
    context: dict[str, Any] = Field(default_factory=dict)
    max_rework: int = Field(default=3, ge=0, le=10)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = None
    instruction: str | None = None
    deliverable: str | None = None
    priority: str | None = None
    risk_level: str | None = None
    due_at: str | None = None
    approval_required: bool | None = None
    approval_stage: str | None = None
    budget_usd: float | None = Field(default=None, ge=0)
    execution_mode: str | None = None
    context: dict[str, Any] | None = None
    assignee_employee_id: str | None = None
    department_id: str | None = None
    reviewer_employee_id: str | None = None
    max_rework: int | None = Field(default=None, ge=0, le=10)
    expected_version: int | None = None


class PlanStepInput(BaseModel):
    id: str | None = None
    title: str = ""
    employee_id: str | None = None
    instruction: str = Field(min_length=1)
    deliverable: str = ""
    depends_on: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class TaskPlanInput(BaseModel):
    steps: list[PlanStepInput] = Field(default_factory=list, max_length=20)
    max_parallel: int = Field(default=4, ge=1, le=8)


class DecomposeRequest(BaseModel):
    max_steps: int = Field(default=4, ge=2, le=6)
    manager_employee_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str
    comment: str = ""
    rewind_step_id: str | None = None

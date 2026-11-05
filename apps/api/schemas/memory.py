"""记忆接口模型（M3-C）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    scope: str = Field(default="employee")
    employee_id: str | None = None
    project_task_id: str | None = None
    kind: str = Field(default="note")
    title: str = Field(default="", max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=8)


class MemoryUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content: str | None = Field(default=None, max_length=20000)
    kind: str | None = None
    tags: list[str] | None = Field(default=None, max_length=8)


class MemoryPromote(BaseModel):
    to_scope: str  # project | company


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=400)
    company_id: str | None = None
    scope: str | None = None
    employee_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)

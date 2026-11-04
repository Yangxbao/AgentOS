"""B2 组织域请求/响应模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    policy: dict[str, Any] | None = None


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    policy: dict[str, Any] | None = None
    expected_updated_at: str | None = None


class CompanyOut(BaseModel):
    id: str
    name: str
    description: str
    policy: dict[str, Any]
    status: str
    created_at: str | None
    updated_at: str | None


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: str | None = None
    code: str = ""
    description: str = ""
    sort_order: int = 0


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: str | None = None
    code: str | None = None
    description: str | None = None
    sort_order: int | None = None
    expected_updated_at: str | None = None


class DepartmentMove(BaseModel):
    new_parent_id: str | None = None
    new_index: int = 0


class DepartmentOut(BaseModel):
    id: str
    company_id: str
    parent_id: str | None
    name: str
    code: str
    description: str
    sort_order: int
    depth: int
    created_at: str | None
    updated_at: str | None


class PositionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    department_id: str | None = None
    level: str = ""
    is_managerial: bool = False
    can_review: bool = False
    review_capability_tags: list[str] = Field(default_factory=list)
    responsibilities: str = ""
    default_permissions: dict[str, Any] = Field(default_factory=dict)


class PositionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    department_id: str | None = None
    level: str | None = None
    is_managerial: bool | None = None
    can_review: bool | None = None
    review_capability_tags: list[str] | None = None
    responsibilities: str | None = None
    default_permissions: dict[str, Any] | None = None
    expected_updated_at: str | None = None


class PositionOut(BaseModel):
    id: str
    company_id: str
    department_id: str | None
    name: str
    level: str
    is_managerial: bool
    can_review: bool
    review_capability_tags: list[str]
    responsibilities: str
    default_permissions: dict[str, Any]
    created_at: str | None
    updated_at: str | None

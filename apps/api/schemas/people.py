"""B3 员工与模型连接请求模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EmployeePositionInput(BaseModel):
    position_id: str
    is_primary: bool = False
    department_id: str | None = None


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    primary_model_id: str
    fallback_model_id: str | None = None
    department_id: str | None = None
    title: str = ""
    avatar: str = ""
    bio: str = ""
    personality: str = ""
    reports_to: str | None = None
    adapter_type: str = "api"
    cli_profile: dict[str, Any] | None = None
    tools_allowed: list[str] = Field(default_factory=list)
    permission_profile: dict[str, Any] = Field(default_factory=dict)
    positions: list[EmployeePositionInput] = Field(default_factory=list)


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    title: str | None = None
    avatar: str | None = None
    bio: str | None = None
    personality: str | None = None
    department_id: str | None = None
    reports_to: str | None = None
    tools_allowed: list[str] | None = None
    permission_profile: dict[str, Any] | None = None
    positions: list[EmployeePositionInput] | None = None
    expected_updated_at: str | None = None


class ModelBindingUpdate(BaseModel):
    primary_model_id: str
    fallback_model_id: str | None = None
    reason: str = ""


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str
    model: str = ""
    api_key_ref: str
    base_url: str | None = None
    timeout_s: int = Field(default=60, ge=1, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)
    model_list_source: str = "static"


class ConnectionUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    api_key_ref: str | None = None
    base_url: str | None = None
    timeout_s: int | None = Field(default=None, ge=1, le=600)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    enabled: bool | None = None
    expected_updated_at: str | None = None

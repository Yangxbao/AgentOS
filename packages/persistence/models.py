"""M0 子集模型：task / task_run / agent_run / task_event / usage_record。

完整设计见 docs/architecture/DATABASE_DESIGN.md。
约定：全部通用类型，双后端兼容；所有表带 owner_id（多租户预留）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    title: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text, default="")
    # 状态机唯一权威字段；AI 自称"完成"不改变此字段
    state: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    rework_count: Mapped[int] = mapped_column(Integer, default=0)
    max_rework: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TaskRun(Base):
    """一次执行 = 一条记录，历史不覆盖。"""

    __tablename__ = "task_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)
    run_no: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    state: Mapped[str] = mapped_column(String(16), default="running")  # running|succeeded|failed|cancelled
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentRun(Base):
    """某员工在一次 task_run 中的执行单元。"""

    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_run.id"), index=True)
    employee_key: Mapped[str] = mapped_column(String(64))  # M0 用字符串键，M1 换 employee 表 FK
    role: Mapped[str] = mapped_column(String(64), default="")
    adapter_type: Mapped[str] = mapped_column(String(16), default="api")
    model: Mapped[str] = mapped_column(String(128), default="")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TaskEvent(Base):
    """事件流（与审计日志分离，借鉴 HALF TaskEvent 设计）。"""

    __tablename__ = "task_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)
    task_run_id: Mapped[str | None] = mapped_column(ForeignKey("task_run.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class UsageRecord(Base):
    __tablename__ = "usage_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_run.id"), index=True)
    employee_key: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # 计价失败记 NULL
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

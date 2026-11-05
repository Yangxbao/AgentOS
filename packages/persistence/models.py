"""M0 子集模型：task / task_run / agent_run / task_event / usage_record。

完整设计见 docs/architecture/DATABASE_DESIGN.md。
约定：全部通用类型，双后端兼容；所有表带 owner_id（多租户预留）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Task(Base):
    """任务/子任务统一实体（M2）。

    `state` 是唯一权威状态；M0 遗留任务 company_id 为 NULL，不回填、不改状态。
    """

    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    title: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text, default="")
    # 状态机唯一权威字段；AI 自称"完成"不改变此字段
    state: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    rework_count: Mapped[int] = mapped_column(Integer, default=0)
    max_rework: Mapped[int] = mapped_column(Integer, default=3)

    company_id: Mapped[str | None] = mapped_column(ForeignKey("company.id"), nullable=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(ForeignKey("task.id"), nullable=True)
    root_task_id: Mapped[str | None] = mapped_column(ForeignKey("task.id"), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    assignee_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employee.id"), nullable=True
    )
    reviewer_employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employee.id"), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deliverable: Mapped[str] = mapped_column(Text, default="")
    instruction: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_stage: Mapped[str] = mapped_column(String(16), default="before_run")
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(16), default="auto")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(64), default="local")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_task_company_state", "company_id", "state"),
        Index("ix_task_assignee_state", "assignee_employee_id", "state"),
        Index("ix_task_parent", "parent_task_id"),
    )


class TaskRun(Base):
    """一次执行 = 一条记录，历史不覆盖。"""

    __tablename__ = "task_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)
    run_no: Mapped[int] = mapped_column(Integer, default=1)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    # queued|running|succeeded|failed|cancelled|paused|awaiting_approval|interrupted
    state: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="real")
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resumed_from_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        # 防重复执行：同一任务同时最多一条活跃 run（SQLite/PostgreSQL 部分索引）
        Index(
            "uq_task_run_active",
            "task_id",
            unique=True,
            sqlite_where=text("state IN ('queued','running')"),
            postgresql_where=text("state IN ('queued','running')"),
        ),
    )


class AgentRun(Base):
    """某员工在一次 task_run 中的一个执行单元（M2：按 step 拆分）。"""

    __tablename__ = "agent_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_run.id"), index=True)
    # M0 用字符串键；B1 起新增 employee_id 双写过渡（M2 切换为主引用）
    employee_key: Mapped[str] = mapped_column(String(64))
    employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(64), default="")
    adapter_type: Mapped[str] = mapped_column(String(16), default="api")
    model: Mapped[str] = mapped_column(String(128), default="")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(16), default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    step_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_connection_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


class Company(Base):
    """公司：组织根节点，承载策略（M1 B2）。"""

    __tablename__ = "company"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_company_owner_name"),
    )


class Department(Base):
    """部门树（parent_id 自引用），深度 0 起，最大 8 层。"""

    __tablename__ = "department"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_department_company_name"),
    )


class Position(Base):
    """岗位模板：职责、默认权限、审查资格（can_review，B5 审查人推导依赖）。"""

    __tablename__ = "position"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(24), default="")
    is_managerial: Mapped[bool] = mapped_column(Boolean, default=False)
    can_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_capability_tags: Mapped[list] = mapped_column(JSON, default=list)
    responsibilities: Mapped[str] = mapped_column(Text, default="")
    default_permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_position_company_name"),
    )


class ModelConnection(Base):
    """模型连接（B3）：只存凭据引用，绝不存明文密钥。"""

    __tablename__ = "model_connection"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    api_key_ref: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timeout_s: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    model_list_source: Mapped[str] = mapped_column(String(16), default="static")
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_health_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("company_id", "provider", "model", "base_url", name="uq_model_company_provider_model_url"),
    )


class Employee(Base):
    """AI 员工身份：与模型解耦，只存主/备模型引用。"""

    __tablename__ = "employee"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), index=True)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    avatar: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|disabled|archived
    reports_to: Mapped[str | None] = mapped_column(ForeignKey("employee.id"), nullable=True, index=True)
    primary_model_id: Mapped[str] = mapped_column(ForeignKey("model_connection.id"))
    fallback_model_id: Mapped[str | None] = mapped_column(ForeignKey("model_connection.id"), nullable=True)
    adapter_type: Mapped[str] = mapped_column(String(16), default="api")
    cli_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tools_allowed: Mapped[list] = mapped_column(JSON, default=list)
    permission_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    capabilities_declared: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_active_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        # 软删除下同公司名称唯一：只约束未删除行（SQLite/PostgreSQL 均支持部分索引）
        Index(
            "uq_employee_company_name_active",
            "company_id",
            "name",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_employee_company_department", "company_id", "department_id"),
    )


class EmployeePosition(Base):
    """员工-岗位（1 主 + n 兼）。"""

    __tablename__ = "employee_position"

    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id"), primary_key=True)
    position_id: Mapped[str] = mapped_column(ForeignKey("position.id"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ModelSwitchLog(Base):
    """模型切换审计（只增不改）。"""

    __tablename__ = "model_switch_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id"), index=True)
    from_model_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_model_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    slot: Mapped[str] = mapped_column(String(16), default="primary")
    actor_type: Mapped[str] = mapped_column(String(16), default="user")
    actor_id: Mapped[str] = mapped_column(String(64), default="local")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PromptRevision(Base):
    """提示词版本（B4）：文件不可变，DB 只存指针 + 哈希。"""

    __tablename__ = "prompt_revision"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employee.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="local")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("employee_id", "version", name="uq_prompt_employee_version"),
    )


class AssignmentDecision(Base):
    """派工决策（只增不改）：候选、分数、理由、审查人。"""

    __tablename__ = "assignment_decision"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("company.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(64), default="local")
    requirement: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    selected_employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer_employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    data_quality: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(16), default="m1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    """审计日志：只增不改，无更新/删除路由。"""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    actor_type: Mapped[str] = mapped_column(String(16), default="user")
    actor_id: Mapped[str] = mapped_column(String(64), default="local")
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str] = mapped_column(String(32), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TaskApproval(Base):
    """人工审批（只增；决策后不再变更，重复决策被拒）。"""

    __tablename__ = "task_approval"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)
    task_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gate: Mapped[str] = mapped_column(String(16), default="before_run")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(64), default="local")
    reviewer_employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    rewind_step_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentHandoff(Base):
    """Agent 之间的上下文交接记录（只增）。"""

    __tablename__ = "agent_handoff"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local", index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)
    task_run_id: Mapped[str] = mapped_column(ForeignKey("task_run.id"), index=True)
    from_agent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_agent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step_id: Mapped[str] = mapped_column(String(32), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(String(64), default="local")
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_run.id"), index=True)
    employee_key: Mapped[str] = mapped_column(String(64), index=True)
    employee_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # 计价失败记 NULL
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    billable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

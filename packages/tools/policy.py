"""五层工具权限决策（M3-A）。

层 1 公司策略（全局开关 + 类别 + 工具白名单 + 风险上限 + 域名白名单）
层 2 岗位默认（M1 `position.default_permissions`，经 effective 合并）
层 3 员工覆盖（M1 `employee.permission_profile`，只能收窄）
层 4 员工工具白名单（`employee.tools_allowed`，空 = 不允许任何工具）
层 5 工作区授权（`employee_workspace_grant`，目录级 read/write）

任一层不允许 → 拒绝，错误码稳定可判定。
默认姿态：全局开关关闭（AGENTOS_TOOL_EXECUTION=off）、网络类别关闭、删除工具关闭、Shell 永久禁用。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.persistence.models import Company, EmployeeWorkspaceGrant, Workspace
from packages.shared.errors import DomainError

from .context import ToolContext
from .http import host_allowed
from .paths import PathDenied, safe_resolve
from .registry import REGISTRY, ToolSpec, risk_rank
from .workspaces import resolve_grant

DEFAULT_TOOL_POLICY: dict = {
    "enabled": True,
    "categories": {"file_read": True, "file_write": True, "network": False, "shell": False, "memory": False},
    "allowed_tools": [
        name for name, spec in REGISTRY.items() if spec.enabled and spec.enabled_by_default
    ],
    "network_domains": [],
    "allow_http_write": False,
    # 允许自动执行的最高风险：超过则需要审批；超过 max_risk_level 直接拒绝
    "auto_execute_max_risk": "medium",
    "max_risk_level": "high",
    "max_tool_calls_per_step": 8,
    "approval_required_tools": [],
}


# M3-E kill switch：进程级紧急停止开关（API 可写，环境变量只决定初始值）。
# 设计取舍：内存态，进程重启后回到 AGENTOS_TOOL_EXECUTION 决定的初始值——
# 紧急制动要的是"立即生效 + 审计留痕"，持久关闭仍应通过环境变量表达。
_KILL_SWITCH = False


def set_tool_execution(enabled: bool) -> None:
    """设置进程级工具执行紧急开关：enabled=False 时立即拒绝一切工具调用。"""
    global _KILL_SWITCH
    _KILL_SWITCH = not bool(enabled)


def tool_execution_state() -> dict:
    """当前全局工具执行的完整状态（env 初始值 + 运行时紧急开关）。"""
    env_enabled = (
        os.environ.get("AGENTOS_TOOL_EXECUTION", "off").strip().lower()
        in {"on", "1", "true", "yes"}
    )
    return {
        "env_enabled": env_enabled,
        "kill_switch": _KILL_SWITCH,
        "enabled": env_enabled and not _KILL_SWITCH,
    }


def global_tools_enabled() -> bool:
    """全局工具执行开关：默认关闭，必须显式 AGENTOS_TOOL_EXECUTION=on，且未被 kill switch 停用。"""
    if _KILL_SWITCH:
        return False
    return os.environ.get("AGENTOS_TOOL_EXECUTION", "off").strip().lower() in {"on", "1", "true", "yes"}


def effective_tool_policy(company: Company) -> dict:
    raw = (company.policy or {}).get("tools") or {}
    policy = {**DEFAULT_TOOL_POLICY}
    categories = {**DEFAULT_TOOL_POLICY["categories"], **(raw.get("categories") or {})}
    policy.update({key: value for key, value in raw.items() if key != "categories"})
    policy["categories"] = categories
    policy["allowed_tools"] = list(policy.get("allowed_tools") or [])
    policy["network_domains"] = [str(item).lower() for item in (policy.get("network_domains") or [])]
    policy["approval_required_tools"] = list(policy.get("approval_required_tools") or [])
    return policy


def validate_policy_patch(patch: dict) -> dict:
    """公司策略修改的校验：只允许已知键，值域受限。"""
    allowed = set(DEFAULT_TOOL_POLICY)
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise DomainError("VALIDATION_ERROR", f"未知策略项：{', '.join(unknown)}", 422)
    if "enabled" in patch and not isinstance(patch["enabled"], bool):
        raise DomainError("VALIDATION_ERROR", "enabled 必须是布尔值", 422)
    if "allow_http_write" in patch and not isinstance(patch["allow_http_write"], bool):
        raise DomainError("VALIDATION_ERROR", "allow_http_write 必须是布尔值", 422)
    if "categories" in patch:
        categories = patch["categories"]
        if not isinstance(categories, dict):
            raise DomainError("VALIDATION_ERROR", "categories 必须是对象", 422)
        bad = sorted(set(categories) - {"file_read", "file_write", "network", "shell", "memory"})
        if bad:
            raise DomainError("VALIDATION_ERROR", f"未知类别：{', '.join(bad)}", 422)
        for key, value in categories.items():
            if not isinstance(value, bool):
                raise DomainError("VALIDATION_ERROR", f"categories.{key} 必须是布尔值", 422)
        if categories.get("shell") is True:
            raise DomainError(
                "SHELL_DISABLED", "M3 不允许开启 Shell 类别（无执行路径）", 403
            )
    if "allowed_tools" in patch:
        tools = patch["allowed_tools"]
        if not isinstance(tools, list) or any(not isinstance(item, str) for item in tools):
            raise DomainError("VALIDATION_ERROR", "allowed_tools 必须是字符串数组", 422)
        unknown_tools = sorted(set(tools) - set(REGISTRY))
        if unknown_tools:
            raise DomainError(
                "VALIDATION_ERROR", f"未注册的工具：{', '.join(unknown_tools)}", 422
            )
        if "shell.run" in tools:
            raise DomainError("SHELL_DISABLED", "shell.run 不能被加入白名单", 403)
    if "network_domains" in patch:
        domains = patch["network_domains"]
        if not isinstance(domains, list) or any(not isinstance(item, str) for item in domains):
            raise DomainError("VALIDATION_ERROR", "network_domains 必须是字符串数组", 422)
        cleaned = []
        for item in domains:
            value = item.strip().lower()
            if not value:
                continue
            if "://" in value or "/" in value:
                raise DomainError(
                    "VALIDATION_ERROR", f"域名白名单只接受 host[:port]：{item}", 422
                )
            cleaned.append(value)
        patch["network_domains"] = cleaned
    for key in ("max_tool_calls_per_step",):
        if key in patch:
            value = patch[key]
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 50:
                raise DomainError("VALIDATION_ERROR", f"{key} 必须是 1..50 的整数", 422)
    for key in ("auto_execute_max_risk", "max_risk_level"):
        if key in patch and patch[key] not in ("low", "medium", "high", "critical"):
            raise DomainError("VALIDATION_ERROR", f"{key} 值非法", 422)
    if "approval_required_tools" in patch:
        tools = patch["approval_required_tools"]
        if not isinstance(tools, list):
            raise DomainError("VALIDATION_ERROR", "approval_required_tools 必须是数组", 422)
    if (
        "auto_execute_max_risk" in patch
        and "max_risk_level" in patch
        and risk_rank(patch["auto_execute_max_risk"]) > risk_rank(patch["max_risk_level"])
    ):
        raise DomainError(
            "VALIDATION_ERROR", "auto_execute_max_risk 不能高于 max_risk_level", 422
        )
    return patch


@dataclass
class Decision:
    allowed: bool
    risk: str
    requires_approval: bool = False
    code: str | None = None
    message: str | None = None
    workspace_id: str | None = None
    resolved_path: str = ""
    data: dict = field(default_factory=dict)

    def deny(self, code: str, message: str, **detail) -> "Decision":
        return Decision(
            allowed=False, risk=self.risk, code=code, message=message,
            workspace_id=self.workspace_id, data=detail,
        )

    def as_error(self) -> DomainError:
        status = 403 if self.code not in {"TOOL_ARGS_INVALID"} else 422
        if self.code in {"RISK_EXCEEDED"}:
            status = 403
        return DomainError(self.code or "TOOL_DENIED", self.message or "工具调用被拒绝", status,
                           {"risk": self.risk, **(self.data or {})})


def _workspace_ids(session: Session, employee_id: str) -> set[str]:
    rows = session.execute(
        select(EmployeeWorkspaceGrant.workspace_id).where(
            EmployeeWorkspaceGrant.employee_id == employee_id
        )
    ).scalars().all()
    if not rows:
        return set()
    active = session.execute(
        select(Workspace.id).where(
            Workspace.id.in_(list(rows)), Workspace.status == "active"
        )
    ).scalars().all()
    return set(active)


def _employee_tool_layers(ctx: ToolContext, spec: ToolSpec) -> Decision:
    policy = ctx.tool_policy
    perms = ctx.permissions or {}

    if spec.category == "shell" or not spec.enabled:
        return Decision(False, spec.risk).deny(
            "SHELL_DISABLED" if spec.category == "shell" else "TOOL_DISABLED",
            "Shell 执行在 M3 永久禁用",
        )
    if not policy.get("categories", {}).get(spec.category, False):
        code = "SHELL_DISABLED" if spec.category == "shell" else "CATEGORY_DISABLED"
        return Decision(False, spec.risk).deny(code, f"公司策略未开启类别：{spec.category}")

    if spec.name not in (policy.get("allowed_tools") or []):
        return Decision(False, spec.risk).deny(
            "TOOL_NOT_GRANTED", f"公司工具白名单未包含：{spec.name}"
        )

    # 员工显式白名单：空 = 不允许任何工具
    employee_tools = list(ctx.employee.tools_allowed or [])
    if spec.name not in employee_tools:
        return Decision(False, spec.risk).deny(
            "TOOL_NOT_GRANTED", f"员工未被授予工具：{spec.name}"
        )

    # 岗位/员工权限层的 tools 清单（非空时作为额外收窄）
    layer_tools = perms.get("tools")
    if isinstance(layer_tools, list) and layer_tools and spec.name not in layer_tools:
        return Decision(False, spec.risk).deny(
            "TOOL_NOT_GRANTED", f"岗位/员工权限未包含工具：{spec.name}"
        )
    return Decision(True, spec.risk)


def _elevated_risk(spec: ToolSpec, args: dict) -> str:
    risk = spec.risk
    if spec.name == "fs.write_file":
        mode = str(args.get("mode") or "create")
        if mode == "overwrite":
            risk = "high"
        elif mode == "append":
            risk = "medium"
    if spec.name == "http.request":
        method = str(args.get("method") or "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            risk = "high"
    return risk


def decide(ctx: ToolContext, spec: ToolSpec, args: dict) -> Decision:
    risk = _elevated_risk(spec, args)
    policy = ctx.tool_policy

    if not global_tools_enabled():
        if tool_execution_state()["kill_switch"]:
            return Decision(False, risk).deny(
                "TOOLS_DISABLED", "工具执行已被管理员紧急停止（kill switch）"
            )
        return Decision(False, risk).deny(
            "TOOLS_DISABLED", "全局工具执行开关已关闭（AGENTOS_TOOL_EXECUTION=off）"
        )
    if not policy.get("enabled", True):
        return Decision(False, risk).deny("TOOLS_DISABLED", "公司策略已关闭工具执行")

    base = _employee_tool_layers(ctx, spec)
    if not base.allowed:
        return base

    if risk_rank(risk) > risk_rank(policy.get("max_risk_level", "high")):
        return Decision(False, risk).deny(
            "RISK_EXCEEDED", f"风险等级 {risk} 超过公司上限 {policy.get('max_risk_level')}"
        )

    decision = Decision(True, risk)
    if spec.category.startswith("file"):
        workspace_id = args.get("workspace_id")
        if not workspace_id:
            return decision.deny("WORKSPACE_NOT_GRANTED", "文件工具必须指定 workspace_id")
        need = "write" if spec.category == "file_write" else "read"
        try:
            workspace, _grant = resolve_grant(
                ctx.session, ctx.owner_id, ctx.employee.id, workspace_id, need
            )
        except DomainError as exc:
            return Decision(False, risk).deny(exc.code, exc.message, **(exc.detail or {}))
        decision.workspace_id = workspace.id
        # 先做一次路径校验：让"路径逃逸"在审批之前就被拒绝，避免浪费人工审批
        try:
            resolved = safe_resolve(
                Path(workspace.root_path), args.get("path", ""),
                allow_root=spec.name == "fs.list_dir",
            )
            decision.resolved_path = str(resolved)
            # 明知必然失败的操作不要浪费人工审批
            if spec.name in {"fs.delete_file", "fs.write_file"} and resolved.is_dir():
                return Decision(False, risk).deny(
                    "TOOL_PATH_DENIED", "目标是目录，文件工具不接受目录"
                )
        except PathDenied as exc:
            return Decision(False, risk).deny(exc.code, exc.message, **(exc.detail or {}))

    if spec.category == "network":
        domains = policy.get("network_domains") or []
        if not domains:
            return decision.deny("TOOL_NETWORK_DENIED", "公司未配置网络域名白名单")
        try:
            parts = urlsplit(str(args.get("url") or ""))
            host = (parts.hostname or "").lower()
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return decision.deny("TOOL_NETWORK_DENIED", "URL 无法解析")
        if parts.scheme not in ("http", "https"):
            return decision.deny("TOOL_NETWORK_DENIED", "只允许 http/https")
        if not host or not host_allowed(host, port, domains):
            return decision.deny("TOOL_NETWORK_DENIED", f"域名不在白名单：{host}")
        if str(args.get("method") or "GET").upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            if not policy.get("allow_http_write", False):
                return decision.deny(
                    "TOOL_DISABLED", "公司策略未开启 HTTP 写方法（allow_http_write=false）"
                )

    # 自动执行上限 = min(员工有效 max_risk_level, 公司 auto_execute_max_risk)
    # 超过它不拒绝，而是转人工审批（这是 gate=tool_call 的意义）
    employee_ceiling = (ctx.permissions or {}).get("max_risk_level") or "medium"
    auto_ceiling = policy.get("auto_execute_max_risk", "medium")
    if risk_rank(employee_ceiling) < risk_rank(auto_ceiling):
        auto_ceiling = employee_ceiling
    needs_approval = (
        risk_rank(risk) > risk_rank(auto_ceiling)
        or spec.requires_approval
        or spec.name in (policy.get("approval_required_tools") or [])
    )
    decision.requires_approval = needs_approval
    return decision


def visible_tools(ctx: ToolContext) -> list[str]:
    """当前员工"模型可见"的工具集合（已通过前四层，且工作区/网络可用）。"""
    names: list[str] = []
    has_workspace = bool(_workspace_ids(ctx.session, ctx.employee.id))
    for name, spec in REGISTRY.items():
        decision = _employee_tool_layers(ctx, spec)
        if not decision.allowed:
            continue
        if spec.category.startswith("file") and not has_workspace:
            continue
        if spec.category == "network" and not (ctx.tool_policy.get("network_domains") or []):
            continue
        names.append(name)
    return sorted(names)


def tool_permission_report(ctx: ToolContext) -> dict:
    """给 UI 用的五层诊断：每个工具为什么可用/不可用。"""
    has_workspace = bool(_workspace_ids(ctx.session, ctx.employee.id))
    items = []
    for name, spec in REGISTRY.items():
        decision = _employee_tool_layers(ctx, spec)
        if decision.allowed:
            reason = "available"
            if spec.category.startswith("file") and not has_workspace:
                reason = "workspace_not_granted"
            elif spec.category == "network" and not (ctx.tool_policy.get("network_domains") or []):
                reason = "network_not_configured"
        else:
            reason = str(decision.code).lower()
        items.append({
            "tool": name,
            "category": spec.category,
            "risk": spec.risk,
            "enabled": spec.enabled,
            "requires_approval": spec.requires_approval,
            "available": decision.allowed and reason == "available",
            "reason": reason,
        })
    return {
        "global_enabled": global_tools_enabled(),
        "company_enabled": bool(ctx.tool_policy.get("enabled", True)),
        "shell_enabled": False,
        "tools": items,
        "workspaces": sorted(_workspace_ids(ctx.session, ctx.employee.id)),
    }

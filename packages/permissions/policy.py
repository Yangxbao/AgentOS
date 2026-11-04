"""审批策略表 + 不可配置的硬 deny 清单（B5）。"""
from __future__ import annotations

import re

HARD_DENY_PATTERNS = [
    r"set-mppreference",
    r"netsh\s+advfirewall",
    r"add-mppreference.*exclusion",
    r"\bsetx\b",
    r"hklm\\+system\\+currentcontrolset\\+control\\+session manager\\+environment",
    r"\bbcdedit\b",
    r"vssadmin\s+delete",
]

RISK_LEVELS = ["low", "medium", "high", "critical"]

DEFAULT_DECISIONS = {
    "file_read": "allow",
    "file_write": "approval",
    "file_delete": "approval",
    "shell_exec": "approval",
    "network_upload": "approval",
    "system_config": "approval",
    "software_install": "approval",
    "service_deploy": "approval",
    "code_publish": "approval",
}


def is_hard_denied(command: str) -> bool:
    text = (command or "").lower()
    return any(re.search(pattern, text) for pattern in HARD_DENY_PATTERNS)


def decide(action_type: str, risk_level: str, effective_permissions: dict, command: str = "") -> dict:
    if command and is_hard_denied(command):
        return {"decision": "deny", "reason": "命中不可配置的系统安全黑名单（硬拒绝）"}
    max_risk = effective_permissions.get("max_risk_level", "medium")
    if RISK_LEVELS.index(risk_level) > RISK_LEVELS.index(max_risk):
        return {"decision": "deny", "reason": f"风险等级 {risk_level} 超出员工上限 {max_risk}"}
    decision = DEFAULT_DECISIONS.get(action_type, "approval")
    return {"decision": decision, "reason": f"按策略表：{action_type} → {decision}"}

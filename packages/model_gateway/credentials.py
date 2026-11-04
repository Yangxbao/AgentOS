"""凭据引用解析与脱敏（B3）。

规则（BR-11）：只接受 `env:<VAR>` / `dpapi:<blob>` / `keyring:<service>:<user>`；
拒绝 `sk-` 等疑似明文；解析失败给出明确错误，绝不回显密钥。
"""
from __future__ import annotations

import os
import re

from packages.shared.errors import DomainError

REF_PATTERN = re.compile(r"^(env:[A-Za-z_][A-Za-z0-9_]*|dpapi:[A-Za-z0-9_\-]+|keyring:[^:]+:[^:]+)$")
PLAINTEXT_HINTS = re.compile(r"^(sk-|sk_|xoxb-|ghp_|AIza)", re.IGNORECASE)
SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9]{8,}|Bearer\s+\S+|(?i:api[_-]?key)\s*[:=]\s*\S+)")


def validate_ref(ref: str) -> str:
    clean = (ref or "").strip()
    if not clean:
        raise DomainError("VALIDATION_ERROR", "api_key_ref 不能为空", 422)
    if PLAINTEXT_HINTS.match(clean) or clean.startswith("sk-"):
        raise DomainError(
            "BR_PLAINTEXT_KEY_REFUSED",
            "禁止提交明文密钥；请使用 env:DEEPSEEK_API_KEY 这类引用",
            422,
        )
    if not REF_PATTERN.match(clean):
        raise DomainError(
            "VALIDATION_ERROR",
            "api_key_ref 格式必须为 env:VAR / dpapi:blob / keyring:service:user",
            422,
        )
    return clean


def resolve_ref(ref: str) -> str:
    """解析为内存中的密钥值；仅用于调用瞬间，不缓存、不落库。"""
    ref = validate_ref(ref)
    scheme, _, rest = ref.partition(":")
    if scheme == "env":
        value = os.environ.get(rest)
        if not value:
            raise DomainError(
                "CREDENTIAL_MISSING",
                f"环境变量 {rest} 未设置，无法调用该模型连接",
                409,
                {"ref": ref},
            )
        return value
    # dpapi/keyring 属 M5 增强，当前明确不支持，不伪装成功
    raise DomainError(
        "CREDENTIAL_BACKEND_UNAVAILABLE",
        f"{scheme}: 凭据后端尚未实现（M5）；请改用 env:VAR",
        501,
        {"ref": ref},
    )


def has_credential(ref: str) -> bool:
    try:
        resolve_ref(ref)
        return True
    except DomainError:
        return False


def redact(text: str) -> str:
    return SECRET_PATTERN.sub("***", text or "")


def ref_display(ref: str) -> str:
    """用于响应的安全展示：只显示 scheme，不泄露变量名以外的内容。"""
    scheme = (ref or "").split(":", 1)[0]
    return f"{scheme}:***" if scheme else "***"

"""路径与敏感文件安全（M3-A 的核心安全函数）。

威胁模型：本地单用户 + 工作区。目标是阻止"模型/提示词注入诱导 Agent 读写工作区外或敏感文件"。
**不声称消除 TOCTOU**：校验与真正打开文件之间仍可能被本机其他进程替换，
彻底解决需要 OS 级沙箱（M4+）。这里做的是：
1. 拒绝一切"看起来就想逃逸"的输入（绝对路径/盘符/UNC/ADS/NUL）；
2. 逐级检查 reparse point（符号链接/junction）；
3. resolve 后再做真实路径包含判断（不靠字符串前缀）；
4. 大小写不敏感比较（Windows）；
5. 敏感文件名单（公司策略只能加不能减）。
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from packages.shared.errors import DomainError

# 文件名/目录名黑名单（全部小写比较）
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "ntuser.dat",
    "sam",
    "system",
    "credentials",
    "credentials.json",
    ".npmrc",
    ".pypirc",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".keystore")
SENSITIVE_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials")
SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".azure", ".kube"}
SENSITIVE_RELATIVE = {".git/config", ".git-credentials"}

_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_SPLIT = re.compile(r"[\\/]")
_REPARSE_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class PathDenied(Exception):
    """路径被拒绝；`code` 直接映射到 API 错误码。"""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def as_domain_error(self) -> DomainError:
        return DomainError(self.code, self.message, 403, self.detail)


def is_sensitive(relative: str) -> bool:
    """按相对路径判断是否为敏感文件（大小写不敏感）。"""
    normalized = relative.replace("\\", "/").strip("/").lower()
    if not normalized:
        return False
    if normalized in SENSITIVE_RELATIVE:
        return True
    parts = [part for part in normalized.split("/") if part]
    for part in parts:
        if part in SENSITIVE_DIRS:
            return True
        if part in SENSITIVE_NAMES:
            return True
        if part.startswith(SENSITIVE_PREFIXES):
            return True
        if part.endswith(SENSITIVE_SUFFIXES):
            return True
        # .env.* 变体
        if part.startswith(".env."):
            return True
    return False


def _is_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_FLAG)


def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _deny(message: str, code: str = "TOOL_PATH_DENIED", **detail) -> PathDenied:
    return PathDenied(code, message, detail)


def safe_resolve(root: str | Path, relative: str | None, *, allow_root: bool = True) -> Path:
    """把模型给的相对路径解析成工作区内的真实路径；任何可疑输入直接拒绝。"""
    root_path = Path(root)
    if not root_path.is_absolute():
        raise _deny(f"工作区根路径不是绝对路径：{root}", code="WORKSPACE_INVALID_ROOT")
    root_resolved = root_path.resolve()

    if relative is None:
        relative = ""
    if not isinstance(relative, str):
        raise _deny("路径必须是字符串")

    if relative == "":
        if allow_root:
            return root_resolved
        raise _deny("该操作不允许作用于工作区根目录")

    if "\x00" in relative:
        raise _deny("路径包含 NUL 字符")
    if any(ord(ch) < 32 for ch in relative):
        raise _deny("路径包含控制字符")
    # ADS（file.txt:stream）与 Windows 盘符（C:\...）都会命中冒号
    if ":" in relative:
        raise _deny("路径包含冒号（盘符或 NTFS 数据流不被允许）")
    if relative.startswith(("/", "\\")):
        raise _deny("不允许绝对路径或 UNC 路径")
    if os.path.isabs(relative):
        raise _deny("不允许绝对路径")

    parts = _SPLIT.split(relative)
    if any(part == "" for part in parts):
        raise _deny("路径包含空段（重复分隔符或首尾分隔符）")
    for part in parts:
        if part in (".", ".."):
            raise _deny("路径包含相对跳转（. 或 ..）")
        if part.endswith((" ", ".")):
            raise _deny(f"路径段以空格或点结尾：{part!r}")
        if part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise _deny(f"路径段是 Windows 保留设备名：{part}")

    candidate = root_resolved.joinpath(*parts)
    # 逐级检查已存在的 reparse point（链接/junction），必须在 resolve 之前检查
    cursor = root_resolved
    for part in parts:
        cursor = cursor / part
        if _is_reparse(cursor):
            raise _deny(f"路径经过符号链接/junction：{part}", code="TOOL_PATH_DENIED")

    resolved = candidate.resolve()
    try:
        common = os.path.commonpath([_norm(root_resolved), _norm(resolved)])
    except ValueError as exc:  # 不同盘符
        raise _deny("路径不在工作区内（跨盘符）") from exc
    if common != _norm(root_resolved):
        raise _deny("路径解析后落在工作区之外")

    if is_sensitive(relative):
        raise _deny(f"拒绝访问敏感文件：{relative}", code="TOOL_SENSITIVE_FILE")

    return resolved


def relative_of(root: str | Path, path: str | Path) -> str:
    root_resolved = Path(root).resolve()
    target = Path(path).resolve()
    try:
        return target.relative_to(root_resolved).as_posix()
    except ValueError:
        return target.as_posix()

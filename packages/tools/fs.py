"""文件工具（M3-A）：所有路径都必须先过 safe_resolve。

不提供 mkdir / 递归删除 / 目录删除；写文件用"临时文件 + fsync + os.replace"保证原子性。
"""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from packages.shared.errors import DomainError

from .context import ToolContext
from .paths import PathDenied, relative_of, safe_resolve
from .workspaces import resolve_grant

MAX_READ_BYTES = 256 * 1024
MAX_WRITE_BYTES = 1024 * 1024
MAX_LIST_ENTRIES = 500
MAX_LIST_DEPTH = 3

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
]


class SecretContent(Exception):
    """文件内容命中密钥特征：整体拒绝，不返回部分内容。"""


def scan_secrets(text: str) -> None:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise SecretContent(pattern.pattern)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def _ws(ctx: ToolContext, args: dict, need: str = "read"):
    workspace, _grant = resolve_grant(
        ctx.session, ctx.owner_id, ctx.employee.id, args["workspace_id"], need
    )
    return workspace


def _guarded(fn):
    """把 PathDenied/SecretContent 统一转成 DomainError（错误码稳定）。"""
    async def wrapper(ctx: ToolContext, args: dict) -> dict:
        try:
            return await fn(ctx, args)
        except PathDenied as exc:
            raise exc.as_domain_error() from exc
        except SecretContent as exc:
            raise DomainError(
                "TOOL_SENSITIVE_FILE",
                "文件内容命中密钥特征，已整体拒绝返回",
                403,
                {"pattern": exc.args[0][:40]},
            ) from exc
    return wrapper


@_guarded
async def list_dir(ctx: ToolContext, args: dict) -> dict:
    workspace = _ws(ctx, args)
    root = Path(workspace.root_path)
    target = safe_resolve(root, args.get("path", ""))
    depth = int(args.get("depth", 1))
    limit = int(args.get("limit", 200))
    if depth < 1 or depth > MAX_LIST_DEPTH:
        raise DomainError("TOOL_ARGS_INVALID", f"depth 必须在 1..{MAX_LIST_DEPTH}", 422)
    if limit < 1 or limit > MAX_LIST_ENTRIES:
        raise DomainError("TOOL_ARGS_INVALID", f"limit 必须在 1..{MAX_LIST_ENTRIES}", 422)
    if not target.is_dir():
        raise DomainError(
            "TOOL_PATH_NOT_FOUND", f"目录不存在：{relative_of(root, target)}", 404
        )

    entries: list[dict] = []
    truncated = False

    def walk(directory: Path, level: int) -> None:
        nonlocal truncated
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            entries.append({"name": directory.name, "type": "error", "error": str(exc)[:120]})
            return
        for child in children:
            if len(entries) >= limit:
                truncated = True
                return
            try:
                if child.is_symlink():
                    entries.append({
                        "name": child.name, "type": "symlink",
                        "path": relative_of(root, child),
                    })
                    continue
                info = child.stat()
                is_dir = child.is_dir()
            except OSError:
                continue
            entries.append({
                "name": child.name,
                "type": "dir" if is_dir else "file",
                "path": relative_of(root, child),
                "size": 0 if is_dir else info.st_size,
                "modified_at": _iso(info.st_mtime),
            })
            if is_dir and level < depth:
                walk(child, level + 1)

    walk(target, 1)
    return {
        "path": relative_of(root, target),
        "entries": entries,
        "truncated": truncated,
        "count": len(entries),
    }


@_guarded
async def read_file(ctx: ToolContext, args: dict) -> dict:
    workspace = _ws(ctx, args)
    root = Path(workspace.root_path)
    target = safe_resolve(root, args["path"], allow_root=False)
    if not target.is_file():
        raise DomainError("TOOL_PATH_NOT_FOUND", f"文件不存在：{args['path']}", 404)
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise DomainError(
            "TOOL_OUTPUT_TOO_LARGE",
            f"文件 {size} 字节超过读取上限 {MAX_READ_BYTES}",
            413, {"size": size, "limit": MAX_READ_BYTES},
        )
    data = target.read_bytes()
    if b"\x00" in data[:8192]:
        raise DomainError("TOOL_BINARY_UNSUPPORTED", "二进制文件不支持读取", 415)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DomainError(
            "TOOL_BINARY_UNSUPPORTED", "文件不是合法 UTF-8 文本", 415
        ) from exc
    scan_secrets(text)

    if args.get("with_line_numbers"):
        text = "\n".join(f"{index:>4}| {line}" for index, line in enumerate(text.splitlines(), 1))
    return {
        "path": relative_of(root, target),
        "size": size,
        "sha256": _sha256(data),
        "content": text,
    }


@_guarded
async def stat_path(ctx: ToolContext, args: dict) -> dict:
    workspace = _ws(ctx, args)
    root = Path(workspace.root_path)
    target = safe_resolve(root, args["path"])
    if not target.exists():
        raise DomainError("TOOL_PATH_NOT_FOUND", f"路径不存在：{args['path']}", 404)
    info = target.stat()
    return {
        "path": relative_of(root, target),
        "name": target.name,
        "type": "dir" if target.is_dir() else "file",
        "size": info.st_size,
        "mode": oct(info.st_mode & 0o777),
        "modified_at": _iso(info.st_mtime),
        "created_at": _iso(info.st_ctime),
    }


@_guarded
async def write_file(ctx: ToolContext, args: dict) -> dict:
    workspace = _ws(ctx, args, need="write")
    root = Path(workspace.root_path)
    target = safe_resolve(root, args["path"], allow_root=False)
    mode = args.get("mode", "create")
    content = args["content"]
    payload = content.encode("utf-8")
    if len(payload) > MAX_WRITE_BYTES:
        raise DomainError(
            "TOOL_OUTPUT_TOO_LARGE",
            f"写入内容 {len(payload)} 字节超过上限 {MAX_WRITE_BYTES}",
            413, {"limit": MAX_WRITE_BYTES},
        )
    if not target.parent.is_dir():
        raise DomainError(
            "TOOL_PATH_NOT_FOUND", "父目录不存在（不自动创建多级目录）", 404,
            {"parent": relative_of(root, target.parent)},
        )
    if target.is_dir():
        raise DomainError("TOOL_PATH_DENIED", "目标是目录，不能写入", 422)

    existed = target.exists()
    if mode == "create":
        if existed:
            raise DomainError(
                "TOOL_PATH_EXISTS", "文件已存在，create 模式不覆盖", 409,
                {"path": relative_of(root, target)},
            )
        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError as exc:
            raise DomainError("TOOL_PATH_EXISTS", "文件已存在（并发创建）", 409) from exc
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return {
            "path": relative_of(root, target),
            "mode": mode,
            "bytes": len(payload),
            "sha256": _sha256(payload),
            "created": True,
        }

    if mode == "append":
        current = target.stat().st_size if existed else 0
        if current + len(payload) > MAX_WRITE_BYTES:
            raise DomainError(
                "TOOL_OUTPUT_TOO_LARGE",
                f"追加后文件将超过 {MAX_WRITE_BYTES} 字节上限",
                413, {"current": current, "limit": MAX_WRITE_BYTES},
            )
        with target.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        data = target.read_bytes()
        return {
            "path": relative_of(root, target),
            "mode": mode,
            "bytes": len(payload),
            "total_bytes": len(data),
            "sha256": _sha256(data),
            "created": not existed,
        }

    # overwrite：临时文件 + fsync + 原子替换
    tmp = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise DomainError("TOOL_EXEC_FAILED", f"写入失败：{exc}", 500) from exc
    return {
        "path": relative_of(root, target),
        "mode": mode,
        "bytes": len(payload),
        "sha256": _sha256(payload),
        "created": not existed,
    }


@_guarded
async def delete_file(ctx: ToolContext, args: dict) -> dict:
    workspace = _ws(ctx, args, need="write")
    root = Path(workspace.root_path)
    target = safe_resolve(root, args["path"], allow_root=False)
    if not target.exists():
        raise DomainError("TOOL_PATH_NOT_FOUND", f"文件不存在：{args['path']}", 404)
    if target.is_dir():
        raise DomainError("TOOL_PATH_DENIED", "只允许删除单个文件，不允许删除目录", 422)
    if target.is_symlink():
        raise DomainError("TOOL_PATH_DENIED", "不允许删除符号链接", 422)
    data = target.read_bytes()
    digest, size = _sha256(data), len(data)
    try:
        target.unlink()
    except OSError as exc:
        raise DomainError("TOOL_EXEC_FAILED", f"删除失败：{exc}", 500) from exc
    return {
        "path": relative_of(root, target),
        "deleted": True,
        "sha256": digest,
        "bytes": size,
    }

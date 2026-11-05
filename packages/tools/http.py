"""HTTP 工具（M3-A）。

默认拒绝一切外部访问：必须由公司策略显式配置域名白名单。
防 SSRF：域名白名单 → DNS 解析后逐 IP 检查 → 重定向逐跳复检。
本机回环只在测试开关 + 显式白名单同时满足时放行（默认关闭）。
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

from packages.shared.errors import DomainError

from .context import ToolContext
from .paths import PathDenied  # noqa: F401  （保持错误类型统一导出习惯）

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_INLINE_CHARS = 20000
MAX_REDIRECTS = 5
ALLOWED_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED_HEADERS = {"content-type", "accept", "user-agent", "accept-language"}
FORBIDDEN_HEADERS = {"host", "cookie", "authorization", "proxy-authorization", "x-forwarded-for"}


def _allow_loopback() -> bool:
    return os.environ.get("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "0") == "1"


def host_allowed(host: str, port: int, domains: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for entry in domains or []:
        entry = str(entry).strip().lower()
        if not entry:
            continue
        if ":" in entry and entry.rsplit(":", 1)[1].isdigit():
            entry_host, entry_port = entry.rsplit(":", 1)
            if host == entry_host and int(entry_port) == port:
                return True
            continue
        if entry.startswith("*."):
            if host.endswith(entry[1:]) and host != entry[2:]:
                return True
        elif host == entry:
            return True
    return False


def _check_ip(address: str, host: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return
    metadata = {"169.254.169.254", "100.100.100.200", "fd00:ec2::254"}
    if str(ip) in metadata:
        raise DomainError(
            "TOOL_SSRF_BLOCKED", f"拒绝访问云元数据地址：{address}", 403, {"host": host}
        )
    if ip.is_loopback:
        if _allow_loopback():
            return
        raise DomainError(
            "TOOL_SSRF_BLOCKED", f"拒绝访问回环地址：{address}", 403, {"host": host}
        )
    if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise DomainError(
            "TOOL_SSRF_BLOCKED", f"拒绝访问内网/保留地址：{address}", 403, {"host": host}
        )


async def _resolve_and_check(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.run_in_executor(
            None, lambda: socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        )
    except socket.gaierror as exc:
        raise DomainError("TOOL_NETWORK_DENIED", f"域名解析失败：{host}", 502) from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise DomainError("TOOL_NETWORK_DENIED", f"域名无解析结果：{host}", 502)
    for address in addresses:
        _check_ip(address, host)
    return addresses


def _validate_url(url: str, domains: list[str]) -> tuple[str, str, int]:
    if not url or not isinstance(url, str):
        raise DomainError("TOOL_ARGS_INVALID", "url 必填", 422)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise DomainError("TOOL_NETWORK_DENIED", "只允许 http/https", 403, {"scheme": parts.scheme})
    if parts.username or parts.password:
        raise DomainError("TOOL_NETWORK_DENIED", "URL 不允许携带用户信息", 403)
    host = (parts.hostname or "").lower()
    if not host:
        raise DomainError("TOOL_ARGS_INVALID", "URL 缺少主机名", 422)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if not host_allowed(host, port, domains):
        raise DomainError(
            "TOOL_NETWORK_DENIED", f"域名不在白名单：{host}", 403,
            {"host": host, "domains": domains[:20]},
        )
    return parts.scheme, host, port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, D401
        return None


# 显式禁用系统代理：否则请求可能被本机代理转发，绕过域名白名单的语义
_OPENER = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def _do_request(method: str, url: str, headers: dict, body: bytes | None, timeout: float):
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        return _OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # 4xx/5xx 是"服务端正常应答"，属于工具结果而不是执行失败；
        # 3xx 交给上层做逐跳安全校验。
        return exc


async def request(ctx: ToolContext, args: dict) -> dict:
    policy = ctx.tool_policy or {}
    domains = list(policy.get("network_domains") or [])
    if not domains:
        raise DomainError(
            "TOOL_NETWORK_DENIED", "公司未配置网络域名白名单，默认禁止外部访问", 403
        )
    method = str(args.get("method", "GET")).upper()
    if method not in ALLOWED_METHODS:
        raise DomainError("TOOL_ARGS_INVALID", f"不支持的方法：{method}", 422)
    if method in WRITE_METHODS and not policy.get("allow_http_write", False):
        raise DomainError(
            "TOOL_DISABLED", "公司策略未开启 HTTP 写方法（allow_http_write=false）", 403
        )

    headers_in = args.get("headers") or {}
    if not isinstance(headers_in, dict):
        raise DomainError("TOOL_ARGS_INVALID", "headers 必须是对象", 422)
    headers: dict[str, str] = {}
    for key, value in headers_in.items():
        lowered = str(key).strip().lower()
        if lowered in FORBIDDEN_HEADERS:
            raise DomainError(
                "TOOL_NETWORK_DENIED", f"不允许自定义请求头：{key}", 403, {"header": key}
            )
        if lowered not in ALLOWED_HEADERS:
            raise DomainError(
                "TOOL_ARGS_INVALID", f"请求头不在允许列表：{key}", 422,
                {"allowed": sorted(ALLOWED_HEADERS)},
            )
        headers[key] = str(value)

    body = args.get("body")
    payload = body.encode("utf-8") if isinstance(body, str) and body else None
    if payload and len(payload) > 256 * 1024:
        raise DomainError("TOOL_ARGS_INVALID", "请求体超过 256KB", 413)
    if method in ("GET", "HEAD") and payload:
        raise DomainError("TOOL_ARGS_INVALID", f"{method} 不允许携带请求体", 422)

    timeout = float(args.get("timeout_s") or 30)
    timeout = max(1.0, min(timeout, 60.0))

    url = args["url"]
    hops: list[str] = []
    for _ in range(MAX_REDIRECTS + 1):
        _scheme, host, port = _validate_url(url, domains)
        await _resolve_and_check(host, port)
        hops.append(url)
        loop = asyncio.get_running_loop()
        try:
            response = await asyncio.wait_for(
                loop.run_in_executor(None, _do_request, method, url, headers, payload, timeout),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise DomainError("TOOL_TIMEOUT", f"HTTP 请求超过 {timeout}s", 504) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise DomainError(
                    "TOOL_TIMEOUT", f"HTTP 请求超过 {timeout}s", 504
                ) from exc
            raise DomainError("TOOL_EXEC_FAILED", f"请求失败：{str(reason)[:200]}", 502) from exc
        except OSError as exc:
            raise DomainError("TOOL_EXEC_FAILED", f"请求失败：{str(exc)[:200]}", 502) from exc

        status = getattr(response, "status", None) or getattr(response, "code", 0)
        if status in (301, 302, 303, 307, 308) and hasattr(response, "headers"):
            location = response.headers.get("Location")
            try:
                response.close()
            except Exception:  # noqa: BLE001
                pass
            if not location:
                raise DomainError("TOOL_EXEC_FAILED", "重定向缺少 Location", 502)
            url = urljoin(url, location)
            continue
        break

    else:
        raise DomainError("TOOL_NETWORK_DENIED", f"重定向超过 {MAX_REDIRECTS} 次", 403)

    content_type = ""
    raw = b""
    try:
        content_type = response.headers.get("Content-Type", "") if response.headers else ""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise DomainError(
                    "TOOL_OUTPUT_TOO_LARGE",
                    f"响应超过 {MAX_RESPONSE_BYTES} 字节上限",
                    413, {"limit": MAX_RESPONSE_BYTES},
                )
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass

    data: dict = {
        "url": hops[-1],
        "status": status,
        "content_type": content_type[:120],
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "redirects": hops[:-1],
    }
    text = ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if not text and raw:
        data["body_base64"] = base64.b64encode(raw[:MAX_INLINE_CHARS // 2]).decode("ascii")
        data["binary"] = True
    else:
        data["body"] = text[:MAX_INLINE_CHARS]
        if len(text) > MAX_INLINE_CHARS:
            data["truncated"] = True
    try:
        data["json"] = json.loads(text) if text and len(text) <= MAX_INLINE_CHARS else None
    except json.JSONDecodeError:
        data["json"] = None
    return data

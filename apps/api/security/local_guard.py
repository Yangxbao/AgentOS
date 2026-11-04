"""本地管理接口防护：Host 校验 + 可信 Origin + 自定义头 + Fetch Metadata + 可选令牌。

威胁模型（M1_PLAN_HANDOFF.md §11.8）：
- 用户浏览器打开的任意网页向 http://127.0.0.1:8000 发起跨站写请求（CSRF）
- DNS rebinding 伪造 Host 访问本地服务

设计说明（与文档的一处偏差，已记录在 B1 交接报告）：
文档建议挂在"写路由的 router 级依赖"；B1 尚无 /api/v1 写路由，为让防护覆盖现有与未来全部路由，
实现为 ASGI 中间件；M5 接入账号体系时可整体替换为鉴权中间件。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _split_env(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class LocalGuardConfig:
    trusted_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    allowed_hosts: list[str] = field(default_factory=lambda: ["localhost", "127.0.0.1", "::1"])
    client_header_name: str = "x-agentos-client"
    client_header_values: list[str] = field(default_factory=lambda: ["web", "cli"])
    local_token: str | None = None
    require_origin: bool = True

    def all_origins(self) -> set[str]:
        return {o.rstrip("/") for o in self.trusted_origins}


def config_from_env() -> LocalGuardConfig:
    cfg = LocalGuardConfig()
    extra = _split_env(os.environ.get("AGENTOS_TRUSTED_ORIGINS"))
    if extra:
        cfg.trusted_origins = list(dict.fromkeys(cfg.trusted_origins + extra))
    token = os.environ.get("AGENTOS_LOCAL_TOKEN")
    if token:
        cfg.local_token = token
    return cfg


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6: [::1]:8000
        end = host.find("]")
        return host[1:end] if end > 0 else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def _origin_of(headers: dict[str, str]) -> str | None:
    origin = headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


class LocalGuardMiddleware:
    def __init__(self, app, config: LocalGuardConfig | None = None):
        self.app = app
        self.config = config or config_from_env()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        method = scope.get("method", "GET").upper()

        # 1) Host 校验：所有请求（防 DNS rebinding）
        host = headers.get("host", "")
        if _hostname(host) not in set(self.config.allowed_hosts):
            await self._reject(send, 400, "INVALID_HOST", f"Host 不被允许：{host or '(空)'}")
            return

        # 2) 写请求：Origin / 自定义头 / Fetch Metadata / 可选令牌
        if method in UNSAFE_METHODS:
            origin = _origin_of(headers)
            if origin is not None and origin not in self.config.all_origins():
                await self._reject(send, 403, "UNTRUSTED_REQUEST", f"Origin 不被信任：{origin}")
                return
            if origin is None and self.config.require_origin:
                # 无 Origin/Referer 的非浏览器客户端，必须带自定义头（下面继续校验）
                pass

            site = headers.get("sec-fetch-site", "").lower()
            if site == "cross-site":
                await self._reject(send, 403, "UNTRUSTED_REQUEST", "跨站写请求被拒绝（Sec-Fetch-Site: cross-site）")
                return

            client = headers.get(self.config.client_header_name, "")
            if client not in self.config.client_header_values:
                await self._reject(
                    send,
                    403,
                    "MISSING_CLIENT_HEADER",
                    f"写请求必须携带 {self.config.client_header_name}: web（或 cli）",
                )
                return

            if self.config.local_token:
                token = headers.get("x-agentos-token", "")
                if token != self.config.local_token:
                    await self._reject(send, 401, "INVALID_TOKEN", "本地令牌无效或缺失")
                    return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send, status: int, code: str, message: str) -> None:
        body = json.dumps(
            {"error": {"code": code, "message": message, "detail": {}, "request_id": "-"}},
            ensure_ascii=False,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json; charset=utf-8")],
        })
        await send({"type": "http.response.body", "body": body})

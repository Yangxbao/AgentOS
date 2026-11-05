"""HTTP 工具安全（M3-A §6.8）：白名单、SSRF、重定向、超时、大小限制。

全部请求都指向本机 stub，不访问任何真实外网。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from packages.permissions.effective import compute_effective_permissions
from packages.persistence import get_session
from packages.persistence.models import Company, Employee
from packages.tools.context import ToolContext
from packages.tools.invoke import invoke_tool
from packages.tools.policy import DEFAULT_TOOL_POLICY, effective_tool_policy


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A003 - 静默
        return

    def _send(self, status: int, body: bytes = b"", content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/ok"):
            self._send(200, json.dumps({"ok": True, "path": self.path}).encode())
        elif self.path.startswith("/big"):
            self._send(200, b"x" * (3 * 1024 * 1024), "text/plain")
        elif self.path.startswith("/slow"):
            time.sleep(1.5)
            self._send(200, b'{"slow": true}')
        elif self.path.startswith("/redirect-bad"):
            self.send_response(302)
            self.send_header("Location", "http://evil.example/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/redirect-ok"):
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path.startswith("/boom"):
            self._send(500, b'{"error": "boom"}')
        else:
            self._send(404, b"{}")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self._send(200, json.dumps({
            "method": "POST", "bytes": len(body),
            "content_type": self.headers.get("Content-Type", ""),
        }).encode())


@pytest.fixture
def http_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def task_row(session, seeded_team, tool_employee):
    import uuid

    from packages.persistence.models import Task

    row = Task(
        id=uuid.uuid4().hex[:24], title="HTTP 工具单测",
        company_id=seeded_team["company"]["id"],
        assignee_employee_id=tool_employee["id"], state="draft", instruction="测试",
    )
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def session(db_url):
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def setup_network(session, company_id, *, domains, allow_write=False, tools=None):
    company = session.get(Company, company_id)
    current = effective_tool_policy(company)
    merged = {
        **current,
        "categories": {**current["categories"], "network": True},
        "allowed_tools": list(tools or (current["allowed_tools"] + ["http.request"])),
        "network_domains": list(domains),
        "allow_http_write": allow_write,
    }
    policy = dict(company.policy or {})
    policy["tools"] = merged
    company.policy = policy
    session.commit()
    return merged


def _ctx(session, company_id, employee_id, *, approved=False):
    company = session.get(Company, company_id)
    employee = session.get(Employee, employee_id)
    return ToolContext(
        session=session, owner_id="local", company=company, employee=employee,
        tool_policy=effective_tool_policy(company),
        permissions=compute_effective_permissions(session, "local", employee_id)["permissions"],
        approved=approved,
    )


async def test_get_ok(tools_on, session, seeded_team, tool_employee, http_stub, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://{http_stub}/ok"})
    assert outcome.ok, outcome.error_message
    assert outcome.output["data"]["status"] == 200
    assert outcome.output["data"]["json"]["ok"] is True


async def test_redirect_within_whitelist(tools_on, session, seeded_team, tool_employee, http_stub,
                                         monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://{http_stub}/redirect-ok"})
    assert outcome.ok, outcome.error_message
    assert outcome.output["data"]["status"] == 200


async def test_domain_not_whitelisted(tools_on, session, seeded_team, tool_employee, http_stub,
                                      monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=["api.example.com"])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://{http_stub}/ok"})
    assert not outcome.ok and outcome.error_code == "TOOL_NETWORK_DENIED"


async def test_no_whitelist_configured(tools_on, session, seeded_team, tool_employee):
    setup_network(session, seeded_team["company"]["id"], domains=[])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": "https://api.example.com/x"})
    assert not outcome.ok and outcome.error_code == "TOOL_NETWORK_DENIED"


async def test_loopback_blocked_by_default(tools_on, session, seeded_team, tool_employee,
                                           http_stub, monkeypatch):
    monkeypatch.delenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", raising=False)
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://{http_stub}/ok"})
    assert not outcome.ok and outcome.error_code == "TOOL_SSRF_BLOCKED"


async def test_localhost_name_blocked(tools_on, session, seeded_team, tool_employee, http_stub,
                                      monkeypatch):
    monkeypatch.delenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", raising=False)
    port = http_stub.split(":")[1]
    setup_network(session, seeded_team["company"]["id"], domains=[f"localhost:{port}"])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://localhost:{port}/ok"})
    assert not outcome.ok and outcome.error_code == "TOOL_SSRF_BLOCKED"


async def test_metadata_ip_blocked(tools_on, session, seeded_team, tool_employee):
    setup_network(session, seeded_team["company"]["id"], domains=["169.254.169.254"])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request", {"url": "http://169.254.169.254/latest/meta-data/"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_SSRF_BLOCKED"


async def test_private_ip_blocked(tools_on, session, seeded_team, tool_employee):
    setup_network(session, seeded_team["company"]["id"], domains=["192.168.10.10"])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": "http://192.168.10.10/admin"})
    assert not outcome.ok and outcome.error_code == "TOOL_SSRF_BLOCKED"


async def test_redirect_to_untrusted_domain_rejected(tools_on, session, seeded_team, tool_employee,
                                                     http_stub, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request", {"url": f"http://{http_stub}/redirect-bad"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_NETWORK_DENIED"


async def test_custom_host_header_rejected(tools_on, session, seeded_team, tool_employee,
                                           http_stub, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request", {"url": f"http://{http_stub}/ok", "headers": {"Host": "evil.example"}}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_NETWORK_DENIED"


async def test_authorization_header_rejected(tools_on, session, seeded_team, tool_employee,
                                             http_stub, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request",
        {"url": f"http://{http_stub}/ok", "headers": {"Authorization": "Bearer abcdefghijklmnop"}},
    )
    assert not outcome.ok and outcome.error_code == "TOOL_NETWORK_DENIED"


async def test_post_denied_without_policy(tools_on, session, seeded_team, tool_employee,
                                          http_stub, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub], allow_write=False)
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request", {"url": f"http://{http_stub}/hook", "method": "POST", "body": "x"}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_DISABLED"


async def test_post_requires_approval_then_executes(tools_on, session, seeded_team, tool_employee,
                                                    http_stub, monkeypatch, task_row):
    from packages.persistence import get_session as _gs

    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub], allow_write=True)
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    ctx.task = task_row
    args = {"url": f"http://{http_stub}/hook", "method": "POST", "body": "payload"}
    pending = await invoke_tool(ctx, "http.request", args)
    assert pending.suspended, pending.error_message

    other = _gs()
    try:
        approved_ctx = _ctx(other, seeded_team["company"]["id"], tool_employee["id"], approved=True)
        approved_ctx.task = other.get(type(task_row), task_row.id)
        approved_ctx.tool_call_id = pending.tool_call_id
        outcome = await invoke_tool(approved_ctx, "http.request", args)
        assert outcome.ok, outcome.error_message
        assert outcome.output["data"]["json"]["method"] == "POST"
        assert outcome.output["data"]["json"]["bytes"] == len("payload")
    finally:
        other.close()


async def test_timeout(tools_on, session, seeded_team, tool_employee, http_stub, monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(
        ctx, "http.request", {"url": f"http://{http_stub}/slow", "timeout_s": 1}
    )
    assert not outcome.ok and outcome.error_code == "TOOL_TIMEOUT"


async def test_response_too_large(tools_on, session, seeded_team, tool_employee, http_stub,
                                 monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://{http_stub}/big"})
    assert not outcome.ok and outcome.error_code == "TOOL_OUTPUT_TOO_LARGE"


async def test_http_500_returns_status(tools_on, session, seeded_team, tool_employee, http_stub,
                                       monkeypatch):
    monkeypatch.setenv("AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK", "1")
    setup_network(session, seeded_team["company"]["id"], domains=[http_stub])
    ctx = _ctx(session, seeded_team["company"]["id"], tool_employee["id"])
    outcome = await invoke_tool(ctx, "http.request", {"url": f"http://{http_stub}/boom"})
    assert outcome.ok and outcome.output["data"]["status"] == 500


def test_default_network_category_is_off():
    assert DEFAULT_TOOL_POLICY["categories"]["network"] is False
    assert "http.request" not in DEFAULT_TOOL_POLICY["allowed_tools"]
    assert DEFAULT_TOOL_POLICY["network_domains"] == []

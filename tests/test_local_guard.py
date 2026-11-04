"""B1 本地管理接口防护测试（S-11 ~ S-14 + 正常请求放行对照）。"""
from __future__ import annotations

from scripts.run_api import resolve_bind_host

ALLOWED_ORIGIN = "http://127.0.0.1:5173"
CLIENT_HEADERS = {"X-AgentOS-Client": "web"}


def test_normal_frontend_request_passes(client, seeded_task):
    """放行对照：可信 Origin + 自定义头 → 通过防护，进入路由（405 说明已到达路由层）。"""
    resp = client.post("/api/tasks", headers={"Origin": ALLOWED_ORIGIN, **CLIENT_HEADERS})
    assert resp.status_code == 405, resp.text
    assert resp.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert resp.headers.get("x-request-id")

    # 读请求不受 Origin 限制
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_untrusted_origin_rejected(client):
    resp = client.post("/api/tasks", headers={"Origin": "http://evil.example", **CLIENT_HEADERS})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "UNTRUSTED_REQUEST"

    # Fetch Metadata 明确跨站时，即使 Origin 在名单内也拒绝（S-11 补充断言）
    cross_site = client.post(
        "/api/tasks",
        headers={"Origin": ALLOWED_ORIGIN, "Sec-Fetch-Site": "cross-site", **CLIENT_HEADERS},
    )
    assert cross_site.status_code == 403
    assert cross_site.json()["error"]["code"] == "UNTRUSTED_REQUEST"


def test_invalid_host_rejected(client):
    resp = client.get("/api/health", headers={"Host": "evil.example"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_HOST"


def test_missing_client_header_rejected(client):
    resp = client.post("/api/tasks", headers={"Origin": ALLOWED_ORIGIN})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "MISSING_CLIENT_HEADER"


def test_external_bind_address_rejected():
    # S-14：0.0.0.0 默认拒绝启动
    try:
        resolve_bind_host("0.0.0.0")
    except SystemExit as exc:
        assert "127.0.0.1" in str(exc)
    else:
        raise AssertionError("0.0.0.0 未被拒绝")

    # 显式授权后才允许
    assert resolve_bind_host("0.0.0.0", allow_external=True) == "0.0.0.0"
    # 回环地址统一规范化为 127.0.0.1
    assert resolve_bind_host("localhost") == "127.0.0.1"
    assert resolve_bind_host("::1") == "127.0.0.1"

"""B1 补充验收：错误包络、request_id、分页边界、CORS 预检、Referer、可选令牌。"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from apps.api.deps import PageParams, get_actor
from apps.api.errors import register_exception_handlers
from apps.api.main import create_app

ALLOWED_ORIGIN = "http://127.0.0.1:5173"
CLIENT_HEADERS = {"X-AgentOS-Client": "web"}


def test_error_envelope_and_request_id(client):
    resp = client.get("/api/not-exists")
    assert resp.status_code == 404
    body = resp.json()["error"]
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] != "-"
    assert resp.headers["x-request-id"] == body["request_id"]


def test_request_id_is_echoed_when_provided(client):
    resp = client.get("/api/health", headers={"X-Request-ID": "trace-abc-123"})
    assert resp.status_code == 200
    assert resp.headers["x-request-id"] == "trace-abc-123"


def test_guard_rejection_carries_request_id(client):
    resp = client.post("/api/tasks", headers={"Origin": "http://evil.example", **CLIENT_HEADERS})
    assert resp.status_code == 403
    assert resp.json()["error"]["request_id"] != "-"
    assert resp.headers["x-request-id"] == resp.json()["error"]["request_id"]


def test_pagination_bounds_and_validation():
    """用探针应用验证 PageParams：边界值可用、超限/非法值返回统一 422。"""
    probe = FastAPI()
    register_exception_handlers(probe)

    @probe.get("/probe")
    def _probe(params: PageParams = Depends()):
        return {"page": params.page, "page_size": params.page_size, "offset": params.offset}

    with TestClient(probe) as test_client:
        ok = test_client.get("/probe?page=2&page_size=200")
        assert ok.status_code == 200
        assert ok.json() == {"page": 2, "page_size": 200, "offset": 200}

        too_big = test_client.get("/probe?page_size=201")
        assert too_big.status_code == 422
        assert too_big.json()["error"]["code"] == "VALIDATION_ERROR"

        bad_page = test_client.get("/probe?page=0")
        assert bad_page.status_code == 422
        assert bad_page.json()["error"]["code"] == "VALIDATION_ERROR"


def test_cors_preflight_allows_agentos_client_header(client):
    resp = client.options(
        "/api/tasks",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-agentos-client,content-type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "x-agentos-client" in resp.headers.get("access-control-allow-headers", "").lower()


def test_referer_fallback_accepted(client):
    """没有 Origin 时用 Referer 判断来源（非浏览器客户端常见）。"""
    resp = client.post(
        "/api/tasks",
        headers={"Referer": f"{ALLOWED_ORIGIN}/employees", **CLIENT_HEADERS},
    )
    assert resp.status_code == 405  # 放行到路由层


def test_local_token_required_when_configured(monkeypatch):
    monkeypatch.setenv("AGENTOS_LOCAL_TOKEN", "s3cret-token")
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        missing = test_client.post("/api/tasks", headers={"Origin": ALLOWED_ORIGIN, **CLIENT_HEADERS})
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "INVALID_TOKEN"

        wrong = test_client.post(
            "/api/tasks",
            headers={"Origin": ALLOWED_ORIGIN, "X-AgentOS-Token": "nope", **CLIENT_HEADERS},
        )
        assert wrong.status_code == 401

        ok = test_client.post(
            "/api/tasks",
            headers={"Origin": ALLOWED_ORIGIN, "X-AgentOS-Token": "s3cret-token", **CLIENT_HEADERS},
        )
        assert ok.status_code == 405


def test_actor_is_local_user(actor):
    assert actor.actor_type == "user"
    assert actor.owner_id == "local"
    from fastapi import Request as _Request

    assert get_actor(_Request({"type": "http", "headers": []})).actor_id == "local"

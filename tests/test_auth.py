"""M4 账号体系：注册/登录/会话/登出/数据隔离/开关兼容。

全部用例自包含（数据用带 token 的请求自建），避免 fixture 环境互相污染。
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    from apps.api.main import create_app

    app = create_app()
    c = TestClient(app, base_url="http://127.0.0.1:8000")
    c.headers.update({"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"})
    return c


def _register(client, username, password="pass12345678", display_name=""):
    return client.post("/api/v1/auth/register",
                       json={"username": username, "password": password, "display_name": display_name})


def _login(client, username, password="pass12345678"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_status_reports_enabled(monkeypatch):
    from packages import auth as auth_service

    monkeypatch.setattr(auth_service, "auth_enabled", lambda: True)
    client = _make_client()
    assert client.get("/api/v1/auth/status").json() == {"enabled": True}


def test_register_login_create_and_read(monkeypatch, db_url):
    """注册 → 登录 → 带 token 建公司 → 读回：完整主链路。"""
    from packages import auth as auth_service

    monkeypatch.setattr(auth_service, "auth_enabled", lambda: True)
    client = _make_client()
    r = _register(client, "alice")
    assert r.status_code == 200, r.text
    assert r.json()["owner_id"].startswith("u_") and r.json()["owner_id"] != "local"

    r = _login(client, "alice")
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["user"]["username"] == "alice"
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post("/api/v1/companies", json={"name": "爱丽丝的公司"}, headers=headers)
    assert created.status_code == 201, created.text
    items = client.get("/api/v1/companies", headers=headers).json()["items"]
    assert [c["name"] for c in items] == ["爱丽丝的公司"]
    # me 返回登录身份
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["actor"] == "alice" and me["owner_id"].startswith("u_")


def test_second_user_isolation(monkeypatch, db_url):
    """两个用户互不可见对方公司（owner_id 隔离）。"""
    from packages import auth as auth_service

    monkeypatch.setattr(auth_service, "auth_enabled", lambda: True)
    client = _make_client()
    for name in ("alice", "bob"):
        assert _register(client, name).status_code == 200
    alice_token = _login(client, "alice", "pass12345678").json()["token"]
    bob_token = _login(client, "bob", "pass12345678").json()["token"]

    r = client.post("/api/v1/companies", json={"name": "爱丽丝的公司"},
                    headers={"Authorization": f"Bearer {alice_token}"})
    assert r.status_code == 201

    alice_items = client.get("/api/v1/companies",
                             headers={"Authorization": f"Bearer {alice_token}"}).json()["items"]
    bob_items = client.get("/api/v1/companies",
                           headers={"Authorization": f"Bearer {bob_token}"}).json()["items"]
    assert [c["name"] for c in alice_items] == ["爱丽丝的公司"]
    assert bob_items == []


def test_wrong_password_401_and_username_not_leaked(monkeypatch, db_url):
    from packages import auth as auth_service

    monkeypatch.setattr(auth_service, "auth_enabled", lambda: True)
    client = _make_client()
    assert _register(client, "carol").status_code == 200
    for username, password in (("carol", "wrong-password"), ("no-such-user", "whatever123")):
        r = _login(client, username, password)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"  # 同一错误，不泄露账号存在性


def test_logout_invalidates_session(monkeypatch, db_url):
    from packages import auth as auth_service

    monkeypatch.setattr(auth_service, "auth_enabled", lambda: True)
    client = _make_client()
    assert _register(client, "dave").status_code == 200
    token = _login(client, "dave").json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_register_validation(monkeypatch, db_url):
    from packages import auth as auth_service

    monkeypatch.setattr(auth_service, "auth_enabled", lambda: True)
    client = _make_client()
    assert client.post("/api/v1/auth/register",
                       json={"username": "ab", "password": "longenough1"}).status_code == 422
    assert client.post("/api/v1/auth/register",
                       json={"username": "bob", "password": "short"}).status_code == 422
    assert client.post("/api/v1/auth/register",
                       json={"username": "bob", "password": "bob12345678"}).status_code == 200
    assert client.post("/api/v1/auth/register",
                       json={"username": "bob", "password": "bob12345678"}).status_code == 409


def test_admin_seed_login():
    """迁移种子 admin（owner_id=local）：登录成功且绑定既有数据空间（真实库）。

    with 上下文触发 lifespan：init_db 按 env 指向真实库（否则全局 engine 可能
    残留上一个测试的 tmp 连接，导致 admin 查不到 → 401）。
    """
    from apps.api.main import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        c.headers.update({"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"})
        r = _login(c, "admin", "admin123")
        assert r.status_code == 200, r.text
        assert r.json()["user"]["owner_id"] == "local"
        token = r.json()["token"]
        assert c.get("/api/v1/companies", headers={"Authorization": f"Bearer {token}"}).status_code == 200
        # 清理会话，不留登录态
        assert c.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_auth_off_keeps_legacy_behaviour():
    """开关 off（默认）：业务接口不要求登录，owner=local 行为不变。"""
    client = _make_client()
    assert client.get("/api/v1/auth/status").json() == {"enabled": False}
    assert client.get("/api/v1/companies").status_code == 200  # 无 token 也放行

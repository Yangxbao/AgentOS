"""测试夹具（B1）：临时数据库、带真实中间件的 API 客户端、调用主体、样例任务。

注意：B1 尚无 company/employee 表，seeded_company 夹具随 B2 一起提供。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.deps import ActorContext, get_actor  # noqa: E402
from apps.api.main import create_app  # noqa: E402
from packages.persistence import Task, get_session, init_db  # noqa: E402
from packages.shared.types import new_id  # noqa: E402


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'agentos_test.db'}"
    monkeypatch.setenv("AGENTOS_DB_URL", url)
    init_db(url)
    return url


@pytest.fixture
def client(db_url):
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


@pytest.fixture
def actor() -> ActorContext:
    return get_actor()


@pytest.fixture
def write_client(client):
    """带可信 Origin 与自定义头的客户端：业务写请求用；安全测试仍用裸 client。"""
    client.headers.update({"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"})
    return client


@pytest.fixture
def seeded_company(write_client) -> dict:
    """B2：建一家默认公司并返回其响应体（含 id / updated_at）。"""
    resp = write_client.post(
        "/api/v1/companies",
        json={"name": "测试公司", "description": "B2 夹具"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def seeded_task(db_url) -> str:
    """插入一条真实任务记录，供接口/防护测试断言。"""
    task_id = new_id()
    with get_session() as session:
        session.add(Task(id=task_id, title="B1 夹具任务", state="draft"))
        session.commit()
    return task_id

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


@pytest.fixture(autouse=True)
def default_execution_env(monkeypatch):
    """全量测试默认走 Mock 执行：绝不因测试意外产生真实模型费用。"""
    monkeypatch.setenv("AGENTOS_MODEL_MODE", "mock")
    monkeypatch.setenv("AGENTOS_MOCK_DELAY_MS", "0")


@pytest.fixture(autouse=True)
def isolated_prompt_root(tmp_path, monkeypatch):
    """每个测试用独立提示词根目录，避免污染 data/prompts（否则对账脚本会报孤儿）。"""
    root = tmp_path / "prompts"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGENTOS_PROMPTS_ROOT", str(root))
    return root


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
def seeded_connection(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "test-secret")
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/model-connections",
        json={
            "name": "测试连接",
            "provider": "deepseek",
            "model": "deepseek/deepseek-chat",
            "api_key_ref": "env:TEST_MODEL_KEY",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def seeded_employee(write_client, seeded_company, seeded_connection) -> dict:
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/employees",
        json={
            "name": "测试员工",
            "title": "分析师",
            "primary_model_id": seeded_connection["id"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def seeded_team(write_client, seeded_company, seeded_connection) -> dict:
    """M2 执行夹具：一家公司 + 管理/开发/测试三名员工 + 对应岗位。"""
    company_id = seeded_company["id"]

    def _position(name: str, **extra) -> dict:
        resp = write_client.post(
            f"/api/v1/companies/{company_id}/positions",
            json={"name": name, **extra},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def _employee(name: str, title: str, position_id: str, tools: list[str] | None = None) -> dict:
        resp = write_client.post(
            f"/api/v1/companies/{company_id}/employees",
            json={
                "name": name, "title": title,
                "primary_model_id": seeded_connection["id"],
                "tools_allowed": tools or [],
                "positions": [{"position_id": position_id, "is_primary": True}],
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    manager_position = _position("负责人", is_managerial=True, can_review=True)
    dev_position = _position("开发", review_capability_tags=["coding.python"])
    qa_position = _position("测试", can_review=True, review_capability_tags=["test.unit"])

    return {
        "company": seeded_company,
        "connection": seeded_connection,
        "manager": _employee("经理甲", "负责人", manager_position["id"]),
        "dev": _employee("开发乙", "开发工程师", dev_position["id"], tools=["file.write"]),
        "qa": _employee("测试丙", "测试工程师", qa_position["id"]),
        "positions": {
            "manager": manager_position, "dev": dev_position, "qa": qa_position,
        },
    }


@pytest.fixture
def seeded_task(db_url) -> str:
    """插入一条真实任务记录，供接口/防护测试断言。"""
    task_id = new_id()
    with get_session() as session:
        session.add(Task(id=task_id, title="B1 夹具任务", state="draft"))
        session.commit()
    return task_id


TOOL_NAMES = [
    "fs.list_dir", "fs.read_file", "fs.stat",
    "fs.write_file", "fs.delete_file", "http.request",
]


@pytest.fixture
def tools_on(monkeypatch):
    """显式打开全局工具开关：默认是 off（生产默认不加权限）。"""
    monkeypatch.setenv("AGENTOS_TOOL_EXECUTION", "on")
    return True


@pytest.fixture
def workspace_root(tmp_path):
    root = tmp_path / "workspace"
    (root / "notes").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "notes" / "a.txt").write_text("hello world", encoding="utf-8")
    return root


@pytest.fixture
def seeded_workspace(write_client, seeded_company, workspace_root):
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/workspaces",
        json={"name": "测试工作区", "root_path": str(workspace_root), "mode": "read_write"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def tool_employee(write_client, seeded_team, seeded_workspace):
    """有工具白名单 + 工作区写授权的员工（默认 medium 风险上限）。"""
    company_id = seeded_team["company"]["id"]
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={
            "name": "工具员工", "title": "执行工程师",
            "primary_model_id": seeded_team["connection"]["id"],
            "tools_allowed": list(TOOL_NAMES),
        },
    )
    assert resp.status_code == 201, resp.text
    employee = resp.json()
    grant = write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": employee["id"], "access": "write"},
    )
    assert grant.status_code == 201, grant.text
    return employee

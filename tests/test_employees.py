"""B3 验收：员工 CRUD/汇报链/软删除、模型连接、解耦与历史快照、凭据与健康缓存。"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from packages.model_gateway.credentials import redact, resolve_ref, validate_ref
from packages.model_gateway.health import health_cache
from packages.persistence import UsageRecord, get_session
from packages.shared.errors import DomainError


def _create_connection(write_client, company_id, name="DeepSeek 主力", model="deepseek/deepseek-chat",
                       ref="env:TEST_MODEL_KEY"):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/model-connections",
        json={"name": name, "provider": "deepseek", "model": model, "api_key_ref": ref},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_position(write_client, company_id, name="分析师", can_review=False):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/positions",
        json={"name": name, "can_review": can_review},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_employee(write_client, company_id, connection_id, name="林知远", **kwargs):
    payload = {"name": name, "primary_model_id": connection_id, **kwargs}
    resp = write_client.post(f"/api/v1/companies/{company_id}/employees", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_connection_crud_and_models(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "secret-value")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    assert conn["has_credential"] is True
    assert conn["api_key_ref"] == "env:TEST_MODEL_KEY"
    assert "secret-value" not in str(conn)

    listed = write_client.get(f"/api/v1/companies/{company_id}/model-connections")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    models = write_client.get(f"/api/v1/model-connections/{conn['id']}/models")
    assert models.status_code == 200
    assert any(m["id"] == "deepseek/deepseek-chat" for m in models.json()["models"])

    patched = write_client.patch(
        f"/api/v1/model-connections/{conn['id']}", json={"name": "DeepSeek 备用"}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "DeepSeek 备用"


def test_connection_rejects_plaintext_key(write_client, seeded_company):
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/model-connections",
        json={"name": "bad", "provider": "deepseek", "api_key_ref": "sk-abcdefgh12345678"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BR_PLAINTEXT_KEY_REFUSED"


def test_connection_duplicate_and_delete_reference(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    dup = write_client.post(
        f"/api/v1/companies/{company_id}/model-connections",
        json={"name": "另一个", "provider": "deepseek", "model": conn["model"], "api_key_ref": "env:TEST_MODEL_KEY"},
    )
    assert dup.status_code == 409

    _create_employee(write_client, company_id, conn["id"])
    blocked = write_client.delete(f"/api/v1/model-connections/{conn['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BR_MODEL_IN_USE"


def test_employee_create_with_positions_and_detail(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    position = _create_position(write_client, company_id)
    employee = _create_employee(
        write_client, company_id, conn["id"],
        title="首席分析官", positions=[{"position_id": position["id"], "is_primary": True}],
    )
    assert employee["status"] == "active"
    assert employee["positions"][0]["name"] == "分析师"
    assert employee["model"]["primary"]["id"] == conn["id"]
    assert employee["model"]["health_source"] == "unknown"

    detail = write_client.get(f"/api/v1/employees/{employee['id']}")
    assert detail.status_code == 200
    assert detail.json()["model_history"] == []


def test_employee_duplicate_name(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    _create_employee(write_client, company_id, conn["id"])
    dup = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={"name": "林知远", "primary_model_id": conn["id"]},
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "BR_EMPLOYEE_NAME_TAKEN"


def test_report_self_and_cycle_rejected(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    ceo = _create_employee(write_client, company_id, conn["id"], name="CEO")
    dev = _create_employee(write_client, company_id, conn["id"], name="开发", reports_to=ceo["id"])

    self_report = write_client.patch(f"/api/v1/employees/{ceo['id']}", json={"reports_to": ceo["id"]})
    assert self_report.status_code == 409
    assert self_report.json()["error"]["code"] == "BR_REPORT_SELF"

    cycle = write_client.patch(f"/api/v1/employees/{ceo['id']}", json={"reports_to": dev["id"]})
    assert cycle.status_code == 409
    assert cycle.json()["error"]["code"] == "BR_REPORT_CYCLE"


def test_employee_disable_enable_and_delete_rules(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    boss = _create_employee(write_client, company_id, conn["id"], name="主管")
    staff = _create_employee(write_client, company_id, conn["id"], name="专员", reports_to=boss["id"])

    disabled = write_client.post(f"/api/v1/employees/{staff['id']}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    enabled = write_client.post(f"/api/v1/employees/{staff['id']}/enable")
    assert enabled.json()["status"] == "active"

    blocked = write_client.delete(f"/api/v1/employees/{boss['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BR_EMPLOYEE_HAS_REPORTS"

    assert write_client.delete(f"/api/v1/employees/{staff['id']}").status_code == 204
    # 软删除后同名可复用
    again = _create_employee(write_client, company_id, conn["id"], name="专员")
    assert again["id"] != staff["id"]


def test_model_switch_history_and_warnings(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    primary = _create_connection(write_client, company_id, name="主连接", model="deepseek/deepseek-chat")
    second = _create_connection(write_client, company_id, name="备用连接", model="custom/unknown-model")
    employee = _create_employee(write_client, company_id, primary["id"])

    switched = write_client.put(
        f"/api/v1/employees/{employee['id']}/model-binding",
        json={"primary_model_id": second["id"], "reason": "测试切换"},
    )
    assert switched.status_code == 200
    body = switched.json()
    assert body["employee_id"] == employee["id"]
    assert body["history_preserved"] is True
    assert body["warnings"], "切到未知模型应给出能力不可预判警告"

    detail = write_client.get(f"/api/v1/employees/{employee['id']}")
    history = detail.json()["model_history"]
    assert len(history) == 1
    assert history[0]["from_model_id"] == primary["id"]
    assert history[0]["to_model_id"] == second["id"]


def test_shared_connection_usage_attribution(write_client, seeded_company, monkeypatch):
    """两个员工共用同一连接：usage 按 employee_id 归属，互不串账。"""
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    a = _create_employee(write_client, company_id, conn["id"], name="员工A")
    b = _create_employee(write_client, company_id, conn["id"], name="员工B")

    with get_session() as session:
        for employee, tokens in ((a, 10), (b, 20)):
            session.add(UsageRecord(
                agent_run_id="run-x", employee_key=employee["name"],
                employee_id=employee["id"], model=conn["model"],
                prompt_tokens=tokens, completion_tokens=1, cost_usd=None, latency_ms=1,
            ))
        session.commit()
        rows = session.execute(select(UsageRecord).order_by(UsageRecord.prompt_tokens)).scalars().all()
    assert [(r.employee_id, r.prompt_tokens) for r in rows] == [(a["id"], 10), (b["id"], 20)]


def test_employee_position_company_mismatch(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    other = write_client.post("/api/v1/companies", json={"name": "另一家公司"}).json()
    other_position = _create_position(write_client, other["id"], name="外部岗位")

    resp = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={
            "name": "跨界员工", "primary_model_id": conn["id"],
            "positions": [{"position_id": other_position["id"], "is_primary": True}],
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BR_EMPLOYEE_POSITION_COMPANY_MISMATCH"


def test_credentials_unit():
    assert validate_ref("env:TEST_MODEL_KEY") == "env:TEST_MODEL_KEY"
    with pytest.raises(DomainError):
        validate_ref("sk-abcdefgh12345678")
    with pytest.raises(DomainError):
        validate_ref("plain-value")
    with pytest.raises(DomainError) as missing:
        resolve_ref("env:NOT_SET_VAR_XYZ")
    assert missing.value.code == "CREDENTIAL_MISSING"
    assert redact("sk-abcdefgh1234 and Bearer abc") == "*** and ***"


def test_health_cache_ttl_and_invalidate(monkeypatch):
    health_cache.clear()
    key = health_cache.key("conn-1", "fp")
    health_cache.put(key, True, 12)
    assert health_cache.get(key).ok is True

    # 负缓存 60s：时间推进后过期
    fail_key = health_cache.key("conn-2", "fp")
    health_cache.put(fail_key, False, 5)
    import packages.model_gateway.health as health_module

    real_time = health_module.time.time
    monkeypatch.setattr(health_module.time, "time", lambda: real_time() + 61)
    assert health_cache.get(fail_key) is None

    health_cache.put(key, True, 1)
    health_cache.invalidate("conn-1")
    assert health_cache.get(key) is None
    health_cache.clear()


def test_employee_pagination_and_status_filter(write_client, seeded_company, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    conn = _create_connection(write_client, company_id)
    for index in range(3):
        _create_employee(write_client, company_id, conn["id"], name=f"员工{index}")

    page = write_client.get(f"/api/v1/companies/{company_id}/employees?page_size=2")
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 2

    assert write_client.get(
        f"/api/v1/companies/{company_id}/employees?page_size=201"
    ).status_code == 422


def test_employee_positions_expose_can_review(write_client, seeded_company, seeded_connection):
    """前端审核人过滤依赖 employee.positions[].can_review（后端仍硬校验资格）。"""
    company_id = seeded_company["id"]
    reviewer_pos = _create_position(write_client, company_id, "审核岗", can_review=True)
    worker_pos = _create_position(write_client, company_id, "执行岗", can_review=False)
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={
            "name": "双岗员工", "title": "测试",
            "primary_model_id": seeded_connection["id"],
            "positions": [
                {"position_id": reviewer_pos["id"], "is_primary": True},
                {"position_id": worker_pos["id"], "is_primary": False},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    positions = {p["position_id"]: p for p in resp.json()["positions"]}
    assert positions[reviewer_pos["id"]]["can_review"] is True
    assert positions[worker_pos["id"]]["can_review"] is False
